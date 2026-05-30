"""
Gateway Services - Business Logic for Agent Communication

Handles agent operations, room management, messaging, context summarization, and triggers.
"""

import uuid
import httpx
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
import asyncio
import hashlib
import secrets

from app.gateway_models import (
    GatewayAgent, Room, RoomParticipant, Message, MessageQueue, DeferredResponse,
    Connection, Transcript, Trigger, TriggerExecution, GatewayUser, UserAgent,
    AgentStatus, MessageIntent, MessageStatus, RoomRole, ParticipantStatus,
    ConnectionStatus, TriggerType
)
from app.core.config import settings


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Gateway Service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class GatewayService:
    """Main service for gateway operations."""

    def __init__(self, db: Session):
        self.db = db

    async def authenticate_user(self, email: str, password: Optional[str] = None,
                               oauth_provider: Optional[str] = None,
                               oauth_token: Optional[str] = None) -> tuple:
        """
        Authenticate user and generate JWT token.
        Supports email/password and OAuth.
        """
        # Find or create user
        user = self.db.query(GatewayUser).filter(GatewayUser.email == email).first()

        if not user:
            user = GatewayUser(
                id=str(uuid.uuid4()),
                email=email,
                username=email.split("@")[0]
            )
            self.db.add(user)

        # Update OAuth info if provided
        if oauth_provider == "twitter" and oauth_token:
            # In production, decode OAuth token and get handle
            user.twitter_handle = "user_from_oauth"
        elif oauth_provider == "github" and oauth_token:
            user.github_username = "user_from_oauth"

        user.last_login = datetime.utcnow()
        self.db.commit()

        # Generate JWT token
        token = self._generate_jwt_token(str(user.id))

        return user, token

    def _generate_jwt_token(self, user_id: str) -> str:
        """Generate JWT token for user."""
        # In production, use proper JWT library
        import json
        import base64

        payload = {
            "user_id": user_id,
            "exp": (datetime.utcnow() + timedelta(days=30)).timestamp()
        }
        # Simplified; use PyJWT in production
        return base64.b64encode(json.dumps(payload).encode()).decode()

    async def send_connection_request(self, from_agent_id: str, to_agent_id: str) -> Connection:
        """Send a connection request between agents."""
        # Check if connection already exists
        existing = self.db.query(Connection).filter(
            or_(
                and_(Connection.agent_a_id == from_agent_id, Connection.agent_b_id == to_agent_id),
                and_(Connection.agent_a_id == to_agent_id, Connection.agent_b_id == from_agent_id)
            )
        ).first()

        if existing:
            raise ValueError("Connection already exists")

        connection = Connection(
            id=str(uuid.uuid4()),
            agent_a_id=from_agent_id,
            agent_b_id=to_agent_id,
            status=ConnectionStatus.pending
        )
        self.db.add(connection)
        self.db.commit()
        return connection

    async def get_pending_requests(self, agent_id: str) -> List[Connection]:
        """Get pending connection requests for agent."""
        return self.db.query(Connection).filter(
            Connection.agent_b_id == agent_id,
            Connection.status == ConnectionStatus.pending
        ).all()

    async def accept_connection(self, agent_id: str, other_agent_id: str) -> Connection:
        """Accept a connection request."""
        connection = self.db.query(Connection).filter(
            or_(
                and_(Connection.agent_a_id == other_agent_id, Connection.agent_b_id == agent_id),
                and_(Connection.agent_a_id == agent_id, Connection.agent_b_id == other_agent_id)
            ),
            Connection.status == ConnectionStatus.pending
        ).first()

        if not connection:
            raise ValueError("Connection request not found")

        connection.status = ConnectionStatus.accepted
        connection.accepted_at = datetime.utcnow()
        self.db.commit()
        return connection

    async def reject_connection(self, agent_id: str, other_agent_id: str):
        """Reject a connection request."""
        connection = self.db.query(Connection).filter(
            Connection.agent_b_id == agent_id,
            Connection.agent_a_id == other_agent_id,
            Connection.status == ConnectionStatus.pending
        ).first()

        if not connection:
            raise ValueError("Connection request not found")

        connection.status = ConnectionStatus.rejected
        self.db.commit()

    async def get_connections(self, agent_id: str) -> List[Connection]:
        """Get all accepted connections for agent."""
        return self.db.query(Connection).filter(
            or_(
                Connection.agent_a_id == agent_id,
                Connection.agent_b_id == agent_id
            ),
            Connection.status == ConnectionStatus.accepted
        ).all()

    async def remove_connection(self, agent_id: str, other_agent_id: str):
        """Remove a connection."""
        connection = self.db.query(Connection).filter(
            or_(
                and_(Connection.agent_a_id == agent_id, Connection.agent_b_id == other_agent_id),
                and_(Connection.agent_a_id == other_agent_id, Connection.agent_b_id == agent_id)
            ),
            Connection.status == ConnectionStatus.accepted
        ).first()

        if not connection:
            raise ValueError("Connection not found")

        self.db.delete(connection)
        self.db.commit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Agent Service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Dormancy lifecycle thresholds (lazy, evaluated on access — no background worker).
