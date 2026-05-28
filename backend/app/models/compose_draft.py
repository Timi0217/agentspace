from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSON
from datetime import datetime
import uuid

from app.db.base import Base


class ComposeDraft(Base):
    __tablename__ = "compose_drafts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template = Column(Text, nullable=False)  # The original template/intent
    emails = Column(JSON, nullable=False)  # List of {candidate_id, name, email, subject, body}
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)  # Auto-expire after 24h
