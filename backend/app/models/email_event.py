from sqlalchemy import Column, String, Text, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
import uuid
import enum
from app.db.base import Base


class EmailEventType(str, enum.Enum):
    # Outbound events (we sent something)
    outreach_sent = "outreach_sent"           # Initial warmup/cold email sent
    screening_sent = "screening_sent"         # Screening questions email sent
    followup_sent = "followup_sent"           # Manual follow-up sent (from Write Follow-up)
    role_pitch_sent = "role_pitch_sent"       # JD-specific outreach or follow-up sent

    # Inbound events (candidate did something)
    email_opened = "email_opened"             # Candidate opened an email
    candidate_replied = "candidate_replied"   # Candidate replied to any email
    screening_answered = "screening_answered" # Candidate's screening answers received
    link_clicked = "link_clicked"             # Candidate clicked a link in email


class EmailEvent(Base):
    __tablename__ = "email_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)

    # Event metadata
    event_type = Column(Enum(EmailEventType), nullable=False)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Email content (for sent/received events)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)

    # Resend tracking
    resend_email_id = Column(String, nullable=True)     # Resend email ID for tracking
    message_id = Column(String, nullable=True)           # SMTP Message-ID for threading

    # Structured data (for screening answers, parsed data, etc.)
    metadata_ = Column("metadata", JSONB, nullable=True)

    # Ordering helper: sequence number within a candidate's chain
    # (auto-incremented per candidate, for deterministic ordering)
    sequence = Column(Integer, nullable=False, default=0)