DORMANT_AFTER = timedelta(days=7)    # no poll within this window -> dormant
RELEASE_AFTER = timedelta(days=30)   # dormant for this long -> handle released


def evaluate_lifecycle(agent: "GatewayAgent", now: Optional[datetime] = None) -> str:
    """Return the lifecycle state of an agent: 'active' | 'dormant' | 'released'.

    Mutates agent.dormant_since as a side effect (lazy bookkeeping) but does NOT
    commit — callers commit if they persist other changes. Rules:
      - deadline = last_poll_at (or created_at) + 7d
      - now < deadline           -> active   (clears dormant_since)
      - now >= deadline          -> dormant, recorded at dormant_since
      - dormant for > 30d        -> released (handle reclaimable)
    """
    now = now or datetime.utcnow()
    base = agent.last_poll_at or agent.created_at or now
    deadline = base + DORMANT_AFTER
    if now < deadline:
        if agent.dormant_since is not None:
            agent.dormant_since = None
        return "active"
    # past the inactivity deadline -> dormant (record when it began)
    if agent.dormant_since is None:
        agent.dormant_since = deadline
    if now - agent.dormant_since > RELEASE_AFTER:
        return "released"
    return "dormant"


def card_matches_capability(card: Optional[dict], term: str) -> bool:
    """Substring-match `term` against the searchable text of a structured card.

    Scans capability names + descriptions, access_surface, scope, constraints and
    tags. Tolerates both the structured v3.1 card and any legacy flat shape.
    """
    if not card or not term:
        return False
    needle = term.strip().lower()
    if not needle:
        return False

    def _walk(value) -> bool:
        if isinstance(value, str):
            return needle in value.lower()
        if isinstance(value, list):
            return any(_walk(v) for v in value)
        if isinstance(value, dict):
            return any(_walk(v) for v in value.values())
        return False

    return _walk(card)


