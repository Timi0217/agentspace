from sqlalchemy.orm import Session
from sqlalchemy import or_, case
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from app.models import Candidate, Role, Match
from app.schemas import (
    CandidateCreate,
    CandidateUpdate,
    RoleCreate,
    RoleUpdate,
    MatchCreate,
    MatchUpdate,
)


# Candidate CRUD
def create_candidate(db: Session, candidate: CandidateCreate) -> Candidate:
    db_candidate = Candidate(**candidate.model_dump(exclude_unset=True))
    db.add(db_candidate)
    db.commit()
    db.refresh(db_candidate)
    return db_candidate


def get_candidate(db: Session, candidate_id: UUID) -> Optional[Candidate]:
    return db.query(Candidate).filter(Candidate.id == candidate_id).first()


def get_candidate_by_github_username(
    db: Session, github_username: str
) -> Optional[Candidate]:
    # GitHub usernames are case-insensitive, so use case-insensitive lookup
    if not github_username:
        return None
    return (
        db.query(Candidate)
        .filter(Candidate.github_username.ilike(github_username))
        .first()
    )


def get_candidates(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    min_score: Optional[int] = None,
    tech_stack: Optional[List[str]] = None,
    archetype: Optional[str] = None,
    hireable: Optional[bool] = None,
    analyzed: Optional[bool] = None,
    tier: Optional[str] = None,
    location_country: Optional[str] = None,
    has_outreach: Optional[bool] = None,
    opened: Optional[bool] = None,
    screened: Optional[bool] = None,
) -> Dict[str, Any]:
    query = db.query(Candidate)

    if status:
        query = query.filter(Candidate.status == status)

    if min_score:
        query = query.filter(Candidate.fit_score >= min_score)

    if tech_stack:
        # Filter by tech stack overlap - sanitize inputs
        for tech in tech_stack:
            # Validate tech is a safe string (alphanumeric, dash, dot, space, plus)
            if isinstance(tech, str) and tech.replace('-', '').replace('.', '').replace(' ', '').replace('+', '').isalnum():
                query = query.filter(Candidate.tech_stack.contains([tech]))

    if archetype:
        query = query.filter(Candidate.archetype == archetype)

    if hireable is not None:
        query = query.filter(Candidate.github_hireable == hireable)

    if analyzed is not None:
        if analyzed:
            query = query.filter(Candidate.archetype.isnot(None))
        else:
            query = query.filter(Candidate.archetype.is_(None))

    if tier:
        query = query.filter(Candidate.tier == tier)

    if location_country:
        query = query.filter(Candidate.location_country == location_country)

    if has_outreach is not None:
        if has_outreach:
            query = query.filter(Candidate.outreach_status.isnot(None))
        else:
            query = query.filter(Candidate.outreach_status.is_(None))

    if opened is not None:
        if opened:
            # Opened warm-up email but hasn't replied yet
            query = query.filter(
                Candidate.warmup_email_opened_at.isnot(None),
                Candidate.warmup_replied_at.is_(None),
            )

    if screened is not None:
        if screened:
            # Completed screening call
            query = query.filter(Candidate.screening_completed_at.isnot(None))

    # Get total count BEFORE pagination (for accurate "Showing X of Y")
    # IMPORTANT: use a separate count query — with_entities mutates the query
    # and would break the subsequent .order_by().all() call.
    from sqlalchemy import func
    count_query = query.with_entities(func.count(Candidate.id))
    total = count_query.scalar()

    # Order by:
    # 1. source='manual' first (manual adds should always appear at top regardless of score)
    # 2. created_at DESC (newest first) - ensures new candidates appear at top
    # 3. fit_score DESC (highest scores first) - for candidates from same timeframe
    from sqlalchemy import case
    manual_first = case((Candidate.source == 'manual', 0), else_=1)
    candidates = query.order_by(manual_first, Candidate.created_at.desc(), Candidate.fit_score.desc()).offset(skip).limit(limit).all()

    return {"data": candidates, "total": total}


def update_candidate(
    db: Session, candidate_id: UUID, candidate: CandidateUpdate
) -> Optional[Candidate]:
    db_candidate = get_candidate(db, candidate_id)
    if not db_candidate:
        return None

    update_data = candidate.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_candidate, field, value)

    db_candidate.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_candidate)
    return db_candidate


def delete_candidate(db: Session, candidate_id: UUID) -> bool:
    db_candidate = get_candidate(db, candidate_id)
    if not db_candidate:
        return False

    # Delete related records in correct order (respecting foreign key constraints)
    # 1. Delete FitAnalysis records first (they reference matches)
    from app.models.fit_analysis import FitAnalysis
    db.query(FitAnalysis).filter(FitAnalysis.candidate_id == candidate_id).delete()

    # 2. Delete Match records (they reference candidates)
    db.query(Match).filter(Match.candidate_id == candidate_id).delete()

    # 3. Finally delete the candidate
    db.delete(db_candidate)
    db.commit()
    return True


