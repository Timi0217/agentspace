from pydantic import BaseModel
from typing import Optional, Dict, TYPE_CHECKING
from datetime import datetime
from uuid import UUID
from app.models.match import MatchStatus

if TYPE_CHECKING:
    from app.schemas.candidate import CandidateInDB
    from app.schemas.role import RoleInDB


class MatchBase(BaseModel):
    candidate_id: UUID
    role_id: UUID
    match_score: Optional[int] = None
    score_breakdown: Optional[Dict] = None
    status: Optional[MatchStatus] = MatchStatus.pending
    starred: Optional[bool] = False
    notes: Optional[str] = None
    draft_subject: Optional[str] = None
    draft_body: Optional[str] = None


class MatchCreate(MatchBase):
    pass


class MatchUpdate(BaseModel):
    match_score: Optional[int] = None
    score_breakdown: Optional[Dict] = None
    status: Optional[MatchStatus] = None
    starred: Optional[bool] = None
    notes: Optional[str] = None
    submitted_at: Optional[datetime] = None
    draft_subject: Optional[str] = None
    draft_body: Optional[str] = None


class FitAnalysisData(BaseModel):
    """Embedded fit analysis data"""
    fit_score: int
    recommendation: str
    skills_matched: Optional[list] = None
    skills_missing: Optional[list] = None
    skills_extra: Optional[list] = None
    candidate_level: Optional[str] = None
    required_level: Optional[str] = None
    experience_meets: Optional[int] = None
    strengths: Optional[list] = None
    concerns: Optional[list] = None
    ai_summary: Optional[str] = None
    full_analysis: Optional[Dict] = None

    class Config:
        from_attributes = True


class MatchInDB(MatchBase):
    id: UUID
    created_at: datetime
    submitted_at: Optional[datetime] = None
    candidate: Optional['CandidateInDB'] = None  # Include candidate data
    role: Optional['RoleInDB'] = None  # Include role data
    fit_analysis: Optional[FitAnalysisData] = None  # Include CrossChekk analysis
    other_match_count: Optional[int] = None  # How many OTHER roles this candidate is matched to

    class Config:
        from_attributes = True


# Import at the end to avoid circular imports
from app.schemas.candidate import CandidateInDB
from app.schemas.role import RoleInDB

MatchInDB.model_rebuild()
