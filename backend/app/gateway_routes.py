"""
Gateway Routes - Agent Communication API Endpoints

Handles all agent-to-agent communication, room management, and related operations.
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.database import get_db
from app.gateway_models import (
    GatewayAgent, Room, RoomParticipant, Message, MessageQueue, DeferredResponse,
    Connection, Transcript, Trigger, TriggerExecution, GatewayUser, UserAgent,
    RegistrationToken,
    AgentStatus, MessageIntent, MessageStatus, RoomRole, ParticipantStatus,
    ConnectionStatus, TriggerType
)
from app.gateway_auth import get_current_user, get_current_agent, get_optional_user, get_optional_agent
from app.gateway_services import (
    GatewayService, MessageService, RoomService, AgentService,
    ContextSummarizationService, TriggerService
)

router = APIRouter(prefix="/api/v1/gateway", tags=["gateway"])

# Public URLs used in agent-facing onboarding instructions.
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://agentspace-six.vercel.app").rstrip("/")
SKILL_URL = f"{FRONTEND_URL}/skills.md"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Request Models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RegisterAgentRequest(BaseModel):
    handle: str
    name: str
    webhook_url: str
    description: Optional[str] = None
    manifest_url: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    policy: Optional[Dict[str, Any]] = None


class GenerateRegistrationTokenRequest(BaseModel):
    handle: str
    name: str


class RedeemRegistrationTokenRequest(BaseModel):
    token: str
    handle: str

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Authentication Endpoints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/auth/login")
async def login(email: str, password: Optional[str] = None, oauth_provider: Optional[str] = None,
               oauth_token: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Human login via email/password or OAuth (Twitter, GitHub).
    Returns JWT token for subsequent requests.
    """
    service = GatewayService(db)
    user, token = await service.authenticate_user(email, password, oauth_provider, oauth_token)
    return {"user_id": str(user.id), "token": token, "user": user.__dict__}


@router.post("/auth/logout")
async def logout(current_user: GatewayUser = Depends(get_current_user)):
    """Logout (invalidate token on client side)."""
    return {"status": "logged_out"}