# Role CRUD
def create_role(db: Session, role: RoleCreate) -> Role:
    db_role = Role(**role.model_dump(exclude_unset=True))
    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role


def get_role(db: Session, role_id: UUID) -> Optional[Role]:
    return db.query(Role).filter(Role.id == role_id).first()


def get_role_by_company_and_title(
    db: Session, company_name: str, title: str
) -> Optional[Role]:
    """Check if a role already exists for this company and title."""
    return (
        db.query(Role)
        .filter(
            Role.company_name == company_name,
            Role.title == title
        )
        .first()
    )


def get_role_by_url(db: Session, jd_url: str) -> Optional[Role]:
    """Check if a role already exists with this job URL."""
    if not jd_url:
        return None
    return db.query(Role).filter(Role.jd_url == jd_url).first()


def get_roles(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    company_stage: Optional[str] = None,
    urgency: Optional[str] = None,
) -> List[Role]:
    query = db.query(Role)

    if status:
        query = query.filter(Role.status == status)

    if company_stage:
        query = query.filter(Role.company_stage == company_stage)

    if urgency:
        query = query.filter(Role.urgency == urgency)

    # Order by position first (nulls last), then created_at desc as fallback
    return query.order_by(
        case((Role.position.isnot(None), 0), else_=1),
        Role.position.asc(),
        Role.created_at.desc(),
    ).offset(skip).limit(limit).all()


def update_role(db: Session, role_id: UUID, role: RoleUpdate) -> Optional[Role]:
    db_role = get_role(db, role_id)
    if not db_role:
        return None

    update_data = role.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_role, field, value)

    db_role.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_role)
    return db_role


def delete_role(db: Session, role_id: UUID) -> bool:
    db_role = get_role(db, role_id)
    if not db_role:
        return False

    # Delete related records that reference this role (foreign key constraints)
    from app.models.fit_analysis import FitAnalysis
    db.query(FitAnalysis).filter(FitAnalysis.role_id == role_id).delete()
    db.query(Match).filter(Match.role_id == role_id).delete()

    db.delete(db_role)
    db.commit()
    return True


# Match CRUD
def create_match(db: Session, match: MatchCreate) -> Match:
    db_match = Match(**match.model_dump(exclude_unset=True))
    db.add(db_match)
    db.commit()
    db.refresh(db_match)
    return db_match


def get_match(db: Session, match_id: UUID) -> Optional[Match]:
    return db.query(Match).filter(Match.id == match_id).first()


def get_matches_for_role(
    db: Session, role_id: UUID, skip: int = 0, limit: int = 100
) -> List[Match]:
    from sqlalchemy.orm import joinedload
    return (
        db.query(Match)
        .options(
            joinedload(Match.candidate),
            joinedload(Match.role),
            joinedload(Match.fit_analysis)
        )
        .filter(Match.role_id == role_id)
        .order_by(Match.match_score.desc(), Match.created_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_all_matches(
    db: Session, skip: int = 0, limit: int = 5000, min_score: int = 0
) -> List[Match]:
    from sqlalchemy.orm import joinedload
    q = (
        db.query(Match)
        .options(
            joinedload(Match.candidate),
            joinedload(Match.role),
            joinedload(Match.fit_analysis)
        )
        .order_by(Match.match_score.desc(), Match.created_at.desc())
    )
    if min_score > 0:
        q = q.filter(Match.match_score >= min_score)
    return q.offset(skip).limit(limit).all()


def get_matches_for_candidate(
    db: Session, candidate_id: UUID, skip: int = 0, limit: int = 100
) -> List[Match]:
    from sqlalchemy.orm import joinedload
    return (
        db.query(Match)
        .options(
            joinedload(Match.role),
            joinedload(Match.fit_analysis),
        )
        .filter(Match.candidate_id == candidate_id)
        .order_by(Match.match_score.desc(), Match.created_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def update_match(db: Session, match_id: UUID, match: MatchUpdate) -> Optional[Match]:
    db_match = get_match(db, match_id)
    if not db_match:
        return None

    update_data = match.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_match, field, value)

    db.commit()
    db.refresh(db_match)
    return db_match


def delete_match(db: Session, match_id: UUID) -> bool:
    db_match = get_match(db, match_id)
    if not db_match:
        return False

    db.delete(db_match)
    db.commit()
    return True
