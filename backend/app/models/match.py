from sqlalchemy import Column, Integer, Boolean, String, Text, DateTime, Enum, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum
from app.db.base import Base


class MatchStatus(str, enum.Enum):
    pending = "pending"
    contacted = "contacted"
    submitted = "submitted"
    interviewing = "interviewing"
    offered = "offered"
    placed = "placed"
    rejected = "rejected"


class Match(Base):
    __tablename__ = "matches"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Scoring
    match_score = Column(Integer, nullable=True)
    score_breakdown = Column(JSON, nullable=True)

    # Status
    status = Column(Enum(MatchStatus), default=MatchStatus.pending)
    starred = Column(Boolean, default=False, nullable=False, server_default='false')
    submitted_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    # Outreach draft (persisted per-match)
    draft_subject = Column(Text, nullable=True)
    draft_body = Column(Text, nullable=True)

    # Company page visibility (admin can hide without affecting match/starred status)
    hidden_from_company_page = Column(Boolean, default=False, nullable=False, server_default='false')

    # Client voting on company page (thumbs up/down)
    client_vote = Column(String, nullable=True)  # "up", "down", or null

    # Relationships
    candidate = relationship("Candidate", foreign_keys=[candidate_id])
    role = relationship("Role", foreign_keys=[role_id])
    fit_analysis = relationship("FitAnalysis", foreign_keys="[FitAnalysis.match_id]", uselist=False)
