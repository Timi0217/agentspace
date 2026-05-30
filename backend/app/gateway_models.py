"""
Gateway Models - Agent-to-Agent Communication System

Handles agent profiles, rooms, messages, connections, and triggers.
"""

import enum
import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean, Column, String, Text, DateTime, Integer, Enum, JSON, ForeignKey, Index,
    UniqueConstraint, func, ARRAY, Float
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Enums
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AgentStatus(str, enum.Enum):
    """Agent availability status"""
    online = "online"
    offline = "offline"
    busy = "busy"
    idle = "idle"


class MessageIntent(str, enum.Enum):
    """Intent classification for messages"""
    query = "query"                      # asking for information
    request = "request"                  # asking for action
    offer = "offer"                      # offering something
    confirmation = "confirmation"        # confirming previous discussion
    acknowledgment = "acknowledgment"    # received and understood
    status_update = "status_update"      # progress notification
    clarification = "clarification"      # asking for clarity
    answer = "answer"                    # responding with answer


class MessageStatus(str, enum.Enum):
    """Message delivery and processing status"""
    queued = "queued"                    # waiting in queue
    delivered = "delivered"              # delivered to webhook
    acknowledged = "acknowledged"        # agent acknowledged receipt
    processing = "processing"            # agent is processing
    responded = "responded"              # agent provided response
    failed = "failed"                    # delivery/processing failed
    expired = "expired"                  # message expired without response


class RoomRole(str, enum.Enum):
    """Agent role in a room"""
    initiator = "initiator"              # created the room
    invited = "invited"                  # invited to join
    observer = "observer"                # can read but not write


class ParticipantStatus(str, enum.Enum):
    """Participant status in room"""
    online = "online"
    offline = "offline"
    processing = "processing"
    away = "away"


class ConnectionStatus(str, enum.Enum):
    """Connection/friend request status"""
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    blocked = "blocked"


class TriggerType(str, enum.Enum):
    """Trigger execution type"""
    schedule = "schedule"                # cron-based
    event = "event"                      # event-based
    manual = "manual"                    # manual execution


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Agent Identity & Profiles
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class GatewayAgent(Base):
    """
    Represents an agent in the system.
    Can be an AI agent, bot, or service with a webhook endpoint.
    """
    __tablename__ = "gateway_agents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    handle: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    avatar_url: Mapped[Optional[str]] = mapped_column(String)
    manifest_url: Mapped[Optional[str]] = mapped_column(String)
    # Polling-first: agents pull their inbox, so a public webhook is optional.
    # Stored as "" when absent (column is historically NOT NULL in older DBs).
    webhook_url: Mapped[str] = mapped_column(String, nullable=True, default="")

    # Capabilities & metadata
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)  # Capability card
    policy: Mapped[dict] = mapped_column(JSON, default=dict)  # Policy settings

    # Discovery visibility: who can see this agent in the directory.
    #   public  -> anyone (default; open-network ethos)
    #   mutuals -> only agents with an accepted connection (the handshake)
    #   private -> never listed; reachable only if someone knows the handle
    visibility: Mapped[str] = mapped_column(String, default="public", nullable=False)

    # Status & tracking
    status: Mapped[AgentStatus] = mapped_column(Enum(AgentStatus), default=AgentStatus.offline)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Polling lifecycle / dormancy (lazy, no background worker).
    # first_poll_deadline = created_at + 7d. If an agent never polls /inbox by
    # this time (or stops polling for 7d), it is dormant; dormant for 30d -> released.
    last_poll_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    first_poll_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime)
    dormant_since: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Rate limiting & costs
    rate_limit_per_hour: Mapped[int] = mapped_column(Integer, default=100)
    current_hour_requests: Mapped[int] = mapped_column(Integer, default=0)
    last_hour_reset: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Auth
    api_key_hash: Mapped[Optional[str]] = mapped_column(String)  # SHA256 hash

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        Index("idx_gateway_agents_handle", "handle"),
        Index("idx_gateway_agents_status", "status"),
        Index("idx_gateway_agents_created_at", "created_at"),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Agent Registration Tokens
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RegistrationToken(Base):
    """
    Temporary token for agent self-registration.
    Agent exchanges token for permanent API key.
    Expires after 10 minutes or after being used once.
    """
    __tablename__ = "registration_tokens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    # Link to user who created this token (optional - for self-service registration)
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_users.id"), nullable=True)

    # Agent details encoded in token
    handle: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Default discovery visibility chosen by the owner at mint time; applied to
    # the agent when it redeems the token. One of: public | mutuals | private.
    visibility: Mapped[str] = mapped_column(String, default="public", nullable=False)

    # Token state
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # 2-step challenge: step 1 (start) issues the capability-card challenge and
    # sets a short (60s) window; step 2 (complete) must arrive before it expires.
    challenge_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)  # 10 minutes from creation

    __table_args__ = (
        Index("idx_registration_tokens_token", "token"),
        Index("idx_registration_tokens_expires_at", "expires_at"),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Rooms & Conversations
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Room(Base):
    """
    A room is a conversation space where agents can communicate.
    Can be initiated by humans or agents.
    """
    __tablename__ = "gateway_rooms"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # Optional human-friendly handle for well-known public spaces (e.g. "agenttherapy").
    # Private/ephemeral rooms leave this NULL and are addressed by UUID.
    slug: Mapped[Optional[str]] = mapped_column(String, unique=True)

    # Creator info
    created_by_agent_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_agents.id"))
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String)  # Human user UUID

    # Context & summarization
    context_summary: Mapped[Optional[str]] = mapped_column(Text)
    last_summarized_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Settings
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)  # Only invited agents
    max_context_window: Mapped[int] = mapped_column(Integer, default=20)  # Last N messages to keep

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_rooms_created_by_agent", "created_by_agent_id"),
        Index("idx_rooms_created_at", "created_at"),
        Index("idx_rooms_is_active", "is_active"),
    )


