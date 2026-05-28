from sqlalchemy import Column, String, Integer, DateTime, JSON, Enum
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.db.base import Base


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    stopped = "stopped"


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Job type: ingestion, bulk_analyze, bulk_outreach, targeted_sourcing, analyze_unanalyzed
    job_type = Column(String, nullable=True, default=None)

    # Optional role association (for targeted sourcing, analyze_unanalyzed, etc.)
    role_id = Column(UUID(as_uuid=True), nullable=True)

    # Status
    status = Column(Enum(JobStatus), default=JobStatus.pending)

    # Progress tracking
    total_candidates = Column(Integer, default=0)
    processed_count = Column(Integer, default=0)
    current_batch = Column(Integer, default=0)
    total_batches = Column(Integer, default=0)

    # Search progress
    current_search = Column(String, nullable=True)
    searches_completed = Column(Integer, default=0)
    searches_total = Column(Integer, default=0)

    # Stats
    candidates_saved = Column(Integer, default=0)
    candidates_skipped = Column(Integer, default=0)
    error_count = Column(Integer, default=0)

    # Checkpoint data for resume
    checkpoint_data = Column(JSON, nullable=True)  # Stores: search results, last processed username, etc.

    # Search configuration
    min_behavior_score = Column(Integer, default=30)  # Lowered from 40 to catch more mid-career + hireable candidates

    # Error tracking
    error_message = Column(String, nullable=True)

    # Activity log (keep last 1000 entries)
    recent_logs = Column(JSON, default=list)

    # Final stats
    stats = Column(JSON, nullable=True)
