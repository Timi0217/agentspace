from sqlalchemy import Column, String, Integer, DateTime, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db.base import Base


class IngestionStatus(Base):
    __tablename__ = "ingestion_status"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Status tracking
    status = Column(String, nullable=False)  # running, completed, failed, stopped
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    stop_requested = Column(Boolean, default=False)  # Set to True to signal stop

    # Progress tracking
    current_search = Column(String, nullable=True)  # Current search query being processed
    searches_completed = Column(Integer, default=0)
    searches_total = Column(Integer, default=0)
    candidates_processed = Column(Integer, default=0)
    candidates_saved = Column(Integer, default=0)
    candidates_skipped = Column(Integer, default=0)

    # Stats
    stats = Column(JSON, nullable=True)  # Detailed stats like hot/warm counts, errors, etc.

    # Latest activity log entries (last 50)
    recent_logs = Column(JSON, nullable=True, default=list)

    # Error tracking
    error_message = Column(String, nullable=True)
    error_count = Column(Integer, default=0)