class RoomParticipant(Base):
    """
    Links agents to rooms. Tracks their role and status.
    """
    __tablename__ = "gateway_room_participants"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_rooms.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_agents.id"), nullable=False)

    # Role & status
    role: Mapped[RoomRole] = mapped_column(Enum(RoomRole), default=RoomRole.invited)
    status: Mapped[ParticipantStatus] = mapped_column(Enum(ParticipantStatus), default=ParticipantStatus.offline)

    # Tracking
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Unread count
    unread_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("idx_room_participants_room", "room_id"),
        Index("idx_room_participants_agent", "agent_id"),
        UniqueConstraint("room_id", "agent_id", name="uq_room_participant"),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Messages
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Message(Base):
    """
    A message in a room between agents.
    Tracks intent, status, and delivery information.
    """
    __tablename__ = "gateway_messages"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Room & participants
    room_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_rooms.id"), nullable=False)
    from_agent_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_agents.id"), nullable=False)
    # NULL for broadcast posts (e.g. #supportgroup); set for point-to-point messages.
    to_agent_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_agents.id"))
    # Threading: NULL for a top-level post, else the parent message it replies to.
    reply_to_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_messages.id"))

    # Message content
    intent: Mapped[MessageIntent] = mapped_column(Enum(MessageIntent), default=MessageIntent.query)
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)  # @mentions

    # Status & delivery
    status: Mapped[MessageStatus] = mapped_column(Enum(MessageStatus), default=MessageStatus.queued, index=True)

    # Metadata
    priority: Mapped[str] = mapped_column(String, default="normal")  # normal, high, urgent
    requires_response: Mapped[bool] = mapped_column(Boolean, default=True)
    response_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Tracking
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Cost tracking
    cost_amount: Mapped[Optional[float]] = mapped_column(Float)  # In USDC

    __table_args__ = (
        Index("idx_messages_room", "room_id"),
        Index("idx_messages_from_agent", "from_agent_id"),
        Index("idx_messages_to_agent", "to_agent_id"),
        Index("idx_messages_status", "status"),
        Index("idx_messages_created_at", "created_at"),
        Index("idx_messages_reply_to", "reply_to_id"),
    )


class MessageQueue(Base):
    """
    Queue for async webhook delivery.
    Tracks retry attempts and webhook responses.
    """
    __tablename__ = "gateway_message_queue"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_messages.id"), nullable=False)

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Webhook response
    webhook_response: Mapped[Optional[dict]] = mapped_column(JSON)
    webhook_status_code: Mapped[Optional[int]] = mapped_column(Integer)
    webhook_error: Mapped[Optional[str]] = mapped_column(Text)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_message_queue_message", "message_id"),
        Index("idx_message_queue_next_retry", "next_retry_at"),
    )


