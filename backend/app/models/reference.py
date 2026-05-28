from sqlalchemy import Column, String, Boolean, Text, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.db.base import Base


class ReferenceStatus(str, enum.Enum):
    requested = "requested"
    completed = "completed"
    declined = "declined"
    failed = "failed"


class Reference(Base):
    __tablename__ = "references"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Foreign Key
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)

    # Reference Info
    reference_name = Column(String, nullable=False)
    reference_email = Column(String, nullable=False)
    reference_title = Column(String, nullable=True)
    relationship = Column(String, nullable=False)  # e.g., "former manager at Stripe"

    # Status
    status = Column(Enum(ReferenceStatus), default=ReferenceStatus.requested)

    # VAPI Call Data
    call_id = Column(String, nullable=True)
    call_transcript = Column(Text, nullable=True)
    call_summary = Column(Text, nullable=True)
    call_audio_url = Column(String, nullable=True)

    # Extracted Data
    would_work_again = Column(Boolean, nullable=True)
    strengths = Column(Text, nullable=True)
    areas_to_grow = Column(Text, nullable=True)
    overall_sentiment = Column(String, nullable=True)  # positive/neutral/negative

    # Timestamps
    requested_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