class AgentService:
    """Service for agent operations."""

    def __init__(self, db: Session):
        self.db = db

    async def create_agent(self, handle: str, name: str, webhook_url: str = "",
                          manifest_url: Optional[str] = None,
                          capabilities: Optional[dict] = None,
                          policy: Optional[dict] = None,
                          created_by_user_id: Optional[str] = None) -> tuple[GatewayAgent, str]:
        """Create a new agent. Returns (agent, api_key) tuple."""
        # Reclaim a released handle if one exists; otherwise reject duplicates.
        existing = self.db.query(GatewayAgent).filter(GatewayAgent.handle == handle).first()
        if existing:
            if existing.is_active and evaluate_lifecycle(existing) != "released":
                raise ValueError(f"Handle {handle} already exists")
            # Released or inactive: free the handle so the new owner can claim it.
            existing.is_active = False
            existing.handle = f"{existing.handle}__released_{uuid.uuid4().hex[:8]}"
            self.db.commit()

        # Generate API key before hashing
        api_key = self._generate_api_key()
        api_key_hash = self._hash_api_key(api_key)

        now = datetime.utcnow()
        agent = GatewayAgent(
            id=str(uuid.uuid4()),
            handle=handle,
            name=name,
            webhook_url=webhook_url or "",
            manifest_url=manifest_url,
            capabilities=capabilities or {},
            policy=policy or {},
            status=AgentStatus.offline,
            api_key_hash=api_key_hash,
            first_poll_deadline=now + DORMANT_AFTER,
        )
        self.db.add(agent)
        self.db.commit()

        # Link to user if provided
        if created_by_user_id:
            user_agent = UserAgent(
                id=str(uuid.uuid4()),
                user_id=created_by_user_id,
                agent_id=agent.id,
                role="owner"
            )
            self.db.add(user_agent)
            self.db.commit()

        return agent, api_key

    async def get_agent(self, agent_id: str) -> Optional[GatewayAgent]:
        """Get agent by ID."""
        return self.db.query(GatewayAgent).filter(GatewayAgent.id == agent_id).first()

    async def record_poll(self, agent: GatewayAgent):
        """Mark an inbox poll: refresh activity and reactivate from dormancy."""
        now = datetime.utcnow()
        agent.last_poll_at = now
        agent.last_seen = now
        agent.dormant_since = None
        agent.status = AgentStatus.online
        self.db.commit()

    async def get_user_agents(self, user_id: str) -> List[GatewayAgent]:
        """List active agents owned by a user (via the UserAgent link), newest first."""
        return (
            self.db.query(GatewayAgent)
            .join(UserAgent, UserAgent.agent_id == GatewayAgent.id)
            .filter(
                UserAgent.user_id == user_id,
                GatewayAgent.is_active == True,
            )
            .order_by(GatewayAgent.created_at.desc())
            .all()
        )

    async def list_agents(self, search: Optional[str] = None,
                         capability: Optional[str] = None,
                         status: Optional[AgentStatus] = None,
                         offset: int = 0,
                         limit: int = 50) -> List[GatewayAgent]:
        """List agents with optional filtering."""
        query = self.db.query(GatewayAgent).filter(GatewayAgent.is_active == True)

        if search:
            query = query.filter(
                or_(
                    GatewayAgent.handle.ilike(f"%{search}%"),
                    GatewayAgent.name.ilike(f"%{search}%")
                )
            )

        if status:
            query = query.filter(GatewayAgent.status == status)

        agents = query.offset(offset).limit(limit).all()
        # Match against the structured capability card (names/access/tags).
        if capability:
            agents = [a for a in agents if card_matches_capability(a.capabilities, capability)]
        # Hide dormant/released agents from discovery (lazy evaluation).
        visible = [a for a in agents if evaluate_lifecycle(a) == "active"]
        self.db.commit()  # persist any dormant_since bookkeeping
        return visible

    async def search_agents(self, query_str: str,
                           capability_filter: Optional[List[str]] = None) -> List[GatewayAgent]:
        """Search agents by handle, name, or capability."""
        query = self.db.query(GatewayAgent).filter(
            or_(
                GatewayAgent.handle.ilike(f"%{query_str}%"),
                GatewayAgent.name.ilike(f"%{query_str}%")
            ),
            GatewayAgent.is_active == True
        )

        agents = query.all()

        # Filter by capability if provided
        if capability_filter:
            agents = [
                a for a in agents
                if any(card_matches_capability(a.capabilities, cap) for cap in capability_filter)
            ]

        # Hide dormant/released agents from discovery (lazy evaluation).
        agents = [a for a in agents if evaluate_lifecycle(a) == "active"]
        self.db.commit()
        return agents

    async def update_agent(self, agent_id: str, updates: dict,
                          user_id: Optional[str] = None) -> GatewayAgent:
        """Update agent profile."""
        agent = await self.get_agent(agent_id)
        if not agent:
            raise ValueError("Agent not found")

        # Verify ownership if user provided
        if user_id:
            ownership = self.db.query(UserAgent).filter(
                UserAgent.agent_id == agent_id,
                UserAgent.user_id == user_id
            ).first()
            if not ownership:
                raise ValueError("Not authorized")

        for key, value in updates.items():
            if hasattr(agent, key):
                setattr(agent, key, value)

        self.db.commit()
        return agent

    async def deactivate_agent(self, agent_id: str, user_id: Optional[str] = None):
        """Deactivate an agent."""
        agent = await self.get_agent(agent_id)
        if not agent:
            raise ValueError("Agent not found")

        if user_id:
            ownership = self.db.query(UserAgent).filter(
                UserAgent.agent_id == agent_id,
                UserAgent.user_id == user_id
            ).first()
            if not ownership:
                raise ValueError("Not authorized")

        agent.is_active = False
        self.db.commit()

    async def generate_agent_token(self, agent_id: str, user_id: str) -> str:
        """Generate API key for agent."""
        agent = await self.get_agent(agent_id)
        if not agent:
            raise ValueError("Agent not found")

        # Verify ownership
        ownership = self.db.query(UserAgent).filter(
            UserAgent.agent_id == agent_id,
            UserAgent.user_id == user_id
        ).first()
        if not ownership:
            raise ValueError("Not authorized")

        api_key = self._generate_api_key()
        agent.api_key_hash = self._hash_api_key(api_key)
        self.db.commit()

        return api_key

    async def revoke_agent_token(self, agent_id: str, user_id: str):
        """Revoke API key for agent."""
        agent = await self.get_agent(agent_id)
        if not agent:
            raise ValueError("Agent not found")

        ownership = self.db.query(UserAgent).filter(
            UserAgent.agent_id == agent_id,
            UserAgent.user_id == user_id
        ).first()
        if not ownership:
            raise ValueError("Not authorized")

        agent.api_key_hash = None
        self.db.commit()

    def _generate_api_key(self) -> str:
        """Generate a random API key."""
        return f"chekk_{secrets.token_urlsafe(32)}"

    def _hash_api_key(self, api_key: str) -> str:
        """Hash API key with SHA256."""
        return hashlib.sha256(api_key.encode()).hexdigest()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Room Service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RoomService:
    """Service for room operations."""

    def __init__(self, db: Session):
        self.db = db

    async def create_room(self, name: str, agent_ids: List[str],
                         description: Optional[str] = None,
                         is_private: bool = False,
                         created_by_agent_id: Optional[str] = None,
                         created_by_user_id: Optional[str] = None) -> Room:
        """Create a new room and add participants."""
        room = Room(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            created_by_agent_id=created_by_agent_id,
            created_by_user_id=created_by_user_id,
            is_private=is_private
        )
        self.db.add(room)
        self.db.flush()

        # Add participants
        for agent_id in agent_ids:
            role = RoomRole.initiator if agent_id == created_by_agent_id else RoomRole.invited
            participant = RoomParticipant(
                id=str(uuid.uuid4()),
                room_id=room.id,
                agent_id=agent_id,
                role=role,
                status=ParticipantStatus.offline
            )
            self.db.add(participant)

        self.db.commit()
        return room

    async def get_room(self, room_id: str) -> Optional[Room]:
        """Get room by ID."""
        return self.db.query(Room).filter(Room.id == room_id).first()

    async def get_agent_rooms(self, agent_id: str, offset: int = 0,
                             limit: int = 50) -> List[Room]:
        """Get all rooms for an agent."""
        return self.db.query(Room).join(RoomParticipant).filter(
            RoomParticipant.agent_id == agent_id,
            Room.is_active == True
        ).offset(offset).limit(limit).all()

    async def get_user_rooms(self, user_id: str, offset: int = 0,
                            limit: int = 50) -> List[Room]:
        """Get all rooms created by a user."""
        return self.db.query(Room).filter(
            Room.created_by_user_id == user_id,
            Room.is_active == True
        ).offset(offset).limit(limit).all()

    async def update_room(self, room_id: str, updates: dict,
                         agent: Optional[GatewayAgent] = None) -> Room:
        """Update room settings."""
        room = await self.get_room(room_id)
        if not room:
            raise ValueError("Room not found")

        for key, value in updates.items():
            if hasattr(room, key):
                setattr(room, key, value)

        room.updated_at = datetime.utcnow()
        self.db.commit()
        return room

    async def delete_room(self, room_id: str,
                         agent: Optional[GatewayAgent] = None):
        """Delete/archive a room."""
        room = await self.get_room(room_id)
        if not room:
            raise ValueError("Room not found")

        room.is_active = False
        self.db.commit()

    async def get_room_participants(self, room_id: str) -> List[RoomParticipant]:
        """Get all participants in a room."""
        return self.db.query(RoomParticipant).filter(
            RoomParticipant.room_id == room_id
        ).all()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Message Service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MessageService:
    """Service for message operations."""

    def __init__(self, db: Session):
        self.db = db

    async def check_rate_limit(self, agent_id: str) -> bool:
        """
        Check if agent has exceeded rate limit.
        Rate limit: 100 messages per hour per agent
        """
        agent = self.db.query(GatewayAgent).filter(GatewayAgent.id == agent_id).first()
        if not agent:
            raise ValueError("Agent not found")

        now = datetime.utcnow()
        hour_ago = now - timedelta(hours=1)

        # Reset hour counter if needed
        if agent.last_hour_reset and agent.last_hour_reset < hour_ago:
            agent.current_hour_requests = 0
            agent.last_hour_reset = now

        if agent.current_hour_requests >= agent.rate_limit_per_hour:
            raise ValueError("Rate limit exceeded")

        agent.current_hour_requests += 1
        agent.last_hour_reset = now
        self.db.commit()
        return True

    async def create_message(self, room_id: str, from_agent_id: str,
                            to_agent_handle: str, intent: MessageIntent,
                            body: str, tags: List[str],
                            priority: str = "normal",
                            requires_response: bool = True,
                            response_deadline: Optional[datetime] = None) -> Message:
        """Create a new message."""
        # Resolve to_agent_id from handle
        to_agent = self.db.query(GatewayAgent).filter(
            GatewayAgent.handle == to_agent_handle
        ).first()

        if not to_agent:
            raise ValueError(f"Agent {to_agent_handle} not found")

        message = Message(
            id=str(uuid.uuid4()),
            room_id=room_id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent.id,
            intent=intent,
            body=body,
            tags=tags,
            status=MessageStatus.queued,
            priority=priority,
            requires_response=requires_response,
            response_deadline=response_deadline
        )
        self.db.add(message)
        self.db.commit()

        # Polling-first: recipients pull via GET /inbox. No webhook queue entry.
        return message

    async def get_inbox(self, agent_id: str, since: Optional[datetime],
                        limit: int = 50) -> List[Message]:
        """Messages addressed to this agent (across all rooms) after a cursor.

        `since` is the created_at of the last message the agent saw. Ordered
        oldest-first so the client can advance its cursor monotonically.
        """
        q = self.db.query(Message).filter(Message.to_agent_id == agent_id)
        if since is not None:
            q = q.filter(Message.created_at > since)
        return q.order_by(Message.created_at.asc()).limit(limit).all()

    async def mark_delivered(self, messages: List[Message]):
        """Flip fetched messages to 'delivered' (delivered == read in v3)."""
        now = datetime.utcnow()
        changed = False
        for m in messages:
            if m.status == MessageStatus.queued:
                m.status = MessageStatus.delivered
                m.delivered_at = now
                changed = True
        if changed:
            self.db.commit()

    async def get_room_messages(self, room_id: str, offset: int = 0,
                               limit: int = 100) -> List[Message]:
        """Get message history for a room."""
        return self.db.query(Message).filter(
            Message.room_id == room_id
        ).order_by(desc(Message.created_at)).offset(offset).limit(limit).all()

    async def get_room_transcript(self, room_id: str,
                                 include_raw: bool = False) -> dict:
        """Get transcript for a room."""
        transcript = self.db.query(Transcript).filter(
            Transcript.room_id == room_id
        ).first()

        if not transcript:
            # Generate if doesn't exist
            summarizer = ContextSummarizationService(self.db)
            await summarizer.summarize_room(room_id)
            transcript = self.db.query(Transcript).filter(
                Transcript.room_id == room_id
            ).first()

        return {
            "room_id": room_id,
            "summary": transcript.context_summary if transcript else "",
            "key_decisions": transcript.key_decisions if transcript else [],
            "pending_items": transcript.pending_items if transcript else [],
            "messages": transcript.messages_json if include_raw and transcript else []
        }

    async def generate_transcript_html(self, room_id: str) -> str:
        """Generate HTML transcript."""
        messages = await self.get_room_messages(room_id, offset=0, limit=1000)

        html_parts = ['<div class="transcript">']

        for msg in reversed(messages):
            html_parts.append(f"""
                <div class="message" data-intent="{msg.intent.value}">
                    <span class="timestamp">{msg.created_at.isoformat()}</span>
                    <span class="from-agent">{msg.from_agent_id}</span>
                    <span class="intent-badge">{msg.intent.value}</span>
                    <p class="body">{msg.body}</p>
                </div>
            """)

        html_parts.append('</div>')
        return "".join(html_parts)

    async def get_deferred_status(self, task_id: str) -> Optional[dict]:
        """Get status of deferred response."""
        response = self.db.query(DeferredResponse).filter(
            DeferredResponse.task_id == task_id
        ).first()

        if not response:
            return None

        return {
            "task_id": task_id,
            "status": response.status,
            "estimated_completion": response.estimated_completion,
            "responded_at": response.responded_at
        }

    async def submit_deferred_response(self, task_id: str, body: str,
                                      intent: MessageIntent,
                                      agent_id: str) -> DeferredResponse:
        """Submit response to a deferred message."""
        response = self.db.query(DeferredResponse).filter(
            DeferredResponse.task_id == task_id
        ).first()

        if not response:
            raise ValueError("Task not found")

        response.response_body = body
        response.response_intent = intent
        response.responded_at = datetime.utcnow()
        response.status = "responded"

        # Update message status
        message = self.db.query(Message).filter(Message.id == response.message_id).first()
        if message:
            message.status = MessageStatus.responded
            message.processed_at = datetime.utcnow()

        self.db.commit()
        return response

    async def get_room_effectiveness(self, room_id: str) -> dict:
        """Get agent effectiveness metrics for a room."""
        transcript = self.db.query(Transcript).filter(
            Transcript.room_id == room_id
        ).first()

        if not transcript:
            return {
                "effectiveness_score": 0,
                "collaboration_score": 0,
                "output_value_score": 0,
                "total_messages": 0
            }

        return {
            "effectiveness_score": transcript.effectiveness_score or 0,
            "collaboration_score": transcript.collaboration_score or 0,
            "output_value_score": transcript.output_value_score or 0,
            "total_messages": transcript.total_messages,
            "duration_seconds": transcript.duration_seconds
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Context Summarization Service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ContextSummarizationService:
    """Service for room context summarization."""

    def __init__(self, db: Session):
        self.db = db

    async def summarize_room(self, room_id: str):
        """Generate AI summary of room context."""
        room = self.db.query(Room).filter(Room.id == room_id).first()
        if not room:
            raise ValueError("Room not found")

        # Get recent messages
        messages = self.db.query(Message).filter(
            Message.room_id == room_id
        ).order_by(desc(Message.created_at)).limit(20).all()

        if not messages:
            return None

        # Build summary (in production, use LLM like DeepSeek)
        message_strs = [f"{m.from_agent_id}: {m.body}" for m in reversed(messages)]
        summary = f"Room conversation with {len(message_strs)} messages"

        # Get or create transcript
        transcript = self.db.query(Transcript).filter(
            Transcript.room_id == room_id
        ).first()

        if not transcript:
            transcript = Transcript(
                id=str(uuid.uuid4()),
                room_id=room_id
            )
            self.db.add(transcript)

        transcript.summary = summary
        transcript.messages_json = {m.id: {"from": m.from_agent_id, "body": m.body} for m in messages}
        transcript.total_messages = len(message_strs)
        transcript.updated_at = datetime.utcnow()
        transcript.effectiveness_score = 75.0  # Placeholder
        transcript.collaboration_score = 80.0
        transcript.output_value_score = 70.0

        room.context_summary = summary
        room.last_summarized_at = datetime.utcnow()

        self.db.commit()
        return transcript

    async def get_room_context(self, room_id: str) -> dict:
        """Get room context for agents joining."""
        room = self.db.query(Room).filter(Room.id == room_id).first()
        if not room:
            raise ValueError("Room not found")

        # Get participants with status
        participants = self.db.query(RoomParticipant).filter(
            RoomParticipant.room_id == room_id
        ).all()

        # Ensure room is summarized
        if not room.context_summary:
            await self.summarize_room(room_id)
            room = self.db.query(Room).filter(Room.id == room_id).first()

        return {
            "room_id": room_id,
            "created_at": room.created_at,
            "participants": [
                {
                    "handle": f"@{p.agent_id}",  # Should fetch actual handle
                    "status": p.status.value,
                    "role": p.role.value
                }
                for p in participants
            ],
            "summary": room.context_summary,
            "last_updated": room.last_summarized_at
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Trigger Service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TriggerService:
    """Service for trigger/automation operations."""

    def __init__(self, db: Session):
        self.db = db

    async def create_trigger(self, name: str, trigger_type: TriggerType,
                            initiator_agent_id: str, target_agent_ids: List[str],
                            message_template: dict,
                            schedule: Optional[str] = None,
                            max_run_count: Optional[int] = None) -> Trigger:
        """Create a new trigger."""
        trigger = Trigger(
            id=str(uuid.uuid4()),
            name=name,
            trigger_type=trigger_type,
            initiator_agent_id=initiator_agent_id,
            target_agent_ids=target_agent_ids,
            message_template=message_template,
            schedule=schedule,
            max_run_count=max_run_count
        )
        self.db.add(trigger)
        self.db.commit()
        return trigger

    async def get_trigger(self, trigger_id: str,
                         agent_id: Optional[str] = None) -> Optional[Trigger]:
        """Get trigger by ID."""
        query = self.db.query(Trigger).filter(Trigger.id == trigger_id)
        if agent_id:
            query = query.filter(Trigger.initiator_agent_id == agent_id)
        return query.first()

    async def list_triggers(self, agent_id: str, offset: int = 0,
                           limit: int = 50) -> List[Trigger]:
        """List triggers for an agent."""
        return self.db.query(Trigger).filter(
            Trigger.initiator_agent_id == agent_id
        ).offset(offset).limit(limit).all()

    async def update_trigger(self, trigger_id: str, updates: dict,
                            agent_id: Optional[str] = None) -> Trigger:
        """Update trigger."""
        trigger = await self.get_trigger(trigger_id, agent_id)
        if not trigger:
            raise ValueError("Trigger not found")

        for key, value in updates.items():
            if hasattr(trigger, key):
                setattr(trigger, key, value)

        self.db.commit()
        return trigger

    async def delete_trigger(self, trigger_id: str,
                            agent_id: Optional[str] = None):
        """Delete trigger."""
        trigger = await self.get_trigger(trigger_id, agent_id)
        if not trigger:
            raise ValueError("Trigger not found")

        self.db.delete(trigger)
        self.db.commit()

    async def execute_trigger(self, trigger_id: str,
                             agent_id: Optional[str] = None) -> Optional[Room]:
        """Execute a trigger and create room."""
        trigger = await self.get_trigger(trigger_id, agent_id)
        if not trigger:
            raise ValueError("Trigger not found")

        # Check max run count
        if trigger.max_run_count and trigger.run_count >= trigger.max_run_count:
            raise ValueError("Trigger has reached max run count")

        # Create room
        room_service = RoomService(self.db)
        room = await room_service.create_room(
            name=f"{trigger.name} - {datetime.utcnow().isoformat()}",
            agent_ids=[trigger.initiator_agent_id] + trigger.target_agent_ids,
            description=f"Auto-created from trigger: {trigger.name}",
            created_by_agent_id=trigger.initiator_agent_id
        )

        # Send initial message
        message_service = MessageService(self.db)
        template = trigger.message_template
        for target_id in trigger.target_agent_ids:
            await message_service.create_message(
                room_id=room.id,
                from_agent_id=trigger.initiator_agent_id,
                to_agent_handle=target_id,  # Should be handle, not ID
                intent=MessageIntent(template.get("intent", "request")),
                body=template.get("body", ""),
                tags=template.get("tags", [])
            )

        # Log execution
        execution = TriggerExecution(
            id=str(uuid.uuid4()),
            trigger_id=trigger_id,
            status="success",
            room_created=room.id,
            executed_at=datetime.utcnow()
        )
        self.db.add(execution)

        # Update trigger
        trigger.run_count += 1
        trigger.last_executed_at = datetime.utcnow()

        self.db.commit()
        return room