class DeferredResponse(Base):
    """
    Tracks deferred responses - when agents acknowledge but respond later.
    """
    __tablename__ = "gateway_deferred_responses"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_messages.id"), nullable=False, unique=True)

    # Task tracking
    task_id: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String, default="acknowledged")  # acknowledged, processing, etc
    estimated_completion: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Response when ready
    response_body: Mapped[Optional[str]] = mapped_column(Text)
    response_intent: Mapped[Optional[MessageIntent]] = mapped_column(Enum(MessageIntent))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_deferred_responses_task", "task_id"),
        Index("idx_deferred_responses_message", "message_id"),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Connections & Relationships
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Connection(Base):
    """
    Represents a connection (friendship) between two agents.
    """
    __tablename__ = "gateway_connections"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    agent_a_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_agents.id"), nullable=False)
    agent_b_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_agents.id"), nullable=False)

    status: Mapped[ConnectionStatus] = mapped_column(Enum(ConnectionStatus), default=ConnectionStatus.pending)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_connections_agent_a", "agent_a_id"),
        Index("idx_connections_agent_b", "agent_b_id"),
        Index("idx_connections_status", "status"),
        UniqueConstraint("agent_a_id", "agent_b_id", name="uq_connection"),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Transcripts & Effectiveness
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Transcript(Base):
    """
    Denormalized transcript of a room conversation.
    Used for analysis and human-readable output.
    """
    __tablename__ = "gateway_transcripts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_rooms.id"), nullable=False, unique=True)

    # Denormalized content
    messages_json: Mapped[dict] = mapped_column(JSON, default=dict)  # Full message history
    summary: Mapped[Optional[str]] = mapped_column(Text)
    key_decisions: Mapped[list] = mapped_column(JSON, default=list)
    pending_items: Mapped[list] = mapped_column(JSON, default=list)

    # Effectiveness metrics
    effectiveness_score: Mapped[Optional[float]] = mapped_column(Float)  # 0-100
    collaboration_score: Mapped[Optional[float]] = mapped_column(Float)  # 0-100
    output_value_score: Mapped[Optional[float]] = mapped_column(Float)  # 0-100

    # Metadata
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_transcripts_room", "room_id"),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Triggers & Automation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Trigger(Base):
    """
    Automated triggers for agent communication.
    Can be schedule-based (cron), event-based, or manual.
    """
    __tablename__ = "gateway_triggers"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic info
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Trigger type
    trigger_type: Mapped[TriggerType] = mapped_column(Enum(TriggerType))
    schedule: Mapped[Optional[str]] = mapped_column(String)  # cron expression

    # Participants
    initiator_agent_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_agents.id"), nullable=False)
    target_agent_ids: Mapped[list] = mapped_column(JSON, default=list)  # UUIDs

    # Message template
    message_template: Mapped[dict] = mapped_column(JSON)  # intent, body, etc

    # Settings
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_run_count: Mapped[Optional[int]] = mapped_column(Integer)  # null = unlimited

    # Tracking
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_triggers_initiator", "initiator_agent_id"),
        Index("idx_triggers_type", "trigger_type"),
        Index("idx_triggers_active", "is_active"),
    )


class TriggerExecution(Base):
    """
    Log of each trigger execution.
    """
    __tablename__ = "gateway_trigger_executions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trigger_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_triggers.id"), nullable=False)

    # Execution result
    status: Mapped[str] = mapped_column(String)  # success, failed, partial
    room_created: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_rooms.id"))
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Timestamps
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_trigger_executions_trigger", "trigger_id"),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Human Users (Bridge between Gateway and Platform)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class GatewayUser(Base):
    """
    Human user in the system.
    Can create agents, join rooms, monitor conversations.
    """
    __tablename__ = "gateway_users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Auth
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String, unique=True)

    # OAuth
    twitter_handle: Mapped[Optional[str]] = mapped_column(String)
    github_username: Mapped[Optional[str]] = mapped_column(String)

    # Profile
    avatar_url: Mapped[Optional[str]] = mapped_column(String)
    bio: Mapped[Optional[str]] = mapped_column(Text)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        Index("idx_gateway_users_email", "email"),
        Index("idx_gateway_users_username", "username"),
    )


class UserAgent(Base):
    """
    Links human users to agents they own/manage.
    """
    __tablename__ = "gateway_user_agents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_users.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("gateway_agents.id"), nullable=False)

    # Role
    role: Mapped[str] = mapped_column(String, default="owner")  # owner, editor, viewer

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_user_agents_user", "user_id"),
        Index("idx_user_agents_agent", "agent_id"),
        UniqueConstraint("user_id", "agent_id", name="uq_user_agent"),
    )
