from sqlalchemy import Column, String, Text, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.db.base import Base


class OutreachMethod(str, enum.Enum):
    email = "email"
    linkedin = "linkedin"
    twitter = "twitter"
    phone = "phone"


class ResponseSentiment(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class OutreachLog(Base):
    __tablename__ = "outreach_log"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Outreach Details
    method = Column(Enum(OutreachMethod), nullable=False)
    template_used = Column(String, nullable=True)
    message_text = Column(Text, nullable=True)

    # Response
    response_received = Column(Boolean, default=False)
    response_date = Column(DateTime, nullable=True)
    response_sentiment = Column(Enum(ResponseSentiment), nullable=True)
    notes = Column(Text, nullable=True)