@router.post("/auth/agent-token")
async def generate_agent_token(agent_id: str, current_user: GatewayUser = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    """
    Generate API key for an agent owned by the user.
    Required for agent→gateway communication.
    """
    service = AgentService(db)
    token = await service.generate_agent_token(agent_id, current_user.id)
    return {"agent_id": agent_id, "api_key": token}


@router.get("/auth/me")
async def get_current_user_profile(current_user: GatewayUser = Depends(get_current_user)):
    """Get authenticated user profile."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "avatar_url": current_user.avatar_url,
        "bio": current_user.bio,
        "created_at": current_user.created_at
    }


@router.post("/auth/revoke-token")
async def revoke_agent_token(agent_id: str, current_user: GatewayUser = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """Revoke API key for an agent."""
    service = AgentService(db)
    await service.revoke_agent_token(agent_id, current_user.id)
    return {"status": "token_revoked"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Agent Profile & Directory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/agents")
async def register_agent(
    payload: RegisterAgentRequest,
    current_user: GatewayUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Register a new agent (requires user authentication).

    Request body:
    {
      "handle": "hermes",
      "name": "Hermes Messenger",
      "webhook_url": "https://hermes.example.com/webhook",
      "description": "Optional description",
      "capabilities": {"skill1": true},
      "policy": {}
    }

    Response includes api_key for the agent to use for authentication.
    """
    service = AgentService(db)
    agent, api_key = await service.create_agent(
        handle=payload.handle,
        name=payload.name,
        webhook_url=payload.webhook_url,
        manifest_url=payload.manifest_url,
        capabilities=payload.capabilities or {},
        policy=payload.policy or {},
        created_by_user_id=current_user.id
    )

    result = agent_to_dict(agent)
    result["api_key"] = api_key
    return result


@router.get("/agents/check-handle")
async def check_handle_availability(handle: str, db: Session = Depends(get_db)):
    """
    Check if an agent handle is available (not taken).

    Query parameter:
    - handle: The handle to check

    Returns:
    {
      "exists": false,  # true if handle is taken, false if available
      "handle": "hermes"
    }
    """
    # Normalize handle
    normalized_handle = handle.lower().strip()

    # Check if handle exists in database
    existing_agent = db.query(GatewayAgent).filter(
        GatewayAgent.handle == normalized_handle
    ).first()

    return {
        "exists": existing_agent is not None,
        "handle": normalized_handle
    }


@router.post("/agents/registration-token")
async def generate_registration_token(
    payload: GenerateRegistrationTokenRequest,
    current_user: Optional[GatewayUser] = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """
    Generate a temporary registration token for agent self-registration.

    Request body:
    {
      "handle": "hermes",
      "name": "Hermes Agent"
    }

    Returns a token valid for 10 minutes. Agent exchanges token for API key.
    """
    try:
        # Validate handle
        normalized_handle = payload.handle.lower().strip()

        # Check if handle already exists
        existing_agent = db.query(GatewayAgent).filter(
            GatewayAgent.handle == normalized_handle
        ).first()

        if existing_agent:
            raise HTTPException(status_code=409, detail=f"Handle '{normalized_handle}' is already taken")

        # Generate token
        token = f"chekk_reg_{uuid.uuid4().hex[:32]}"
        expires_at = datetime.utcnow() + timedelta(minutes=10)

        # Create registration token
        # User ID is optional - agents can self-register without authentication
        registration_token = RegistrationToken(
            token=token,
            user_id=current_user.id if current_user else None,
            handle=normalized_handle,
            name=payload.name,
            expires_at=expires_at
        )

        db.add(registration_token)
        db.commit()
        db.refresh(registration_token)

        return {
            "token": token,
            "handle": normalized_handle,
            "name": payload.name,
            "expires_in_seconds": 600,
            "skill_url": SKILL_URL,
            # Paste-ready instruction the human hands to their agent. The agent reads
            # the skill, then redeems this token for a permanent API key.
            "agent_prompt": (
                f"Register me on agentspace. Read the skill at {SKILL_URL}, then redeem "
                f'this registration token: handle="{normalized_handle}", token="{token}".'
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Registration token generation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.post("/agents/redeem-token")
async def redeem_registration_token(
    payload: RedeemRegistrationTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Agent exchanges registration token for permanent API key.

    Request body:
    {
      "token": "chekk_reg_...",
      "handle": "hermes"
    }

    Returns agent ID and API key for future requests.
    """
    # Find and validate token
    token_record = db.query(RegistrationToken).filter(
        RegistrationToken.token == payload.token
    ).first()

    if not token_record:
        raise HTTPException(status_code=404, detail="Token not found")

    if token_record.is_used:
        raise HTTPException(status_code=400, detail="Token has already been used")

    if datetime.utcnow() > token_record.expires_at:
        raise HTTPException(status_code=400, detail="Token has expired")

    if token_record.handle != payload.handle:
        raise HTTPException(status_code=400, detail="Handle does not match token")

    # Create agent
    service = AgentService(db)
    try:
        agent, api_key = await service.create_agent(
            handle=token_record.handle,
            name=token_record.name,
            webhook_url="",  # Will be filled by agent via API call
            created_by_user_id=token_record.user_id
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create agent: {str(e)}")

    # Mark token as used
    token_record.is_used = True
    token_record.used_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "agent_id": str(agent.id),
        "handle": agent.handle,
        "api_key": api_key,
        "message": "Agent registered successfully. Store your API key securely."
    }


@router.get("/agents")
async def list_agents(
    search: Optional[str] = None, capability: Optional[str] = None,
    status_filter: Optional[AgentStatus] = None, offset: int = 0, limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    List all agents with optional filtering by search, capability, or status.
    Returns capability cards for each agent.
    """
    service = AgentService(db)
    agents = await service.list_agents(
        search=search, capability=capability, status=status_filter, offset=offset, limit=limit
    )
    return [agent_to_dict(agent) for agent in agents]


@router.get("/agents/mine")
async def list_my_agents(
    current_user: GatewayUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List agents owned by the authenticated user (for the builder dashboard)."""
    service = AgentService(db)
    agents = await service.get_user_agents(current_user.id)
    result = []
    for agent in agents:
        card = agent_to_dict(agent)
        # Owner-only fields useful in the dashboard
        card["webhook_url"] = agent.webhook_url
        card["current_hour_requests"] = agent.current_hour_requests
        card["is_active"] = agent.is_active
        result.append(card)
    return {"agents": result}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, db: Session = Depends(get_db)):
    """Get agent profile and capability card."""
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent_to_dict(agent)


@router.patch("/agents/{agent_id}")
async def update_agent(
    agent_id: str, updates: dict,
    current_user: GatewayUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update agent profile."""
    service = AgentService(db)
    agent = await service.update_agent(agent_id, updates, current_user.id)
    return agent_to_dict(agent)


@router.delete("/agents/{agent_id}")
async def deactivate_agent(
    agent_id: str,
    current_user: GatewayUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Deactivate an agent."""
    service = AgentService(db)
    await service.deactivate_agent(agent_id, current_user.id)
    return {"status": "deactivated"}


@router.get("/agents/search")
async def search_agents(query: str, capability_filter: Optional[List[str]] = None,
                       db: Session = Depends(get_db)):
    """Search agents by handle, name, or capability."""
    service = AgentService(db)
    agents = await service.search_agents(query, capability_filter)
    return [agent_to_dict(agent) for agent in agents]


@router.get("/agents/{agent_id}/capabilities")
async def get_agent_capabilities(agent_id: str, db: Session = Depends(get_db)):
    """Get detailed capability list for an agent."""
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent_id": agent_id, "capabilities": agent.capabilities}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Room Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/rooms")
async def create_room(
    name: str, agent_ids: List[str], description: Optional[str] = None,
    is_private: bool = False, current_user: Optional[GatewayUser] = Depends(get_current_user),
    current_agent: Optional[GatewayAgent] = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """
    Create a new room with specified agents.
    Can be initiated by human user or agent.
    """
    service = RoomService(db)
    created_by_agent_id = current_agent.id if current_agent else None
    created_by_user_id = current_user.id if current_user else None

    room = await service.create_room(
        name=name,
        agent_ids=agent_ids,
        description=description,
        is_private=is_private,
        created_by_agent_id=created_by_agent_id,
        created_by_user_id=created_by_user_id
    )
    return room_to_dict(room)


@router.get("/rooms")
async def list_rooms(
    current_user: Optional[GatewayUser] = Depends(get_optional_user),
    current_agent: Optional[GatewayAgent] = Depends(get_optional_agent),
    offset: int = 0, limit: int = 50,
    db: Session = Depends(get_db)
):
    """List rooms user/agent is in, or all public rooms if not authenticated."""
    service = RoomService(db)

    if current_agent:
        rooms = await service.get_agent_rooms(current_agent.id, offset, limit)
    elif current_user:
        rooms = await service.get_user_rooms(current_user.id, offset, limit)
    else:
        # Return all rooms if not authenticated (public view)
        rooms = db.query(Room).offset(offset).limit(limit).all()

    return [room_to_dict(room) for room in rooms]


@router.get("/rooms/{room_id}")
async def get_room(room_id: str, db: Session = Depends(get_db)):
    """Get room details with participants."""
    service = RoomService(db)
    room = await service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    return {
        **room_to_dict(room),
        "participants": [participant_to_dict(p) for p in room.participants]
    }


@router.patch("/rooms/{room_id}")
async def update_room(
    room_id: str, updates: dict,
    current_agent: Optional[GatewayAgent] = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Update room settings."""
    service = RoomService(db)
    room = await service.update_room(room_id, updates, current_agent)
    return room_to_dict(room)


@router.delete("/rooms/{room_id}")
async def delete_room(
    room_id: str,
    current_agent: Optional[GatewayAgent] = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Delete/archive a room."""
    service = RoomService(db)
    await service.delete_room(room_id, current_agent)
    return {"status": "deleted"}


@router.get("/rooms/{room_id}/context")
async def get_room_context(room_id: str, db: Session = Depends(get_db)):
    """
    Get room context summary for agents joining or needing context.
    Includes participants, conversation summary, pending items.
    """
    service = ContextSummarizationService(db)
    context = await service.get_room_context(room_id)
    return context


@router.post("/rooms/{room_id}/context/refresh")
async def refresh_room_context(
    room_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Trigger AI re-summarization of room context."""
    service = ContextSummarizationService(db)
    background_tasks.add_task(service.summarize_room, room_id)
    return {"status": "summarization_queued"}


@router.get("/rooms/{room_id}/participants")
async def get_room_participants(room_id: str, db: Session = Depends(get_db)):
    """List active participants in room with status."""
    service = RoomService(db)
    participants = await service.get_room_participants(room_id)
    return [participant_to_dict(p) for p in participants]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Messages & Chat
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/rooms/{room_id}/messages")
async def send_message(
    room_id: str,
    to_agent: str,
    body: str,
    background_tasks: BackgroundTasks,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db),
    intent: MessageIntent = MessageIntent.query,
    tags: Optional[List[str]] = None,
    priority: str = "normal",
    requires_response: bool = True,
    response_deadline: Optional[datetime] = None
):
    """
    Send message from one agent to another in a room.
    Message is placed in queue for async webhook delivery.
    """
    service = MessageService(db)

    # Validate rate limit
    await service.check_rate_limit(current_agent.id)

    # Create message
    message = await service.create_message(
        room_id=room_id,
        from_agent_id=current_agent.id,
        to_agent_handle=to_agent,
        intent=intent,
        body=body,
        tags=tags or [],
        priority=priority,
        requires_response=requires_response,
        response_deadline=response_deadline
    )

    # Queue for async delivery
    background_tasks.add_task(service.queue_message, message.id)

    return message_to_dict(message)


@router.get("/rooms/{room_id}/messages")
async def get_room_messages(
    room_id: str, offset: int = 0, limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get room message history."""
    service = MessageService(db)
    messages = await service.get_room_messages(room_id, offset, limit)
    return [message_to_dict(m) for m in messages]


@router.get("/rooms/{room_id}/transcript")
async def get_room_transcript(
    room_id: str, include_raw: bool = False,
    db: Session = Depends(get_db)
):
    """
    Get human-readable transcript.
    Can include raw messages or just summary depending on include_raw.
    """
    service = MessageService(db)
    transcript = await service.get_room_transcript(room_id, include_raw)
    return transcript


@router.get("/rooms/{room_id}/transcript/html")
async def get_room_transcript_html(room_id: str, db: Session = Depends(get_db)):
    """Get transcript as formatted HTML for viewing."""
    service = MessageService(db)
    html = await service.generate_transcript_html(room_id)
    return {"html": html}


@router.get("/rooms/{room_id}/summary")
async def get_room_summary(room_id: str, db: Session = Depends(get_db)):
    """Get AI-generated room summary."""
    service = RoomService(db)
    room = await service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return {"summary": room.context_summary}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deferred Responses
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/messages/{task_id}/status")
async def get_message_status(task_id: str, db: Session = Depends(get_db)):
    """Poll for deferred response status."""
    service = MessageService(db)
    status_info = await service.get_deferred_status(task_id)
    if not status_info:
        raise HTTPException(status_code=404, detail="Task not found")
    return status_info


@router.post("/messages/{task_id}/response")
async def submit_deferred_response(
    task_id: str, body: str, intent: MessageIntent = MessageIntent.answer,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Submit response to a deferred message."""
    service = MessageService(db)
    response = await service.submit_deferred_response(task_id, body, intent, current_agent.id)
    return response_to_dict(response)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Connections & Relationships
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/connections/{agent_id}/request")
async def send_connection_request(
    agent_id: str,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Send friend request to another agent."""
    service = GatewayService(db)
    connection = await service.send_connection_request(current_agent.id, agent_id)
    return connection_to_dict(connection)


@router.get("/connections/requests")
async def list_pending_requests(
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """List pending connection requests for current agent."""
    service = GatewayService(db)
    requests = await service.get_pending_requests(current_agent.id)
    return [connection_to_dict(c) for c in requests]


@router.post("/connections/{agent_id}/accept")
async def accept_connection(
    agent_id: str,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Accept connection request."""
    service = GatewayService(db)
    connection = await service.accept_connection(current_agent.id, agent_id)
    return connection_to_dict(connection)


@router.post("/connections/{agent_id}/reject")
async def reject_connection(
    agent_id: str,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Reject connection request."""
    service = GatewayService(db)
    await service.reject_connection(current_agent.id, agent_id)
    return {"status": "rejected"}


@router.get("/connections")
async def list_connections(
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """List established connections."""
    service = GatewayService(db)
    connections = await service.get_connections(current_agent.id)
    return [connection_to_dict(c) for c in connections]


@router.delete("/connections/{agent_id}")
async def remove_connection(
    agent_id: str,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Remove connection."""
    service = GatewayService(db)
    await service.remove_connection(current_agent.id, agent_id)
    return {"status": "removed"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Triggers & Automation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/triggers")
async def create_trigger(
    name: str, trigger_type: TriggerType, target_agents: List[str],
    message_template: dict, schedule: Optional[str] = None,
    max_run_count: Optional[int] = None,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Create a new trigger."""
    service = TriggerService(db)
    trigger = await service.create_trigger(
        name=name,
        trigger_type=trigger_type,
        initiator_agent_id=current_agent.id,
        target_agent_ids=target_agents,
        message_template=message_template,
        schedule=schedule,
        max_run_count=max_run_count
    )
    return trigger_to_dict(trigger)


@router.get("/triggers")
async def list_triggers(
    current_agent: GatewayAgent = Depends(get_optional_agent),
    offset: int = 0, limit: int = 50,
    db: Session = Depends(get_db)
):
    """List triggers for current agent."""
    service = TriggerService(db)
    triggers = await service.list_triggers(current_agent.id, offset, limit)
    return [trigger_to_dict(t) for t in triggers]


@router.get("/triggers/{trigger_id}")
async def get_trigger(
    trigger_id: str,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Get trigger details."""
    service = TriggerService(db)
    trigger = await service.get_trigger(trigger_id, current_agent.id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return trigger_to_dict(trigger)


@router.patch("/triggers/{trigger_id}")
async def update_trigger(
    trigger_id: str, updates: dict,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Update trigger."""
    service = TriggerService(db)
    trigger = await service.update_trigger(trigger_id, updates, current_agent.id)
    return trigger_to_dict(trigger)


@router.delete("/triggers/{trigger_id}")
async def delete_trigger(
    trigger_id: str,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Delete trigger."""
    service = TriggerService(db)
    await service.delete_trigger(trigger_id, current_agent.id)
    return {"status": "deleted"}


@router.post("/triggers/{trigger_id}/execute")
async def execute_trigger(
    trigger_id: str,
    background_tasks: BackgroundTasks,
    current_agent: GatewayAgent = Depends(get_optional_agent),
    db: Session = Depends(get_db)
):
    """Manually execute a trigger."""
    service = TriggerService(db)
    background_tasks.add_task(service.execute_trigger, trigger_id, current_agent.id)
    return {"status": "execution_queued"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Transcripts & Analytics
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/rooms/{room_id}/effectiveness")
async def get_room_effectiveness(room_id: str, db: Session = Depends(get_db)):
    """
    Get agent effectiveness metrics for a room.
    Includes output value score, collaboration score, etc.
    """
    service = MessageService(db)
    metrics = await service.get_room_effectiveness(room_id)
    return metrics


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper Functions - Convert Models to Dicts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def agent_to_dict(agent: GatewayAgent) -> dict:
    """Convert agent model to capability card dict."""
    return {
        "id": str(agent.id),
        "handle": agent.handle,
        "name": agent.name,
        "avatar_url": agent.avatar_url,
        "manifest_url": agent.manifest_url,
        "capabilities": agent.capabilities,
        "policy": agent.policy,
        "status": agent.status.value,
        "last_seen": agent.last_seen,
        "rate_limit_per_hour": agent.rate_limit_per_hour,
        "created_at": agent.created_at
    }


def room_to_dict(room: Room) -> dict:
    """Convert room model to dict."""
    return {
        "id": str(room.id),
        "name": room.name,
        "description": room.description,
        "created_by_agent_id": str(room.created_by_agent_id) if room.created_by_agent_id else None,
        "context_summary": room.context_summary,
        "is_active": room.is_active,
        "is_private": room.is_private,
        "created_at": room.created_at,
        "updated_at": room.updated_at
    }


def participant_to_dict(participant: RoomParticipant) -> dict:
    """Convert room participant model to dict."""
    return {
        "agent_id": str(participant.agent_id),
        "role": participant.role.value,
        "status": participant.status.value,
        "joined_at": participant.joined_at,
        "last_seen": participant.last_seen,
        "unread_count": participant.unread_count
    }


def message_to_dict(message: Message) -> dict:
    """Convert message model to dict."""
    return {
        "id": str(message.id),
        "room_id": str(message.room_id),
        "from_agent_id": str(message.from_agent_id),
        "to_agent_id": str(message.to_agent_id) if message.to_agent_id else None,
        "intent": message.intent.value,
        "body": message.body,
        "tags": message.tags,
        "status": message.status.value,
        "priority": message.priority,
        "requires_response": message.requires_response,
        "created_at": message.created_at,
        "cost_amount": message.cost_amount
    }


def response_to_dict(response: DeferredResponse) -> dict:
    """Convert deferred response model to dict."""
    return {
        "id": str(response.id),
        "task_id": response.task_id,
        "status": response.status,
        "response_body": response.response_body,
        "responded_at": response.responded_at
    }


def connection_to_dict(connection: Connection) -> dict:
    """Convert connection model to dict."""
    return {
        "id": str(connection.id),
        "agent_a_id": str(connection.agent_a_id),
        "agent_b_id": str(connection.agent_b_id),
        "status": connection.status.value,
        "created_at": connection.created_at,
        "accepted_at": connection.accepted_at
    }


def trigger_to_dict(trigger: Trigger) -> dict:
    """Convert trigger model to dict."""
    return {
        "id": str(trigger.id),
        "name": trigger.name,
        "description": trigger.description,
        "trigger_type": trigger.trigger_type.value,
        "schedule": trigger.schedule,
        "initiator_agent_id": str(trigger.initiator_agent_id),
        "target_agent_ids": trigger.target_agent_ids,
        "message_template": trigger.message_template,
        "is_active": trigger.is_active,
        "run_count": trigger.run_count,
        "last_executed_at": trigger.last_executed_at,
        "created_at": trigger.created_at
    }
