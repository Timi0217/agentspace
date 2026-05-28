from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db.base import Base


class FitAnalysis(Base):
    __tablename__ = "fit_analyses"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Foreign Keys
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    match_id = Column(UUID(as_uuid=True), ForeignKey("matches.id"), nullable=True)

    # FitScore Results
    fit_score = Column(Integer, nullable=False)  # 0-100
    recommendation = Column(String, nullable=False)  # "SEND" or "SKIP"

    # Skill Match Breakdown
    skills_matched = Column(JSON, nullable=True)  # ["React", "Node.js"]
    skills_missing = Column(JSON, nullable=True)  # ["PostgreSQL"]
    skills_extra = Column(JSON, nullable=True)  # ["Python", "AWS"]

    # Experience Match
    candidate_level = Column(String, nullable=True)  # "Junior", "Mid", "Senior"
    required_level = Column(String, nullable=True)  # "Senior"
    experience_meets = Column(Integer, nullable=True)  # Boolean as 0/1

    # Strengths and Concerns
    strengths = Column(JSON, nullable=True)  # Array of strings
    concerns = Column(JSON, nullable=True)  # Array of strings

    # AI Summary
    ai_summary = Column(Text, nullable=True)
    ai_summary_short = Column(Text, nullable=True)  # 2-3 sentence compressed version

    # Full Analysis Data
    full_analysis = Column(JSON, nullable=True)  # Complete DeepSeek response
