from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import and_ as sa_and, or_ as sa_or
from sqlalchemy.orm import Session
from typing import Dict, List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import io
import json
import re

from app.core.logging import get_logger
from app.db.base import get_db

logger = get_logger(__name__)
from app.schemas import (
    CandidateCreate,
    CandidateUpdate,
    CandidateInDB,
    RoleCreate,
    RoleUpdate,
    RoleInDB,
    MatchCreate,
    MatchUpdate,
    MatchInDB,
)
from app.api import crud
from app.models import Candidate, Role, Match
from app.models.candidate import Candidate, CandidateStatus
from app.models.email_event import EmailEventType
from app.services.email_events import append_email_event, get_email_chain
from app.services.candidate_analysis import run_candidate_analysis

router = APIRouter()


# ===========================
# LOCATION NORMALIZATION
# ===========================

_US_STATES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'Washington DC',
}
_STATE_NAMES = {v.lower(): v for v in _US_STATES.values()}
_STATE_NAMES['washington dc'] = 'Washington DC'
_STATE_NAMES['d.c.'] = 'Washington DC'
_STATE_NAMES['district of columbia'] = 'Washington DC'

# City/alias -> US state mapping (covers major cities and common aliases)
_CITY_TO_STATE = {
    # California
    'sf': 'California', 'san francisco': 'California', 'sf bay': 'California',
    'sf bay area': 'California', 'bay area': 'California', 'silicon valley': 'California',
    'los angeles': 'California', 'la': 'California', 'san diego': 'California',
    'san jose': 'California', 'palo alto': 'California', 'santa clara': 'California',
    'sunnyvale': 'California', 'mountain view': 'California', 'cupertino': 'California',
    'menlo park': 'California', 'redwood city': 'California', 'berkeley': 'California',
    'oakland': 'California', 'sacramento': 'California', 'fresno': 'California',
    'socal': 'California', 'norcal': 'California', 'bay': 'California',
    # New York
    'nyc': 'New York', 'new york city': 'New York', 'brooklyn': 'New York',
    'manhattan': 'New York', 'queens': 'New York', 'bronx': 'New York',
    'buffalo': 'New York', 'rochester': 'New York',
    # Illinois
    'chicago': 'Illinois', 'chicagoland': 'Illinois',
    # Texas
    'houston': 'Texas', 'dallas': 'Texas', 'austin': 'Texas', 'san antonio': 'Texas',
    'fort worth': 'Texas', 'dfw': 'Texas', 'plano': 'Texas',
    # Florida
    'miami': 'Florida', 'orlando': 'Florida', 'tampa': 'Florida',
    'jacksonville': 'Florida', 'fort lauderdale': 'Florida', 'st petersburg': 'Florida',
    # Georgia
    'atlanta': 'Georgia', 'atl': 'Georgia', 'savannah': 'Georgia',
    # Washington
    'seattle': 'Washington', 'tacoma': 'Washington', 'bellevue': 'Washington',
    'redmond': 'Washington', 'kirkland': 'Washington',
    # Massachusetts
    'boston': 'Massachusetts', 'cambridge': 'Massachusetts',
    # Oregon
    'portland': 'Oregon', 'eugene': 'Oregon', 'bend': 'Oregon',
    # Colorado
    'denver': 'Colorado', 'boulder': 'Colorado', 'colorado springs': 'Colorado',
    # Arizona
    'phoenix': 'Arizona', 'tucson': 'Arizona', 'scottsdale': 'Arizona',
    'tempe': 'Arizona', 'mesa': 'Arizona',
    # Michigan
    'detroit': 'Michigan', 'ann arbor': 'Michigan', 'grand rapids': 'Michigan',
    # Minnesota
    'minneapolis': 'Minnesota', 'st paul': 'Minnesota',
    # North Carolina
    'charlotte': 'North Carolina', 'raleigh': 'North Carolina', 'durham': 'North Carolina',
    'research triangle': 'North Carolina', 'chapel hill': 'North Carolina',
    # Pennsylvania
    'philadelphia': 'Pennsylvania', 'pittsburgh': 'Pennsylvania', 'philly': 'Pennsylvania',
    # Ohio
    'columbus': 'Ohio', 'cleveland': 'Ohio', 'cincinnati': 'Ohio',
    # Virginia
    'richmond': 'Virginia', 'arlington': 'Virginia', 'reston': 'Virginia',
    # Tennessee
    'nashville': 'Tennessee', 'memphis': 'Tennessee', 'knoxville': 'Tennessee',
    # Maryland
    'baltimore': 'Maryland', 'bethesda': 'Maryland',
    # Missouri
    'st louis': 'Missouri', 'kansas city': 'Missouri',
    # Nevada
    'las vegas': 'Nevada', 'reno': 'Nevada',
    # Indiana
    'indianapolis': 'Indiana',
    # Wisconsin
    'milwaukee': 'Wisconsin', 'madison': 'Wisconsin',
    # Utah
    'salt lake city': 'Utah', 'provo': 'Utah',
    # Connecticut
    'hartford': 'Connecticut', 'new haven': 'Connecticut',
    # Washington DC
    'washington dc': 'Washington DC', 'dc': 'Washington DC',
}

# Canadian city/province mapping
_CANADIAN_LOCATIONS = {
    'montreal': 'Canada', 'toronto': 'Canada', 'vancouver': 'Canada',
    'ottawa': 'Canada', 'calgary': 'Canada', 'edmonton': 'Canada',
    'winnipeg': 'Canada', 'quebec': 'Canada', 'québec': 'Canada',
    'ontario': 'Canada', 'bc': 'Canada', 'british columbia': 'Canada',
    'waterloo': 'Canada', 'kitchener': 'Canada', 'kitchener-waterloo': 'Canada',
    'university of waterloo': 'Canada', 'university of montreal': 'Canada',
    'qc': 'Canada', 'on': 'Canada',
}

_COUNTRIES = {
    'uk': 'United Kingdom', 'united kingdom': 'United Kingdom', 'england': 'United Kingdom',
    'scotland': 'United Kingdom', 'wales': 'United Kingdom',
    'germany': 'Germany', 'deutschland': 'Germany',
    'india': 'India', 'canada': 'Canada', 'canada🇨🇦': 'Canada', 'canadá': 'Canada',
    'australia': 'Australia',
    'france': 'France', 'brazil': 'Brazil', 'brasil': 'Brazil',
    'japan': 'Japan', 'china': 'China', 'netherlands': 'Netherlands',
    'spain': 'Spain', 'italy': 'Italy', 'sweden': 'Sweden',
    'poland': 'Poland', 'portugal': 'Portugal', 'ireland': 'Ireland',
    'nigeria': 'Nigeria', 'kenya': 'Kenya', 'south africa': 'South Africa',
    'israel': 'Israel', 'singapore': 'Singapore', 'south korea': 'South Korea',
    'mexico': 'Mexico', 'argentina': 'Argentina', 'colombia': 'Colombia',
    'indonesia': 'Indonesia', 'turkey': 'Turkey', 'türkiye': 'Turkey', 'russia': 'Russia',
    'ukraine': 'Ukraine', 'romania': 'Romania', 'czech republic': 'Czech Republic',
    'switzerland': 'Switzerland', 'austria': 'Austria', 'belgium': 'Belgium',
    'denmark': 'Denmark', 'norway': 'Norway', 'finland': 'Finland',
    'new zealand': 'New Zealand', 'taiwan': 'Taiwan', 'vietnam': 'Vietnam',
    'pakistan': 'Pakistan', 'bangladesh': 'Bangladesh', 'philippines': 'Philippines',
    'egypt': 'Egypt', 'ghana': 'Ghana', 'ethiopia': 'Ethiopia',
    'chile': 'Chile', 'hong kong': 'Hong Kong', 'georgia (sakartvelo)': 'Georgia (Country)',
    'tbilisi': 'Georgia (Country)', 'kazakhstan': 'Kazakhstan',
    'europe': 'Europe', 'seoul': 'South Korea', 'bangalore': 'India',
    'santiago': 'Chile', 'santiago de chile': 'Chile',
}


def _normalize_location(raw: str) -> str:
    """Normalize raw location string to US state or country."""
    import re
    if not raw or not raw.strip():
        return ''

    text = raw.strip()

    # Strip emojis and special unicode characters
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text)  # supplementary planes (most emojis)
    text = re.sub(r'[\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f\u200d]', '', text)  # misc symbols
    text = text.strip()

    if not text:
        return ''

    # Strip trailing noise (country-level suffixes)
    for noise in [', Planet Earth', ', Earth', 'Planet Earth',
                  ', USA', ', US', ', U.S.A.', ', U.S.',
                  ', United States of America', ', United States']:
        if text.lower().endswith(noise.lower()):
            text = text[:len(text) - len(noise)].strip().rstrip(',')

    # Remove "Remote" prefix/suffix
    text = re.sub(r'\bRemote\b[,\s\-]*', '', text, flags=re.IGNORECASE).strip().rstrip(',').strip()
    if not text:
        return 'Remote'

    # Check full text (including parentheticals) against countries BEFORE stripping parens
    # This handles entries like "Georgia (Sakartvelo)" which are in _COUNTRIES
    text_lower_pre = text.lower().strip()
    if text_lower_pre in _COUNTRIES:
        return _COUNTRIES[text_lower_pre]

    # Clean trailing/leading punctuation artifacts
    text = text.strip('()').strip()

    # Split by pipe, tilde, arrow, comma, slash, or + (multi-location entries)
    # Return the FIRST recognizable location from multi-location strings
    segments = re.split(r'[|~]|->|<>', text)
    if len(segments) > 1:
        for seg in segments:
            seg = seg.strip()
            if seg:
                result = _normalize_location(seg)  # recurse on each segment
                if result and result not in ('', 'Remote'):
                    return result

    # Now process as single location
    # Split by comma, slash, or +
    parts = re.split(r'[,/+]', text)
    # Strip dots, trailing/leading whitespace from each part
    parts = [re.sub(r'\.(\s)', r'\1', p).strip().rstrip('.') for p in parts if p.strip()]
    if not parts:
        return ''

    # Clean noise words from parts
    cleaned_parts = []
    for p in parts:
        # Remove parenthetical content like "(Colorado)" or "(Pa)" - extract state if possible
        paren_match = re.search(r'\(([^)]+)\)', p)
        if paren_match:
            inner = paren_match.group(1).strip()
            if inner.upper() in _US_STATES:
                return _US_STATES[inner.upper()]
            if inner.lower() in _STATE_NAMES:
                return _STATE_NAMES[inner.lower()]
            if inner.lower() in _COUNTRIES:
                return _COUNTRIES[inner.lower()]
        p = re.sub(r'\([^)]*\)', '', p).strip()

        # Remove leading noise phrases FIRST
        p = re.sub(r'^(greater|sometimes)\s+', '', p, flags=re.IGNORECASE).strip()
        # Remove trailing noise phrases (careful: only match at word boundaries after content)
        p = re.sub(r'\s+(or around|and beyond|and surrounding|burbs|suburbs|metro|metropolitan|area|region|open to relocation)(\s.*)?$', '', p, flags=re.IGNORECASE).strip()
        # Remove zip codes
        p = re.sub(r'\s*\d{5}(-\d{4})?$', '', p).strip().rstrip('.')
        # Remove bullet/dot separators with trailing text like "• Open To Relocation"
        p = re.sub(r'\s*[•·]\s*.*$', '', p).strip()
        # Remove semicolons and everything after
        p = re.sub(r'\s*;.*$', '', p).strip()
        # Remove trailing periods and extra whitespace
        p = p.strip().rstrip('.')
        if p:
            cleaned_parts.append(p)

    if not cleaned_parts:
        return ''

    # Try the full cleaned text first against city/alias lookup
    full_text = ' '.join(cleaned_parts).strip()
    full_lower = full_text.lower()

    # Direct city/alias lookup on full text
    if full_lower in _CITY_TO_STATE:
        return _CITY_TO_STATE[full_lower]
    if full_lower in _CANADIAN_LOCATIONS:
        return _CANADIAN_LOCATIONS[full_lower]
    if full_lower in _COUNTRIES:
        return _COUNTRIES[full_lower]

    # Check parts right-to-left for US state abbreviation or name
    for part in reversed(cleaned_parts):
        upper = part.upper().strip()
        if upper in _US_STATES:
            return _US_STATES[upper]
        lower = part.lower().strip()
        if lower in _STATE_NAMES:
            return _STATE_NAMES[lower]

    # Check each part against city/alias lookups
    for part in cleaned_parts:
        lower = part.lower().strip()
        if lower in _CITY_TO_STATE:
            return _CITY_TO_STATE[lower]
        if lower in _CANADIAN_LOCATIONS:
            return _CANADIAN_LOCATIONS[lower]

    # Check for country names in parts
    for part in reversed(cleaned_parts):
        lower = part.lower().strip()
        if lower in _COUNTRIES:
            return _COUNTRIES[lower]

    # Try prefix matching: if a part starts with a known city name, use that city's state
    for part in cleaned_parts:
        lower = part.lower().strip()
        # Try longest match first (e.g., "san francisco" before "san")
        for city, state in sorted(_CITY_TO_STATE.items(), key=lambda x: -len(x[0])):
            if lower.startswith(city + ' ') or lower.startswith(city + '-') or lower == city:
                return state
        for city, country in sorted(_CANADIAN_LOCATIONS.items(), key=lambda x: -len(x[0])):
            if lower.startswith(city + ' ') or lower.startswith(city + '-') or lower == city:
                return country

    # Try multi-word state name matching in the full text
    for state_name, canonical in _STATE_NAMES.items():
        if state_name in full_lower:
            return canonical

    # Single word checks (skip 2-letter words that could be false positives like "or", "in")
    words = full_text.split()
    for word in reversed(words):
        w = word.strip().rstrip('.')
        if len(w) <= 2 and w.lower() in ('or', 'in', 'an', 'at', 'to', 'of', 'by', 'it', 'is', 'no', 'so', 'do', 'me', 'my', 'up'):
            continue  # skip common English words that happen to be state abbreviations
        if w.upper() in _US_STATES:
            return _US_STATES[w.upper()]
        if w.lower() in _STATE_NAMES:
            return _STATE_NAMES[w.lower()]
        if w.lower() in _CITY_TO_STATE:
            return _CITY_TO_STATE[w.lower()]

    # If it contains a street address pattern (numbers + words), skip it
    if re.match(r'^\d+\s+', full_text):
        return ''

    # If nothing matched but it has content, check if it's a state name embedded
    # in a longer string (e.g., "Arizona State University" contains "Arizona")
    for state_name, canonical in sorted(_STATE_NAMES.items(), key=lambda x: -len(x[0])):
        if state_name in full_lower:
            return canonical

    # Return empty for unrecognizable locations to filter them out
    return ''


def _get_raw_locations_for_normalized(db, normalized_value: str, base_query=None):
    """Given a normalized location, find all raw location_country values that normalize to it."""
    from sqlalchemy import distinct
    if base_query is not None:
        raw_locs = [r[0] for r in base_query.with_entities(distinct(Candidate.location_country)).filter(
            Candidate.location_country.isnot(None)
        ).all()]
    else:
        raw_locs = [r[0] for r in db.query(distinct(Candidate.location_country)).filter(
            Candidate.location_country.isnot(None)
        ).all()]
    return [raw for raw in raw_locs if _normalize_location(raw) == normalized_value]


# Candidate Routes
@router.post("/candidates/", response_model=CandidateInDB, tags=["candidates"])
def create_candidate(
    candidate: CandidateCreate,
    db: Session = Depends(get_db),
    upsert: bool = Query(False, description="If true, return existing candidate instead of error")
):
    """Create a new candidate"""
    # Check if github_username already exists
    if candidate.github_username:
        existing = crud.get_candidate_by_github_username(db, candidate.github_username)
        if existing:
            # Log the collision for debugging
            logger.info("Found existing candidate: ID=%s, username=%s, status=%s, created=%s", existing.id, existing.github_username, existing.status, existing.created_at)

            # If upsert=true, return existing candidate instead of error
            if upsert:
                logger.info("Returning existing candidate %s", existing.github_username)
                return existing

            raise HTTPException(
                status_code=400,
                detail=f"Candidate with github username {candidate.github_username} already exists (ID: {existing.id}, status: {existing.status}, created: {existing.created_at})",
            )

    # Check if email already exists (if provided)
    if candidate.email:
        existing = db.query(Candidate).filter(
            Candidate.email.ilike(candidate.email)
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Candidate with email {candidate.email} already exists",
            )

    return crud.create_candidate(db, candidate)


@router.get("/candidates/search", tags=["candidates"])
def search_candidates(
    q: str,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """Search candidates by name or GitHub username. Returns lightweight results for autocomplete."""
    from sqlalchemy import or_
    query = db.query(Candidate).filter(
        or_(
            Candidate.name.ilike(f"%{q}%"),
            Candidate.github_username.ilike(f"%{q}%"),
        )
    ).limit(limit)
    results = query.all()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "github_username": c.github_username,
            "archetype": c.archetype,
            "tier": c.tier,
        }
        for c in results
    ]


@router.get("/candidates/", tags=["candidates"])
def list_candidates(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    min_score: Optional[int] = None,
    tech_stack: Optional[List[str]] = Query(None),
    archetype: Optional[str] = None,
    hireable: Optional[bool] = None,
    analyzed: Optional[bool] = None,
    tier: Optional[str] = None,
    location_country: Optional[str] = None,
    has_outreach: Optional[bool] = None,
    opened: Optional[bool] = None,
    screened: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """List candidates with optional filters. Returns {data: [...], total: N}."""
    result = crud.get_candidates(
        db, skip=skip, limit=limit, status=status, min_score=min_score,
        tech_stack=tech_stack, archetype=archetype, hireable=hireable,
        analyzed=analyzed, tier=tier, location_country=location_country,
        has_outreach=has_outreach, opened=opened, screened=screened,
    )
    # Serialize ORM objects via Pydantic so FastAPI can encode the dict
    return {
        "data": [CandidateInDB.model_validate(c) for c in result["data"]],
        "total": result["total"],
    }


@router.get("/candidates/filter-options", tags=["candidates"])
def get_candidate_filter_options(db: Session = Depends(get_db)):
    """Get distinct values for filter dropdowns (locations, languages, archetypes, tiers)"""
    from sqlalchemy import func, distinct

    locations = [r[0] for r in db.query(distinct(Candidate.location_country)).filter(
        Candidate.location_country.isnot(None)
    ).all()]

    archetypes = [r[0] for r in db.query(distinct(Candidate.archetype)).filter(
        Candidate.archetype.isnot(None)
    ).all()]

    tiers = [r[0] for r in db.query(distinct(Candidate.tier)).filter(
        Candidate.tier.isnot(None)
    ).all()]

    # Get unique languages from JSON array column
    from sqlalchemy import text
    try:
        lang_rows = db.execute(text(
            "SELECT DISTINCT lang FROM candidates, jsonb_array_elements_text(github_languages) AS lang ORDER BY lang"
        )).fetchall()
        languages = [r[0] for r in lang_rows]
    except Exception:
        languages = []

    return {
        "locations": sorted(locations),
        "archetypes": sorted(archetypes),
        "tiers": tiers,
        "languages": languages,
    }


@router.get("/candidates/dormant", tags=["candidates"])
def list_dormant_candidates(
    reason: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List dormant candidates, ordered by most recently made dormant (updated_at desc).
    Optional reason filter: 'manual', 'auto_no_reply', or omit for all."""
    # Run auto-dormant sweep first so newly eligible candidates appear immediately
    from app.models.candidate import OutreachStatus as _OS
    _cutoff = datetime.utcnow() - timedelta(days=3)
    _stale = (
        db.query(Candidate)
        .filter(
            Candidate.outreach_status == _OS.sent,
            Candidate.followup_sent_at.isnot(None),
            Candidate.followup_sent_at <= _cutoff,
            Candidate.warmup_replied_at.is_(None),
            Candidate.dormant != True,
        )
        .all()
    )
    if _stale:
        for _c in _stale:
            _c.status = CandidateStatus.rejected
            _c.dormant = True
            _c.dormant_reason = "auto_no_reply"
        db.commit()
        logger.info("Auto-dormant sweep (dormant list): moved %d candidate(s)", len(_stale))

    query = db.query(Candidate).filter(Candidate.dormant == True)
    if reason:
        query = query.filter(Candidate.dormant_reason == reason)
    total = query.count()
    candidates = query.order_by(Candidate.updated_at.desc()).offset(skip).limit(limit).all()

    # Count by reason for tab badges
    auto_count = db.query(Candidate).filter(Candidate.dormant == True, Candidate.dormant_reason == "auto_no_reply").count()
    manual_count = db.query(Candidate).filter(Candidate.dormant == True, Candidate.dormant_reason == "manual").count()

    return {
        "data": [CandidateInDB.model_validate(c) for c in candidates],
        "total": total,
        "auto_count": auto_count,
        "manual_count": manual_count,
    }


@router.get("/candidates/counts", tags=["candidates"])
def get_candidate_counts(db: Session = Depends(get_db)):
    """Get aggregated counts for all candidate filters"""
    from sqlalchemy import func
    from ..models.candidate import Candidate

    # Get total count
    total = db.query(func.count(Candidate.id)).scalar()

    # Get counts by status
    status_counts = db.query(
        Candidate.status,
        func.count(Candidate.id)
    ).group_by(Candidate.status).all()

    # Get analyzed/unanalyzed counts
    analyzed_count = db.query(func.count(Candidate.id)).filter(
        Candidate.archetype.isnot(None)
    ).scalar()
    unanalyzed_count = total - analyzed_count

    # Get hireable count
    hireable_count = db.query(func.count(Candidate.id)).filter(
        Candidate.github_hireable == True
    ).scalar()

    # Get outreach counts
    outreach_drafted_count = db.query(func.count(Candidate.id)).filter(
        Candidate.outreach_status.isnot(None)
    ).scalar()
    no_outreach_count = total - outreach_drafted_count

    # Get "opened but not replied" count (between contacted and warm)
    opened_count = db.query(func.count(Candidate.id)).filter(
        Candidate.warmup_email_opened_at.isnot(None),
        Candidate.warmup_replied_at.is_(None),
    ).scalar()

    # Get "screened" count (completed screening call)
    screened_count = db.query(func.count(Candidate.id)).filter(
        Candidate.screening_completed_at.isnot(None),
    ).scalar()

    # Pipeline stats
    from ..models.match import Match
    from ..models.candidate import OutreachStatus
    starred_count = db.query(func.count(func.distinct(Match.candidate_id))).filter(
        Match.starred == True,
    ).scalar()
    total_matches = db.query(func.count(Match.id)).scalar()
    scheduled_count = db.query(func.count(Candidate.id)).filter(
        Candidate.outreach_status == OutreachStatus.scheduled,
    ).scalar()
    sent_count = db.query(func.count(Candidate.id)).filter(
        Candidate.outreach_status == OutreachStatus.sent,
    ).scalar()
    contacted_count = db.query(func.count(Candidate.id)).filter(
        Candidate.outreach_status == OutreachStatus.sent,
    ).scalar()
    replied_count = db.query(func.count(Candidate.id)).filter(
        Candidate.warmup_replied_at.isnot(None),
    ).scalar()

    # Build response
    counts = {
        'all': total,
        'analyzed': analyzed_count,
        'unanalyzed': unanalyzed_count,
        'hireable': hireable_count,
        'has_outreach': outreach_drafted_count,
        'no_outreach': no_outreach_count,
        'opened': opened_count,
        'screened': screened_count,
        # Pipeline stats
        'starred': starred_count,
        'total_matches': total_matches,
        'scheduled': scheduled_count,
        'sent': sent_count,
        'contacted': contacted_count,
        'replied': replied_count,
    }

    # Add status counts
    for status, count in status_counts:
        if status:
            counts[status] = count

    return counts


def _build_funnel(candidates_query, include_distributions: bool = False):
    """Build funnel stats from a query of candidates.

    If include_distributions is True, each stage includes a 'distributions' dict
    with breakdowns by location, tier, and archetype.
    """
    from sqlalchemy import func as sa_func

    # Define the stages with their filter conditions
    stages_config = [
        ("Warm-up Sent", None, "email"),                               # total = no extra filter
        ("Email Opened", Candidate.warmup_email_opened_at.isnot(None), "opened"),
        ("Replied", Candidate.warmup_replied_at.isnot(None), "replied"),
        ("Questions Sent", Candidate.screening_link_sent_at.isnot(None), "screening_sent"),
        ("Questions Opened", Candidate.screening_email_opened_at.isnot(None), "screening_opened"),
        ("Answered", Candidate.screening_status.in_(["answered", "completed"]), "completed"),
        ("Warm", sa_or(
            sa_and(Candidate.screening_status.in_(["answered", "completed"]), Candidate.screening_transcript.isnot(None), Candidate.screening_transcript != ""),
            Candidate.manually_warmed == True,
        ), "warm"),
    ]

    funnel = []
    for stage_name, condition, icon in stages_config:
        stage_query = candidates_query
        if condition is not None:
            stage_query = stage_query.filter(condition)
        count = stage_query.count()

        stage = {"stage": stage_name, "count": count, "icon": icon}

        if include_distributions and count > 0:
            # Location distribution
            loc_rows = stage_query.with_entities(
                Candidate.location_country, sa_func.count()
            ).group_by(Candidate.location_country).all()
            loc_dist = {}
            for loc, cnt in loc_rows:
                loc_dist[loc or "Unknown"] = cnt

            # Tier distribution
            tier_rows = stage_query.with_entities(
                Candidate.tier, sa_func.count()
            ).group_by(Candidate.tier).all()
            tier_dist = {}
            for tier, cnt in tier_rows:
                tier_dist[tier or "Unknown"] = cnt

            # Archetype distribution
            arch_rows = stage_query.with_entities(
                Candidate.archetype, sa_func.count()
            ).group_by(Candidate.archetype).all()
            arch_dist = {}
            for arch, cnt in arch_rows:
                arch_dist[arch or "Unknown"] = cnt

            stage["distributions"] = {
                "location": loc_dist,
                "tier": tier_dist,
                "archetype": arch_dist,
            }

        funnel.append(stage)

    return funnel


@router.get("/candidates/outreach-queue/stats", tags=["outreach"])
def get_outreach_stats(
    db: Session = Depends(get_db),
):
    """Aggregate funnel stats across all sent candidates, plus per-cohort breakdown."""
    from sqlalchemy import distinct, func as sa_func

    # Auto-backfill: check for replied candidates missing reply text
    from app.core.config import settings
    missing_reply_text = db.query(Candidate).filter(
        Candidate.warmup_replied_at.isnot(None),
        (Candidate.warmup_reply_text.is_(None)) | (Candidate.warmup_reply_text == "")
    ).count()
    if missing_reply_text > 0:
        logger.info("Found %d candidates with replies but no text, triggering backfill...", missing_reply_text)
        try:
            if settings.RESEND_API_KEY:
                _backfill_reply_text_from_resend(db, settings.RESEND_API_KEY)
        except Exception as bf_err:
            logger.warning("Auto-backfill reply text failed: %s", bf_err)

    # Auto-backfill: check for follow-ups missing body text
    missing_followup_body = db.query(Candidate).filter(
        Candidate.screening_link_sent_at.isnot(None),
        Candidate.screening_email_id.isnot(None),
        (Candidate.followup_body.is_(None)) | (Candidate.followup_body == "")
    ).count()
    if missing_followup_body > 0:
        logger.info("Found %d follow-ups with no body stored, triggering backfill...", missing_followup_body)
        try:
            if settings.RESEND_API_KEY:
                _backfill_followup_body_from_resend(db, settings.RESEND_API_KEY)
        except Exception as bf_err:
            logger.warning("Auto-backfill followup body failed: %s", bf_err)

    # Auto-backfill: check for sent candidates missing sent_outreach snapshot
    missing_sent_snapshot = db.query(Candidate).filter(
        Candidate.warmup_email_sent_at.isnot(None),
        Candidate.warmup_email_id.isnot(None),
        (Candidate.sent_outreach_subject.is_(None)) | (Candidate.sent_outreach_subject == "")
    ).count()
    if missing_sent_snapshot > 0:
        logger.info("Found %d sent candidates with no outreach snapshot, triggering backfill...", missing_sent_snapshot)
        try:
            if settings.RESEND_API_KEY:
                _backfill_sent_outreach_from_resend(db, settings.RESEND_API_KEY)
        except Exception as bf_err:
            logger.warning("Auto-backfill sent_outreach failed: %s", bf_err)

    # Base: all candidates that have been sent outreach (exclude dismissed)
    sent_query = db.query(Candidate).filter(
        Candidate.outreach_status == "sent",
        (Candidate.status != CandidateStatus.rejected) | (Candidate.status.is_(None)),
    )
    total_sent = sent_query.count()

    # Overall funnel (with distributions)
    overall_funnel = _build_funnel(sent_query, include_distributions=True)

    # Get distinct cohort names (most recent first)
    cohort_names = [r[0] for r in db.query(distinct(Candidate.outreach_cohort)).filter(
        Candidate.outreach_status == "sent",
        Candidate.outreach_cohort.isnot(None),
    ).order_by(Candidate.outreach_cohort.desc()).all()]

    # Build per-cohort funnels
    cohorts = []
    for cohort in cohort_names:
        cohort_query = sent_query.filter(Candidate.outreach_cohort == cohort)
        funnel = _build_funnel(cohort_query, include_distributions=True)

        # Get earliest warmup_email_sent_at for this cohort as the "sent_at" timestamp
        earliest_sent = cohort_query.with_entities(
            sa_func.min(Candidate.warmup_email_sent_at)
        ).scalar()

        cohorts.append({
            "cohort": cohort,
            "count": funnel[0]["count"],
            "sent_at": earliest_sent.isoformat() if earliest_sent else None,
            "funnel": funnel,
        })

    # Also count "uncohorted" (sent before cohort tracking existed)
    uncohorted_query = sent_query.filter(Candidate.outreach_cohort.is_(None))
    uncohorted_count = uncohorted_query.count()
    if uncohorted_count > 0:
        earliest_sent = uncohorted_query.with_entities(
            sa_func.min(Candidate.warmup_email_sent_at)
        ).scalar()
        cohorts.append({
            "cohort": "Pre-Cohort",
            "count": uncohorted_count,
            "sent_at": earliest_sent.isoformat() if earliest_sent else None,
            "funnel": _build_funnel(uncohorted_query, include_distributions=True),
        })

    # Bookmarked count (across all outreach statuses)
    bookmarked_count = db.query(Candidate).filter(
        Candidate.outreach_status.isnot(None),
        Candidate.bookmarked == True,
    ).count()

    return {
        "total_sent": total_sent,
        "funnel": overall_funnel,
        "cohorts": cohorts,
        "bookmarked_count": bookmarked_count,
    }


@router.get("/candidates/outreach-queue/filter-options", tags=["outreach"])
def get_outreach_filter_options(
    outreach_status: Optional[str] = "drafted",
    scope: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get distinct tier/archetype/location values among outreach candidates for filter dropdowns.

    Pass scope=all to pull from ALL candidates (used by cohort builder to show all available options).
    """
    from sqlalchemy import distinct

    if scope == "all":
        base = db.query(Candidate)
    else:
        base = db.query(Candidate).filter(Candidate.outreach_status.isnot(None))
        if outreach_status:
            base = base.filter(Candidate.outreach_status == outreach_status)

    tiers = [r[0] for r in base.with_entities(distinct(Candidate.tier)).filter(Candidate.tier.isnot(None)).all()]
    archetypes = [r[0] for r in base.with_entities(distinct(Candidate.archetype)).filter(Candidate.archetype.isnot(None)).all()]

    # Normalize locations to state/country level
    raw_locations = [r[0] for r in base.with_entities(distinct(Candidate.location_country)).filter(
        Candidate.location_country.isnot(None)
    ).all()]
    normalized_set = set()
    for raw in raw_locations:
        norm = _normalize_location(raw)
        if norm:
            normalized_set.add(norm)

    return {
        "tiers": tiers,
        "archetypes": sorted(archetypes),
        "locations": sorted(normalized_set),
    }


@router.get("/candidates/outreach-queue", tags=["outreach"])
def get_outreach_queue(
    outreach_status: Optional[str] = None,
    tier: Optional[str] = None,
    archetype: Optional[str] = None,
    location: Optional[str] = None,
    pipeline_stage: Optional[str] = None,
    cohort_name: Optional[str] = None,
    bookmarked_only: bool = False,
    include_dismissed: bool = False,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Get candidates with drafted/scheduled outreach emails (the review queue).

    Filter by outreach_status: 'drafted', 'scheduled', 'sent', or omit for all with outreach.
    Optional filters: tier, archetype, location (location_country).
    pipeline_stage: Filter sent candidates by pipeline progress:
      'opened', 'replied', 'screening_sent', 'screening_opened', 'answered'
    cohort_name: Filter by outreach cohort. Use 'Pre-Cohort' for candidates with no cohort.
    """
    # ── Auto-dormant sweep: move stale no-reply candidates on each load ──
    from app.models.candidate import OutreachStatus as _OS
    _cutoff = datetime.utcnow() - timedelta(days=3)
    _stale = (
        db.query(Candidate)
        .filter(
            Candidate.outreach_status == _OS.sent,
            Candidate.followup_sent_at.isnot(None),
            Candidate.followup_sent_at <= _cutoff,
            Candidate.warmup_replied_at.is_(None),
            Candidate.dormant != True,
        )
        .all()
    )
    if _stale:
        for _c in _stale:
            _c.status = CandidateStatus.rejected
            _c.dormant = True
            _c.dormant_reason = "auto_no_reply"
        db.commit()
        logger.info("Auto-dormant sweep (inline): moved %d candidate(s)", len(_stale))

    query = db.query(Candidate).filter(Candidate.outreach_status.isnot(None))

    if outreach_status:
        query = query.filter(Candidate.outreach_status == outreach_status)

    # Cohort filter
    if cohort_name:
        if cohort_name == "Pre-Cohort":
            query = query.filter(Candidate.outreach_cohort.is_(None))
        else:
            query = query.filter(Candidate.outreach_cohort == cohort_name)
    # Bookmark filter
    if bookmarked_only:
        query = query.filter(Candidate.bookmarked == True)

    if tier:
        query = query.filter(Candidate.tier == tier)
    if archetype:
        query = query.filter(Candidate.archetype == archetype)
    if location:
        # Location is a normalized value (e.g. "Colorado"), resolve to all matching raw values
        matching_raw = _get_raw_locations_for_normalized(db, location)
        if matching_raw:
            query = query.filter(Candidate.location_country.in_(matching_raw))
        else:
            query = query.filter(Candidate.location_country == location)

    # Exclude dismissed (rejected) candidates unless explicitly requested
    if pipeline_stage == "dismissed":
        # Show ONLY dismissed candidates
        query = query.filter(Candidate.status == CandidateStatus.rejected)
    elif not include_dismissed:
        # Default: hide dismissed candidates
        query = query.filter(
            (Candidate.status != CandidateStatus.rejected) | (Candidate.status.is_(None))
        )

    # Pipeline stage filter (for sent tab)
    if pipeline_stage and pipeline_stage != "dismissed":
        stage_filters = {
            "opened": Candidate.warmup_email_opened_at.isnot(None),
            "replied": Candidate.warmup_replied_at.isnot(None),
            "screening_sent": Candidate.screening_link_sent_at.isnot(None),
            "screening_opened": Candidate.screening_email_opened_at.isnot(None),
            "answered": Candidate.screening_status.in_(["answered", "completed"]),
            "warm": sa_or(
                sa_and(Candidate.screening_status.in_(["answered", "completed"]), Candidate.screening_transcript.isnot(None), Candidate.screening_transcript != ""),
                Candidate.manually_warmed == True,
            ),
            # Legacy filters kept for backwards compatibility
            "link_clicked": Candidate.screening_link_clicked_at.isnot(None),
            "screening_done": Candidate.screening_status.in_(["answered", "completed"]),
        }
        if pipeline_stage in stage_filters:
            query = query.filter(stage_filters[pipeline_stage])

    total = query.count()

    # Sort by reply recency first (inbox-style: new replies always bubble to top),
    # then by latest email activity for non-replied candidates.
    from sqlalchemy import func as sa_func

    # Compute breakdown counts server-side so frontend doesn't need all records
    cold_count = query.filter(Candidate.warmup_email_sent_at.is_(None)).count()
    followup_count = total - cold_count

    # Find earliest scheduled_for across ALL matching candidates (not just current page)
    earliest_scheduled = query.with_entities(
        sa_func.min(Candidate.outreach_scheduled_for)
    ).scalar()
    latest_email_activity = sa_func.greatest(
        Candidate.warmup_email_sent_at,
        Candidate.warmup_email_opened_at,
        Candidate.warmup_replied_at,
        Candidate.followup_sent_at,
        Candidate.screening_email_opened_at,
        Candidate.screening_link_clicked_at,
    )
    candidates = (
        query
        .order_by(
            Candidate.warmup_replied_at.desc().nullslast(),   # Replies first (inbox-style)
            latest_email_activity.desc().nullslast(),          # Then by latest activity
            Candidate.updated_at.desc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    # Batch-load email events for all candidates in one query
    from app.models.email_event import EmailEvent
    candidate_ids = [c.id for c in candidates]
    all_events = (
        db.query(EmailEvent)
        .filter(EmailEvent.candidate_id.in_(candidate_ids))
        .order_by(EmailEvent.candidate_id, EmailEvent.sequence.asc())
        .all()
    ) if candidate_ids else []
    events_by_candidate = {}
    for ev in all_events:
        cid = str(ev.candidate_id)
        if cid not in events_by_candidate:
            events_by_candidate[cid] = []
        events_by_candidate[cid].append({
            "id": str(ev.id),
            "event_type": ev.event_type.value,
            "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
            "subject": ev.subject,
            "body": ev.body,
            "resend_email_id": ev.resend_email_id,
            "metadata": ev.metadata_,
            "sequence": ev.sequence,
        })

    return {
        "total": total,
        "cold_count": cold_count,
        "followup_count": followup_count,
        "earliest_scheduled": earliest_scheduled.isoformat() + "Z" if earliest_scheduled else None,
        "candidates": [
            {
                "id": str(c.id),
                "name": c.name,
                "email": c.email,
                "github_username": c.github_username,
                "archetype": c.archetype,
                "tier": c.tier,
                "location_country": c.location_country,
                "outreach_status": c.outreach_status.value if c.outreach_status else None,
                "outreach_subject": c.outreach_subject,
                "outreach_body": c.outreach_body,
                "sent_outreach_subject": c.sent_outreach_subject,
                "sent_outreach_body": c.sent_outreach_body,
                "outreach_scheduled_for": (c.outreach_scheduled_for.isoformat() + "Z") if c.outreach_scheduled_for else None,
                "warmup_email_sent_at": (c.warmup_email_sent_at.isoformat() + "Z") if c.warmup_email_sent_at else None,
                "warmup_email_opened_at": (c.warmup_email_opened_at.isoformat() + "Z") if c.warmup_email_opened_at else None,
                "warmup_replied_at": c.warmup_replied_at.isoformat() if c.warmup_replied_at else None,
                "warmup_reply_text": c.warmup_reply_text,
                "screening_email_opened_at": c.screening_email_opened_at.isoformat() if c.screening_email_opened_at else None,
                "screening_link_sent_at": c.screening_link_sent_at.isoformat() if c.screening_link_sent_at else None,
                "screening_status": c.screening_status,
                "screening_transcript": c.screening_transcript,
                "screening_data": c.screening_data,
                "screening_summary": c.screening_summary,
                "screening_completed_at": c.screening_completed_at.isoformat() if c.screening_completed_at else None,
                "followup_body": c.followup_body,
                "followup_sent_at": c.followup_sent_at.isoformat() if c.followup_sent_at else None,
                "screening_body": c.screening_body,
                "status": c.status.value if c.status else None,
                "outreach_cohort": c.outreach_cohort,
                "outreach_type": c.outreach_type,
                "outreach_role_title": c.outreach_role_title,
                "bookmarked": bool(c.bookmarked),
                "behavior_tier": c.behavior_tier,
                "manually_warmed": bool(c.manually_warmed),
                "star_count": c.star_count or 0,
                "email_events": events_by_candidate.get(str(c.id), []),
            }
            for c in candidates
        ],
    }


# ─── Starred Candidates ──────────────────────────────────────────────
@router.get("/candidates/starred", tags=["candidates", "starred"])
def list_starred_candidates(db: Session = Depends(get_db)):
    """Return all candidates with star_count > 0 together with their starred matches and roles."""
    from app.models.fit_analysis import FitAnalysis

    candidates = (
        db.query(Candidate)
        .filter(Candidate.star_count > 0, Candidate.dormant != True)
        .order_by(Candidate.star_count.desc())
        .all()
    )

    results = []
    for c in candidates:
        # Get all starred matches for this candidate
        starred_matches = (
            db.query(Match)
            .filter(Match.candidate_id == c.id, Match.starred == True)
            .all()
        )

        matches_data = []
        for m in starred_matches:
            role = crud.get_role(db, m.role_id)
            # Get fit analysis if exists
            fit = db.query(FitAnalysis).filter(FitAnalysis.match_id == m.id).first()

            matches_data.append({
                "match_id": str(m.id),
                "role_id": str(m.role_id),
                "role_title": role.title if role else None,
                "company_name": role.company_name if role else None,
                "match_score": m.match_score,
                "fit_score": fit.fit_score if fit else None,
                "recommendation": fit.recommendation if fit else None,
                "ai_summary_short": fit.ai_summary_short if fit else None,
                "starred_at": str(m.created_at) if m.created_at else None,
            })

        # Get ALL fit analyses for this candidate (across all roles, not just starred)
        all_analyses = (
            db.query(FitAnalysis)
            .filter(FitAnalysis.candidate_id == c.id, FitAnalysis.fit_score.isnot(None))
            .all()
        )
        crosschekk_results = {}
        for fa in all_analyses:
            role = crud.get_role(db, fa.role_id)
            if not role:
                continue
            # Find the match to check starred status
            match = db.query(Match).filter(Match.id == fa.match_id).first() if fa.match_id else None
            role_id_str = str(fa.role_id)
            crosschekk_results[role_id_str] = {
                "match_id": str(fa.match_id) if fa.match_id else "",
                "role_id": role_id_str,
                "role_title": role.title,
                "company_name": role.company_name,
                "fit_score": fa.fit_score,
                "recommendation": fa.recommendation or "SKIP",
                "ai_summary_short": fa.ai_summary_short or "",
                "ai_summary": fa.ai_summary or "",
                "skills_matched": fa.skills_matched or [],
                "skills_missing": fa.skills_missing or [],
                "starred": match.starred if match else False,
                "status": "done",
                # Outreach drafts saved on match record
                "draft_subject": match.draft_subject if match else None,
                "draft_body": match.draft_body if match else None,
            }

        results.append({
            "id": str(c.id),
            "name": c.name,
            "email": c.email,
            "github_username": c.github_username,
            "linkedin_url": c.linkedin_url,
            "archetype": c.archetype,
            "tier": c.tier,
            "tier_badge": c.tier_badge,
            "yoe": c.yoe,
            "current_role": c.current_role,
            "current_company": c.current_company,
            "location": c.location_raw,
            "tech_stack": c.tech_stack,
            "star_count": c.star_count,
            "linkedin_text": c.linkedin_text,
            "starred_matches": matches_data,
            "crosschekk_results": crosschekk_results,
            # Outreach history
            "outreach_status": c.outreach_status.value if c.outreach_status else None,
            "outreach_scheduled_for": (c.outreach_scheduled_for.isoformat() + "Z") if c.outreach_scheduled_for else None,
            "outreach_subject": c.outreach_subject,
            "outreach_body": c.outreach_body,
            "warmup_email_sent_at": (c.warmup_email_sent_at.isoformat() + "Z") if c.warmup_email_sent_at else None,
            "warmup_email_opened_at": (c.warmup_email_opened_at.isoformat() + "Z") if c.warmup_email_opened_at else None,
            "warmup_replied_at": (c.warmup_replied_at.isoformat() + "Z") if c.warmup_replied_at else None,
            "warmup_reply_text": c.warmup_reply_text,
            "followup_sent_at": (c.followup_sent_at.isoformat() + "Z") if c.followup_sent_at else None,
            "sent_outreach_subject": c.sent_outreach_subject,
            "sent_outreach_body": c.sent_outreach_body,
        })

    return {"count": len(results), "candidates": results}


@router.get("/candidates/pending-replies", tags=["candidates", "outreach"])
def get_pending_replies(
    db: Session = Depends(get_db),
):
    """Get all candidates with pending replies — either AI-drafted or unread."""
    from app.models.email_event import EmailEvent as _EE
    from app.services.email_events import get_email_chain

    candidates = db.query(Candidate).filter(
        sa_or(
            Candidate.screening_status.in_(["pending_approval", "pending_approval_decline"]),
            Candidate.has_unread_reply == True,
        )
    ).order_by(Candidate.warmup_replied_at.desc()).all()

    results = []
    for c in candidates:
        # For unread replies without an AI draft, get the latest reply from email_events
        reply_text = c.warmup_reply_text
        replied_at = c.warmup_replied_at
        if c.has_unread_reply and c.screening_status not in ("pending_approval", "pending_approval_decline"):
            latest_reply = db.query(_EE).filter(
                _EE.candidate_id == c.id,
                _EE.event_type.in_(["candidate_replied", "screening_answered"]),
            ).order_by(_EE.occurred_at.desc()).first()
            if latest_reply:
                reply_text = latest_reply.body or reply_text
                replied_at = latest_reply.occurred_at or replied_at

        # Fetch full email chain for this candidate
        email_chain = get_email_chain(db, c.id)

        results.append({
            "id": str(c.id),
            "name": c.name,
            "email": c.email,
            "github_username": c.github_username,
            "reply_text": reply_text,
            "draft_body": c.screening_body,
            "replied_at": replied_at,
            "screening_status": c.screening_status,
            "has_unread_reply": c.has_unread_reply or False,
            "outreach_subject": c.sent_outreach_subject or c.outreach_subject,
            "outreach_body": c.sent_outreach_body or c.outreach_body,
            "outreach_cohort": c.outreach_cohort,
            "bookmarked": bool(c.bookmarked),
            "manually_warmed": bool(c.manually_warmed),
            "email_chain": email_chain,
        })

    return {"count": len(results), "candidates": results}


@router.get("/candidates/{candidate_id}", response_model=CandidateInDB, tags=["candidates"])
def get_candidate(candidate_id: UUID, db: Session = Depends(get_db)):
    """Get a specific candidate by ID"""
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.put("/candidates/{candidate_id}", response_model=CandidateInDB, tags=["candidates"])
def update_candidate(
    candidate_id: UUID, candidate: CandidateUpdate, db: Session = Depends(get_db)
):
    """Update a candidate"""
    updated_candidate = crud.update_candidate(db, candidate_id, candidate)
    if not updated_candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return updated_candidate


@router.delete("/candidates/{candidate_id}", tags=["candidates"])
def delete_candidate(candidate_id: UUID, db: Session = Depends(get_db)):
    """Delete a candidate"""
    success = crud.delete_candidate(db, candidate_id)
    if not success:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return {"message": "Candidate deleted successfully"}


@router.post("/candidates/{candidate_id}/analyze", tags=["candidates", "analysis"])
def analyze_candidate(candidate_id: UUID, db: Session = Depends(get_db)):
    """
    Run DeepSeek analysis on a candidate to generate VibeReport.

    This classifies the candidate into an archetype and tier,
    then generates a recruiter-ready assessment.
    """
    try:
        return run_candidate_analysis(candidate_id, db)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )


@router.post("/candidates/bulk-analyze-async", tags=["candidates", "analysis"])
def bulk_analyze_candidates_async(
    status: Optional[str] = None,
    archetype_filter: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Bulk analyze candidates asynchronously with parallel processing and progress tracking.

    Returns immediately with job ID. Poll /api/v1/bulk-jobs/{job_id} for progress.
    """
    from app.models import Candidate
    from app.models.ingestion_job import IngestionJob, JobStatus
    from app.services.parallel_analyzer import analyze_batch_parallel
    import threading

    # Build query with filters
    query = db.query(Candidate)

    if status:
        query = query.filter(Candidate.status == status)

    # Filter for unanalyzed candidates (no archetype)
    if archetype_filter == "unanalyzed":
        query = query.filter(Candidate.archetype.is_(None))
    elif archetype_filter == "analyzed":
        query = query.filter(Candidate.archetype.isnot(None))

    # Get all matching candidates
    candidates = query.all()
    candidate_ids = [str(c.id) for c in candidates]
    total_count = len(candidate_ids)

    if total_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No candidates match the specified filters"
        )

    # PRE-FLIGHT: Verify tokens are configured (trust local bucket algorithm for capacity)
    from app.services.github_ingestion import token_rotator

    if len(token_rotator.tokens) == 0:
        raise HTTPException(
            status_code=500,
            detail="No GitHub API tokens configured. Please add tokens to environment variables."
        )

    logger.debug("%d token(s) configured - trusting local bucket refills (1.39 req/sec per token)", len(token_rotator.tokens))

    # Create job record
    job = IngestionJob(
        status=JobStatus.running,
        job_type='bulk_analyze',
        total_candidates=total_count,
        processed_count=0,
        candidates_saved=0,
        candidates_skipped=0,
        error_count=0,
        recent_logs=[]
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info("Created bulk analyze job %s for %d candidates", job.id, total_count)

    # Start background processing
    def process_in_background():
        from app.db.base import SessionLocal
        from app.models.ingestion_job import IngestionJob

        bg_db = SessionLocal()

        try:
            # Reload job in background session (job was created in request session)
            bg_job = bg_db.query(IngestionJob).filter(IngestionJob.id == job.id).first()

            stats = {
                'analyzed': 0,
                'errors': 0,
                'rare': 0,
                'epic': 0,
                'legendary': 0
            }

            # Process with parallel workers
            analyze_batch_parallel(
                db=bg_db,
                job=bg_job,
                candidate_ids=candidate_ids,
                stats=stats,
                max_workers=12
            )

            # Mark job as complete
            bg_db.refresh(bg_job)
            if bg_job.status != JobStatus.stopped:
                bg_job.status = JobStatus.completed
                bg_job.candidates_saved = stats['analyzed']
                bg_job.updated_at = datetime.utcnow()
                bg_db.commit()

            logger.info("Job %s completed: %d analyzed, %d errors", bg_job.id, stats['analyzed'], stats['errors'])

        except Exception as e:
            logger.error("Job %s failed: %s", bg_job.id, e)
            bg_job.status = JobStatus.failed
            bg_job.error_message = str(e)
            bg_db.commit()
        finally:
            bg_db.close()

    # Start thread
    thread = threading.Thread(target=process_in_background, daemon=True)
    thread.start()

    return {
        "message": "Bulk analysis started in background",
        "job_id": str(job.id),
        "total_count": total_count,
        "status": "running"
    }


@router.post("/candidates/bulk-analyze", tags=["candidates", "analysis"])
def bulk_analyze_candidates(
    status: Optional[str] = None,
    archetype_filter: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Bulk analyze candidates matching filters (e.g., all unanalyzed candidates).

    This processes candidates server-side to avoid pagination limits.
    DEPRECATED: Use /bulk-analyze-async for better progress tracking.
    """
    from app.models import Candidate

    # Build query with filters
    query = db.query(Candidate)

    if status:
        query = query.filter(Candidate.status == status)

    # Filter for unanalyzed candidates (no archetype)
    if archetype_filter == "unanalyzed":
        query = query.filter(Candidate.archetype.is_(None))
    elif archetype_filter == "analyzed":
        query = query.filter(Candidate.archetype.isnot(None))

    # Get all matching candidates
    candidates = query.all()
    total_count = len(candidates)

    if total_count == 0:
        return {
            "message": "No candidates match the specified filters",
            "total": 0,
            "processed": 0,
            "failed": 0
        }

    # Process candidates (limit to prevent overwhelming the system)
    MAX_BULK_ANALYZE = 100
    candidates_to_process = candidates[:MAX_BULK_ANALYZE]

    processed = 0
    failed = 0
    errors = []

    for candidate in candidates_to_process:
        try:
            run_candidate_analysis(candidate.id, db)
            processed += 1
        except Exception as e:
            failed += 1
            errors.append({
                "candidate_id": str(candidate.id),
                "candidate_name": candidate.name or candidate.github_username,
                "error": str(e)
            })
            logger.error("Failed to analyze %s: %s", candidate.name or candidate.github_username, e)

    return {
        "message": f"Bulk analysis complete: {processed} succeeded, {failed} failed",
        "total_matching": total_count,
        "processed": processed,
        "failed": failed,
        "limit_applied": total_count > MAX_BULK_ANALYZE,
        "errors": errors[:10] if errors else []  # Return first 10 errors
    }


@router.post("/candidates/{candidate_id}/upload-resume", tags=["candidates"])
def upload_resume_text(
    candidate_id: UUID,
    resume_text: str,
    db: Session = Depends(get_db)
):
    """
    Upload resume text for a candidate and automatically re-run analysis.

    This resume data will be used during VibeChekk analysis to provide
    additional context about the candidate's experience and skills.
    After uploading, the analysis is automatically re-run with the new context.
    """
    from app.schemas.candidate import CandidateUpdate

    # Validate resume text length (max 1MB of text)
    MAX_TEXT_LENGTH = 1 * 1024 * 1024  # 1MB
    if len(resume_text) > MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Resume text too large. Maximum size is 1MB."
        )

    # Get candidate
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Parse structured fields from resume
    from app.services.resume_parser import parse_resume_fields
    parsed_fields = parse_resume_fields(resume_text)

    # Update resume text and parsed fields
    update_dict = {"resume_text": resume_text}
    if parsed_fields.get('yoe') is not None:
        update_dict['yoe'] = parsed_fields['yoe']
    if parsed_fields.get('current_company'):
        update_dict['current_company'] = parsed_fields['current_company']
    if parsed_fields.get('current_role'):
        update_dict['current_role'] = parsed_fields['current_role']

    update_data = CandidateUpdate(**update_dict)
    updated_candidate = crud.update_candidate(db, candidate_id, update_data)

    # Automatically re-run analysis with the resume context
    try:
        analysis_result = run_candidate_analysis(candidate_id, db)
        return {
            "message": "Resume uploaded and analysis complete",
            "candidate_id": candidate_id,
            "resume_length": len(resume_text),
            "analysis": analysis_result
        }
    except Exception as e:
        # If analysis fails, still return success for resume upload
        logger.error("Analysis failed after resume upload: %s", str(e))
        return {
            "message": "Resume uploaded successfully, but analysis failed",
            "candidate_id": candidate_id,
            "resume_length": len(resume_text),
            "analysis_error": str(e)
        }


@router.post("/candidates/{candidate_id}/upload-resume-pdf", tags=["candidates"])
async def upload_resume_pdf(
    candidate_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a PDF resume for a candidate and automatically re-run analysis.

    The PDF will be parsed to extract text, which will be used during
    VibeChekk analysis to provide additional context about the candidate's
    experience, projects, education, and skills.
    After uploading, the analysis is automatically re-run with the new context.
    """
    from app.schemas.candidate import CandidateUpdate
    from PyPDF2 import PdfReader

    # Validate file type
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF files are accepted."
        )

    # Validate file size (max 10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB in bytes
    file_content = await file.read()
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is 10MB."
        )
    await file.seek(0)  # Reset file pointer for reading again

    # Get candidate
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    try:
        # Read PDF file
        contents = await file.read()
        pdf_file = io.BytesIO(contents)

        # Extract text from PDF
        pdf_reader = PdfReader(pdf_file)
        resume_text = ""

        for page in pdf_reader.pages:
            text = page.extract_text()
            if text:
                resume_text += text + "\n"

        if not resume_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from PDF. The file may be empty or contain only images."
            )

        # Parse structured fields from resume
        from app.services.resume_parser import parse_resume_fields
        parsed_fields = parse_resume_fields(resume_text.strip())

        # Update resume text and parsed fields
        update_dict = {"resume_text": resume_text.strip()}
        if parsed_fields.get('yoe') is not None:
            update_dict['yoe'] = parsed_fields['yoe']
        if parsed_fields.get('current_company'):
            update_dict['current_company'] = parsed_fields['current_company']
        if parsed_fields.get('current_role'):
            update_dict['current_role'] = parsed_fields['current_role']

        update_data = CandidateUpdate(**update_dict)
        updated_candidate = crud.update_candidate(db, candidate_id, update_data)

        # Store raw PDF bytes so the resume is viewable in the profile
        candidate.resume_pdf = file_content
        db.commit()

        # Automatically re-run analysis with the resume context
        try:
            analysis_result = run_candidate_analysis(candidate_id, db)
            return {
                "message": "Resume PDF uploaded, parsed, and analysis complete",
                "candidate_id": candidate_id,
                "resume_length": len(resume_text.strip()),
                "pages_processed": len(pdf_reader.pages),
                "analysis": analysis_result
            }
        except Exception as analysis_error:
            # If analysis fails, still return success for PDF upload
            logger.error("Analysis failed after PDF upload: %s", str(analysis_error))
            return {
                "message": "Resume PDF uploaded and parsed successfully, but analysis failed",
                "candidate_id": candidate_id,
                "resume_length": len(resume_text.strip()),
                "pages_processed": len(pdf_reader.pages),
                "analysis_error": str(analysis_error)
            }

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process PDF: {str(e)}"
        )


# Role Routes
@router.post("/roles/", response_model=RoleInDB, tags=["roles"])
def create_role(role: RoleCreate, db: Session = Depends(get_db)):
    """
    Create a new role with auto-parsing from job description.

    If jd_text is provided, we'll automatically extract:
    - Tech stack (Python, React, PostgreSQL, etc.)
    - Location requirement (remote/hybrid/onsite)
    - Compensation range (salary and equity)
    """
    from app.services.role_sourcing import parse_tech_stack, parse_location_requirement, parse_compensation
    from app.models.role import LocationRequirement

    logger.debug("Received role data: %s", role.model_dump())

    # Convert to dict for modification
    role_data = role.model_dump()

    # Auto-parse from jd_text if provided
    if role_data.get('jd_text'):
        # Parse tech stack if not manually provided
        if not role_data.get('tech_stack') or len(role_data.get('tech_stack', [])) == 0:
            parsed_tech = parse_tech_stack(role_data['jd_text'])
            if parsed_tech:
                role_data['tech_stack'] = parsed_tech

        # Parse location requirement if not manually provided
        if not role_data.get('location_requirement'):
            parsed_location = parse_location_requirement(role_data['jd_text'])
            if parsed_location:
                try:
                    # Convert string to enum
                    role_data['location_requirement'] = LocationRequirement(parsed_location)
                except ValueError:
                    pass  # Invalid value, skip

        # Parse compensation if not manually provided
        if not role_data.get('comp_min') and not role_data.get('equity_min'):
            parsed_comp = parse_compensation(role_data['jd_text'])
            if parsed_comp['comp_min']:
                role_data['comp_min'] = parsed_comp['comp_min']
                role_data['comp_max'] = parsed_comp['comp_max']
            if parsed_comp['equity_min']:
                role_data['equity_min'] = parsed_comp['equity_min']
                role_data['equity_max'] = parsed_comp['equity_max']

    # Recreate the Pydantic model with updated data
    updated_role = RoleCreate(**role_data)
    return crud.create_role(db, updated_role)


@router.post("/roles/parse-raw", tags=["roles"])
def parse_raw_roles(
    raw_text: str,
    db: Session = Depends(get_db)
):
    """
    Parse raw text (LinkedIn posts, bulk job dumps) into structured role data.

    Uses DeepSeek to intelligently extract:
    - Multiple job postings from one paste (separated by --- or context)
    - Company name, job title, description
    - URLs, source indicators, referral bonuses
    - Tech stack, location, compensation

    Returns parsed roles with duplicate detection warnings.
    """
    from app.core.config import settings
    import requests
    import json
    from difflib import SequenceMatcher

    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="DeepSeek API key not configured"
        )

    # DeepSeek prompt for parsing raw text
    prompt = f"""Parse the following raw text into structured job role data. The text may contain multiple job postings separated by "---" or blank lines.

For each job posting found, extract ALL of these fields:
- company_name (required)
- title (required - the job title)
- jd_text (the FULL original job description text - include EVERYTHING. Do NOT summarize)
- jd_url (any URLs found)
- source (where it came from - LinkedIn, job board, etc. Look for "SOURCE" markers)
- placement_fee (any referral bonus mentioned like "$10k referral bonus")
- notable_investors (array of investor/VC names mentioned, e.g. ["CRV", "a16z", "Y Combinator"]. Look for "backed by", "investors include", "led by", funding round mentions, and accelerator names like "YC S25")
- location_requirement (one of: "remote", "hybrid", "onsite" - detect from the text. If it mentions multiple cities, it's likely "hybrid" or "onsite". If it says "remote" anywhere, use "remote")
- location_cities (array of city names mentioned, e.g. ["San Francisco, CA", "Belgrade, Serbia"]. Look for "Location" fields, city names, office locations)
- tech_stack (array of ALL specific technologies, frameworks, languages, and tools mentioned ANYWHERE in the posting - including the "Tech Stack" section, requirements, qualifications, and "nice to have"/"optional" sections. e.g. ["TypeScript", "Svelte", "Golang", "WebGL", "GCP", "C++", "Rust"]. Include languages from optional/preferred requirements too)
- required_skills (array of key skills/requirements from the "What we're looking for" or "Requirements" sections. Each item should be a concise skill description, e.g. ["Computer graphics / real-time rendering", "Experience with Fabric.js, Konva.js, Pixi.js or similar", "Math and geometry for graphics"])
- required_skills_priority (object mapping EACH tech_stack item to "must_have" or "nice_to_have". Skills from "Requirements"/"Must have"/"Qualifications" sections = "must_have". Skills from "Nice to have"/"Bonus"/"Preferred" sections = "nice_to_have". If unclear, default to "must_have". e.g. {{"Python": "must_have", "PyTorch": "must_have", "MLOps": "nice_to_have"}})
- comp_min (minimum compensation as integer, if mentioned, e.g. 150000)
- comp_max (maximum compensation as integer, if mentioned, e.g. 200000)
- company_stage (one of: "pre_seed", "seed", "series_a", "series_b", "growth" - infer from context like "YC S25", funding info, etc.)
- notes (any other relevant info)

Return a JSON object with this structure:
{{
  "roles": [
    {{
      "company_name": "Company Name",
      "title": "Job Title",
      "jd_text": "The full original job description text...",
      "jd_url": "https://...",
      "source": "LinkedIn",
      "placement_fee": "$10k referral bonus",
      "notable_investors": ["CRV", "XYZ Ventures"],
      "location_requirement": "hybrid",
      "location_cities": ["San Francisco, CA"],
      "tech_stack": ["TypeScript", "React"],
      "required_skills": ["3+ years frontend experience", "Real-time rendering"],
      "required_skills_priority": {{"TypeScript": "must_have", "React": "must_have"}},
      "comp_min": 150000,
      "comp_max": 200000,
      "company_stage": "seed",
      "notes": "Additional context..."
    }}
  ]
}}

Rules:
- If multiple jobs are found (separated by --- or clear context breaks), return multiple role objects
- Extract the EXACT company name mentioned
- Extract the EXACT job title mentioned
- IMPORTANT: For jd_text, include the FULL original job description text. Do NOT summarize or shorten. Preserve the complete content.
- For notable_investors, extract ALL investor names, VC firms, and accelerators mentioned (e.g. "CRV", "a16z", "Y Combinator", "Sequoia"). Also extract notable angel investors if named (e.g. "founders of MongoDB & KAYAK")
- CAREFULLY look for location information - it may appear as "Location: ..." at the top, in a sidebar, or mentioned in requirements. Extract ALL cities/locations
- For tech_stack, extract specific technologies (languages, frameworks, tools, cloud platforms) from ALL sections - NOT general skills. Include technologies from "nice to have", "optional", "preferred" sections too (e.g. if "C++, Rust" appear in optional requirements, STILL add them to tech_stack)
- For required_skills, extract the key requirements/qualifications - summarize each as a concise bullet point
- For placement_fee, extract referral bonus amounts like "$10k referral bonus"
- If SOURCE or JD markers are present, use them to determine the source field
- If no clear separation, treat as single job posting
- Omit fields that cannot be determined (don't guess)

Raw text to parse:

{raw_text}
"""

    try:
        # Call DeepSeek API
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a job posting parser. Extract structured data from raw text accurately."
                    },
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": 8192
            },
            timeout=180
        )

        if not response.ok:
            logger.error("DeepSeek Parse API error: %d - %s", response.status_code, response.text)
            raise HTTPException(
                status_code=500,
                detail=f"DeepSeek API error: {response.status_code}"
            )

        data = response.json()
        raw_content = data['choices'][0]['message']['content']
        parsed_data = json.loads(raw_content)

        roles = parsed_data.get('roles', [])

        if not roles:
            raise HTTPException(
                status_code=400,
                detail="No job postings found in the provided text"
            )

        # Duplicate detection
        # 1. Check for duplicates within parsed roles
        # 2. Check against existing roles in database

        def similarity_ratio(a: str, b: str) -> float:
            """Calculate similarity between two strings (0.0 to 1.0)"""
            return SequenceMatcher(None, a.lower(), b.lower()).ratio()

        # Get all existing roles from database
        existing_roles = db.query(Role).all()

        # Add duplicate detection to each parsed role
        for i, role in enumerate(roles):
            role['is_duplicate'] = False
            role['duplicate_reason'] = None
            role['duplicate_warnings'] = []

            # Check against other parsed roles (within this parse)
            for j, other_role in enumerate(roles):
                if i != j:
                    same_company = role.get('company_name', '').lower() == other_role.get('company_name', '').lower()
                    title_similarity = similarity_ratio(
                        role.get('title', ''),
                        other_role.get('title', '')
                    )

                    if same_company and title_similarity > 0.8:
                        role['duplicate_warnings'].append(
                            f"⚠️ Duplicate within parse: Similar to role #{j+1} in this batch"
                        )

            # Check against existing database roles
            company_name = role.get('company_name', '')
            title = role.get('title', '')

            for existing_role in existing_roles:
                same_company = existing_role.company_name.lower() == company_name.lower()
                title_similarity = similarity_ratio(title, existing_role.title)

                if same_company and title_similarity > 0.8:
                    role['is_duplicate'] = True
                    role['duplicate_reason'] = f"Similar role exists: {existing_role.title} at {existing_role.company_name} (created {existing_role.created_at.strftime('%Y-%m-%d')})"
                    role['duplicate_warnings'].append(
                        f"🔴 Database duplicate: {existing_role.title} at {existing_role.company_name} (created {existing_role.created_at.strftime('%Y-%m-%d')})"
                    )
                    break

        return {
            "success": True,
            "count": len(roles),
            "roles": roles
        }

    except json.JSONDecodeError as e:
        logger.error("DeepSeek Parse JSON decode error: %s", e)
        logger.error("DeepSeek Parse raw response: %s", raw_content)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse DeepSeek response: {str(e)}"
        )
    except Exception as e:
        logger.error("DeepSeek Parse error: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse roles: {str(e)}"
        )


# ── Async ingest job store ──────────────────────────────────────────
# In-memory dict: job_id -> { status, raw_pastes, results, error, created_at }
# Survives across frontend navigations/refreshes; cleared on server restart (acceptable).
_ingest_jobs: dict = {}


def _build_ingest_prompt(raw_text: str) -> str:
    """Build the DeepSeek prompt for parsing JD text."""
    return f"""Parse the following raw text into structured job role data. The text may contain multiple job postings separated by "---" or blank lines.

For each job posting found, extract ALL of these fields:
- company_name (required)
- title (required - the job title)
- jd_text (the FULL original job description text - include EVERYTHING. Do NOT summarize)
- jd_url (any URLs found)
- source (where it came from - LinkedIn, job board, etc. Look for "SOURCE" markers)
- placement_fee (any referral bonus mentioned like "$10k referral bonus")
- notable_investors (array of investor/VC names mentioned, e.g. ["CRV", "a16z", "Y Combinator"]. Look for "backed by", "investors include", "led by", funding round mentions, and accelerator names like "YC S25")
- location_requirement (one of: "remote", "hybrid", "onsite" - detect from the text. If it mentions multiple cities, it's likely "hybrid" or "onsite". If it says "remote" anywhere, use "remote")
- location_cities (array of city names mentioned, e.g. ["San Francisco, CA", "Belgrade, Serbia"]. Look for "Location" fields, city names, office locations)
- tech_stack (array of ALL specific technologies, frameworks, languages, and tools mentioned ANYWHERE in the posting - including the "Tech Stack" section, requirements, qualifications, and "nice to have"/"optional" sections. e.g. ["TypeScript", "Svelte", "Golang", "WebGL", "GCP", "C++", "Rust"]. Include languages from optional/preferred requirements too)
- required_skills (array of key skills/requirements from the "What we're looking for" or "Requirements" sections. Each item should be a concise skill description, e.g. ["Computer graphics / real-time rendering", "Experience with Fabric.js, Konva.js, Pixi.js or similar", "Math and geometry for graphics"])
- required_skills_priority (object mapping EACH tech_stack item to "must_have" or "nice_to_have". Skills from "Requirements"/"Must have"/"Qualifications" sections = "must_have". Skills from "Nice to have"/"Bonus"/"Preferred" sections = "nice_to_have". If unclear, default to "must_have". e.g. {{"Python": "must_have", "PyTorch": "must_have", "MLOps": "nice_to_have"}})
- comp_min (minimum compensation as integer, if mentioned, e.g. 150000)
- comp_max (maximum compensation as integer, if mentioned, e.g. 200000)
- company_stage (one of: "pre_seed", "seed", "series_a", "series_b", "growth" - infer from context like "YC S25", funding info, etc.)
- notes (any other relevant info)

Return a JSON object with this structure:
{{
  "roles": [
    {{
      "company_name": "Company Name",
      "title": "Job Title",
      "jd_text": "The full original job description text...",
      "jd_url": "https://...",
      "source": "LinkedIn",
      "placement_fee": "$10k referral bonus",
      "notable_investors": ["CRV", "XYZ Ventures"],
      "location_requirement": "hybrid",
      "location_cities": ["San Francisco, CA"],
      "tech_stack": ["TypeScript", "React"],
      "required_skills": ["3+ years frontend experience", "Real-time rendering"],
      "required_skills_priority": {{"TypeScript": "must_have", "React": "must_have"}},
      "comp_min": 150000,
      "comp_max": 200000,
      "company_stage": "seed",
      "notes": "Additional context..."
    }}
  ]
}}

Rules:
- If multiple jobs are found (separated by --- or clear context breaks), return multiple role objects
- Extract the EXACT company name mentioned
- Extract the EXACT job title mentioned
- IMPORTANT: For jd_text, include the FULL original job description text. Do NOT summarize or shorten. Preserve the complete content.
- For notable_investors, extract ALL investor names, VC firms, and accelerators mentioned (e.g. "CRV", "a16z", "Y Combinator", "Sequoia"). Also extract notable angel investors if named (e.g. "founders of MongoDB & KAYAK")
- CAREFULLY look for location information - it may appear as "Location: ..." at the top, in a sidebar, or mentioned in requirements. Extract ALL cities/locations
- For tech_stack, extract specific technologies (languages, frameworks, tools, cloud platforms) from ALL sections - NOT general skills. Include technologies from "nice to have", "optional", "preferred" sections too (e.g. if "C++, Rust" appear in optional requirements, STILL add them to tech_stack)
- For required_skills, extract the key requirements/qualifications - summarize each as a concise bullet point
- For placement_fee, extract referral bonus amounts like "$10k referral bonus"
- If SOURCE or JD markers are present, use them to determine the source field
- If no clear separation, treat as single job posting
- Omit fields that cannot be determined (don't guess)

Raw text to parse:

{raw_text}
"""


def _parse_chunk(chunk_text: str, settings, chunk_label: str = "") -> list:
    """Parse a chunk of JD text via DeepSeek. Returns list of role dicts or raises."""
    import requests
    import json

    prompt = _build_ingest_prompt(chunk_text)

    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a job posting parser. Extract structured data from raw text accurately. Include the FULL original job description in jd_text."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 8192
        },
        timeout=180
    )

    if not response.ok:
        error_body = ""
        try:
            error_body = response.text[:500]
        except Exception:
            pass
        logger.error("DeepSeek API error %s: %s", response.status_code, error_body)
        raise Exception(f"DeepSeek API error {response.status_code}: {error_body}")

    data = response.json()
    raw_content = data['choices'][0]['message']['content']
    finish_reason = data['choices'][0].get('finish_reason', '')

    # Try to fix truncated JSON by closing open structures
    try:
        parsed_data = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed for %s (finish_reason=%s), attempting repair...", chunk_label, finish_reason)
        repaired = raw_content.rstrip()

        # Strategy 1: If truncated inside jd_text (the longest field), cut jd_text short
        # Find the last well-formed field boundary before truncation
        # Look for pattern: truncated inside a string value for jd_text
        import re

        # Try progressively more aggressive repairs
        parsed_data = None
        for attempt in range(3):
            try:
                if attempt == 0:
                    # Attempt 0: just close unclosed strings and brackets
                    fix = repaired
                    if fix.count('"') % 2 == 1:
                        fix = fix + '"'
                    open_braces = fix.count('{') - fix.count('}')
                    open_brackets = fix.count('[') - fix.count(']')
                    fix += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
                    parsed_data = json.loads(fix)
                elif attempt == 1:
                    # Attempt 1: find the last complete key-value pair and truncate there
                    # Look for the last `", "key":` or `", "key":` pattern
                    last_field = -1
                    for m in re.finditer(r',\s*"[a-z_]+":\s*', repaired):
                        last_field = m.start()
                    if last_field > 0:
                        fix = repaired[:last_field]
                        # Close open structures
                        open_braces = fix.count('{') - fix.count('}')
                        open_brackets = fix.count('[') - fix.count(']')
                        fix += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
                        parsed_data = json.loads(fix)
                elif attempt == 2:
                    # Attempt 2: find the last complete role object and truncate
                    last_obj_end = repaired.rfind('},')
                    if last_obj_end > 0:
                        fix = repaired[:last_obj_end + 1] + ']}'
                        parsed_data = json.loads(fix)
                if parsed_data is not None:
                    logger.info("JSON repair succeeded for %s on attempt %d", chunk_label, attempt)
                    break
            except json.JSONDecodeError:
                parsed_data = None
                continue

        if parsed_data is None:
            raise Exception(f"JSON parse failed even after repair attempts")

    roles = parsed_data.get('roles', [])

    # If jd_text looks truncated (much shorter than the input), substitute raw text
    if len(roles) == 1 and chunk_text:
        jd = roles[0].get('jd_text', '')
        # If the parsed jd_text is less than 50% of the raw input, it was likely truncated
        if jd and len(jd) < len(chunk_text) * 0.5:
            logger.info("jd_text appears truncated (%d vs %d chars), substituting raw text for %s",
                        len(jd), len(chunk_text), chunk_label)
            roles[0]['jd_text'] = chunk_text.strip()

    return roles


def _run_ingest_job(job_id: str, raw_text: str):
    """Background worker: parse raw text via DeepSeek, run dupe detection, store results.

    For large batches (4+ JDs), splits into chunks of 3 to avoid response truncation.
    """
    import json
    import uuid as _uuid
    from datetime import datetime
    from difflib import SequenceMatcher
    from app.core.config import settings
    from app.db.base import SessionLocal

    job = _ingest_jobs.get(job_id)
    if not job:
        return

    try:
        # Split raw text into individual JDs by --- separator
        jd_segments = [s.strip() for s in raw_text.split('---') if s.strip()]

        CHUNK_SIZE = 3
        all_roles = []

        if len(jd_segments) <= CHUNK_SIZE:
            # Small batch - parse all at once
            logger.info("Ingest job %s: parsing %d JDs in single call", job_id, len(jd_segments))
            all_roles = _parse_chunk(raw_text, settings, chunk_label=f"job {job_id}")
        else:
            # Large batch - chunk into groups of CHUNK_SIZE
            chunks = [jd_segments[i:i + CHUNK_SIZE] for i in range(0, len(jd_segments), CHUNK_SIZE)]
            logger.info("Ingest job %s: parsing %d JDs in %d chunks of ≤%d", job_id, len(jd_segments), len(chunks), CHUNK_SIZE)

            for idx, chunk in enumerate(chunks):
                if job.get("status") == "cancelled":
                    return
                chunk_text = '\n\n---\n\n'.join(chunk)
                label = f"job {job_id} chunk {idx+1}/{len(chunks)}"
                logger.info("Parsing %s (%d JDs)...", label, len(chunk))
                try:
                    chunk_roles = _parse_chunk(chunk_text, settings, chunk_label=label)
                    all_roles.extend(chunk_roles)
                    logger.info("Chunk %d/%d: parsed %d roles", idx+1, len(chunks), len(chunk_roles))
                except Exception as e:
                    logger.error("Chunk %d/%d failed: %s", idx+1, len(chunks), e)
                    # Continue with other chunks rather than failing entirely
                    job.setdefault("warnings", []).append(f"Chunk {idx+1} failed: {e}")

        roles = all_roles

        if not roles:
            job["status"] = "error"
            job["error"] = "No job postings found in the provided text"
            return

        # Duplicate detection
        def similarity_ratio(a: str, b: str) -> float:
            return SequenceMatcher(None, a.lower(), b.lower()).ratio()

        db = SessionLocal()
        try:
            existing_roles = db.query(Role).all()

            for i, role in enumerate(roles):
                role['is_duplicate'] = False
                role['duplicate_reason'] = None
                role['duplicate_warnings'] = []

                for j, other_role in enumerate(roles):
                    if i != j:
                        same_company = role.get('company_name', '').lower() == other_role.get('company_name', '').lower()
                        title_similarity = similarity_ratio(role.get('title', ''), other_role.get('title', ''))
                        if same_company and title_similarity > 0.8:
                            role['duplicate_warnings'].append(
                                f"Duplicate within parse: Similar to role #{j+1} in this batch"
                            )

                company_name = role.get('company_name', '')
                title = role.get('title', '')
                for existing_role in existing_roles:
                    same_company = existing_role.company_name.lower() == company_name.lower()
                    title_similarity = similarity_ratio(title, existing_role.title)
                    if same_company and title_similarity > 0.8:
                        role['is_duplicate'] = True
                        role['duplicate_reason'] = f"Similar role exists: {existing_role.title} at {existing_role.company_name} (created {existing_role.created_at.strftime('%Y-%m-%d')})"
                        role['duplicate_warnings'].append(
                            f"Database duplicate: {existing_role.title} at {existing_role.company_name} (created {existing_role.created_at.strftime('%Y-%m-%d')})"
                        )
                        break
        finally:
            db.close()

        job["results"] = roles
        job["raw_segments"] = jd_segments
        job["status"] = "done"
        logger.info("Ingest job %s completed: %d roles parsed from %d segments", job_id, len(roles), len(jd_segments))

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        logger.error("Ingest job %s failed: %s", job_id, e)


@router.post("/roles/ingest", tags=["roles"])
def start_ingest_job(raw_text: str = Body(..., embed=True)):
    """
    Start an async JD ingest job. Returns a job_id immediately.
    The parsing runs in a background thread so it survives frontend disconnects.
    Poll GET /roles/ingest/{job_id} for status.
    """
    import uuid as _uuid
    import threading
    from datetime import datetime
    from app.core.config import settings

    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="DeepSeek API key not configured")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="No text provided")

    job_id = str(_uuid.uuid4())[:8]
    _ingest_jobs[job_id] = {
        "status": "processing",
        "raw_text": raw_text,
        "results": None,
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
    }

    thread = threading.Thread(target=_run_ingest_job, args=(job_id, raw_text), daemon=True)
    thread.start()

    logger.info("Ingest job %s started (%d chars)", job_id, len(raw_text))
    return {"job_id": job_id, "status": "processing"}


@router.get("/roles/ingest/{job_id}", tags=["roles"])
def get_ingest_status(job_id: str):
    """Poll for ingest job status. Returns results when done."""
    job = _ingest_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingest job not found")

    resp = {"job_id": job_id, "status": job["status"]}
    if job["status"] == "done":
        resp["results"] = job["results"]
        resp["count"] = len(job["results"])
        if job.get("raw_segments"):
            resp["raw_segments"] = job["raw_segments"]
        if job.get("warnings"):
            resp["warnings"] = job["warnings"]
    elif job["status"] == "error":
        resp["error"] = job["error"]
    return resp


@router.delete("/roles/ingest/{job_id}", tags=["roles"])
def cancel_ingest_job(job_id: str):
    """Cancel / discard an ingest job."""
    if job_id in _ingest_jobs:
        del _ingest_jobs[job_id]
        return {"status": "cancelled"}
    raise HTTPException(status_code=404, detail="Ingest job not found")


@router.get("/roles/counts", tags=["roles"])
def get_role_counts(db: Session = Depends(get_db)):
    """Get aggregated counts for roles"""
    from sqlalchemy import func
    total = db.query(func.count(Role.id)).scalar()
    status_counts = db.query(
        Role.status, func.count(Role.id)
    ).group_by(Role.status).all()

    counts = {'all': total}
    for status, count in status_counts:
        if status:
            counts[status.value if hasattr(status, 'value') else str(status)] = count
    return counts


@router.get("/roles/match-stats", tags=["roles"])
def get_role_match_stats(db: Session = Depends(get_db)):
    """Get match count, starred count, and outreach count per role (single efficient query)"""
    from sqlalchemy import func, case
    from app.models.match import Match

    stats = (
        db.query(
            Match.role_id,
            func.count(Match.id).label('match_count'),
            func.sum(case((Match.starred == True, 1), else_=0)).label('starred_count'),
            func.sum(case((
                (Match.starred == True) & (Candidate.warmup_email_sent_at.isnot(None)),
                1
            ), else_=0)).label('outreached_count'),
        )
        .join(Candidate, Candidate.id == Match.candidate_id)
        .group_by(Match.role_id)
        .all()
    )

    # Count unique candidates across all matches
    unique_candidates = db.query(func.count(func.distinct(Match.candidate_id))).scalar() or 0

    result = {
        str(row.role_id): {
            "match_count": row.match_count,
            "starred_count": int(row.starred_count or 0),
            "outreached_count": int(row.outreached_count or 0),
        }
        for row in stats
    }
    result["_summary"] = {"unique_candidates": unique_candidates}
    return result


@router.get("/roles/{role_id}/peek", tags=["roles"])
def peek_role_candidates(role_id: str, kind: str = Query("starred", regex="^(starred|outreached)$"), db: Session = Depends(get_db)):
    """Return a short list of candidate names that are starred or outreached for a role."""
    from app.models.match import Match

    q = (
        db.query(Candidate.name, Candidate.github_username)
        .join(Match, Match.candidate_id == Candidate.id)
        .filter(Match.role_id == role_id, Match.starred == True)
    )
    if kind == "outreached":
        q = q.filter(Candidate.warmup_email_sent_at.isnot(None))

    rows = q.order_by(Candidate.name).limit(20).all()
    return [{"name": r.name or r.github_username or "Unknown"} for r in rows]


@router.get("/roles/", response_model=List[RoleInDB], tags=["roles"])
def list_roles(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    company_stage: Optional[str] = None,
    urgency: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List roles with optional filters"""
    return crud.get_roles(
        db, skip=skip, limit=limit, status=status, company_stage=company_stage, urgency=urgency
    )


@router.put("/roles/reorder", tags=["roles"])
def reorder_roles(
    ordering: List[dict],
    db: Session = Depends(get_db),
):
    """
    Update position of roles.
    Expects a list of {id: str, position: int}.
    Must be defined before /roles/{role_id} to avoid route shadowing.
    """
    for item in ordering:
        role = db.query(Role).filter(Role.id == item["id"]).first()
        if role:
            role.position = item["position"]
    db.commit()
    return {"message": "Roles reordered", "count": len(ordering)}


@router.get("/roles/{role_id}", response_model=RoleInDB, tags=["roles"])
def get_role(role_id: UUID, db: Session = Depends(get_db)):
    """Get a specific role by ID"""
    role = crud.get_role(db, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@router.put("/roles/{role_id}", response_model=RoleInDB, tags=["roles"])
def update_role(role_id: UUID, role: RoleUpdate, db: Session = Depends(get_db)):
    """
    Update a role with auto-parsing from job description.

    If jd_text is provided, we'll automatically re-parse:
    - Tech stack (Python, React, PostgreSQL, etc.)
    - Location requirement (remote/hybrid/onsite)
    - Compensation range (salary and equity)
    """
    from app.services.role_sourcing import parse_tech_stack, parse_location_requirement, parse_compensation
    from app.models.role import LocationRequirement

    logger.debug("Received role update data: %s", role.model_dump())

    # Get existing role data
    existing_role = crud.get_role(db, role_id)
    if not existing_role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Convert to dict for modification
    role_data = role.model_dump(exclude_unset=True)

    # Auto-parse from jd_text if it's being updated or exists
    jd_text = role_data.get('jd_text') or existing_role.jd_text
    if jd_text:
        # Parse tech stack if not manually provided
        if 'tech_stack' not in role_data or not role_data.get('tech_stack') or len(role_data.get('tech_stack', [])) == 0:
            parsed_tech = parse_tech_stack(jd_text)
            if parsed_tech:
                role_data['tech_stack'] = parsed_tech
                logger.debug("Parsed tech stack: %s", parsed_tech)

        # Parse location requirement if not manually provided
        if 'location_requirement' not in role_data or not role_data.get('location_requirement'):
            parsed_location = parse_location_requirement(jd_text)
            if parsed_location:
                try:
                    # Convert string to enum
                    role_data['location_requirement'] = LocationRequirement(parsed_location)
                    logger.debug("Parsed location: %s", parsed_location)
                except ValueError:
                    pass  # Invalid value, skip

        # Parse compensation if not manually provided
        if ('comp_min' not in role_data or not role_data.get('comp_min')) and \
           ('equity_min' not in role_data or not role_data.get('equity_min')):
            parsed_comp = parse_compensation(jd_text)
            if parsed_comp['comp_min']:
                role_data['comp_min'] = parsed_comp['comp_min']
                role_data['comp_max'] = parsed_comp['comp_max']
                logger.debug("Parsed compensation: $%s-$%s", parsed_comp['comp_min'], parsed_comp['comp_max'])
            if parsed_comp['equity_min']:
                role_data['equity_min'] = parsed_comp['equity_min']
                role_data['equity_max'] = parsed_comp['equity_max']
                logger.debug("Parsed equity: %s-%s%%", parsed_comp['equity_min'], parsed_comp['equity_max'])

    # Recreate the Pydantic model with updated data
    updated_role_data = RoleUpdate(**role_data)
    updated_role = crud.update_role(db, role_id, updated_role_data)
    if not updated_role:
        raise HTTPException(status_code=404, detail="Role not found")
    return updated_role


@router.delete("/roles/{role_id}", tags=["roles"])
def delete_role(role_id: UUID, db: Session = Depends(get_db)):
    """Delete a role"""
    success = crud.delete_role(db, role_id)
    if not success:
        raise HTTPException(status_code=404, detail="Role not found")
    return {"message": "Role deleted successfully"}


@router.post("/roles/scrape", tags=["roles"])
def scrape_jobs(source: str = "work_at_startup", db: Session = Depends(get_db)):
    """
    Scrape engineering jobs from job boards and save them to the database.

    Supported sources:
    - work_at_startup: YC Work at a Startup
    - hn_who_is_hiring: Hacker News Who's Hiring thread

    Returns: Stats about scraped jobs
    """
    from app.services.role_sourcing import scrape_work_at_startup, scrape_hn_hiring
    from app.schemas.role import RoleCreate

    logger.info("Starting scrape from source: %s", source)

    stats = {
        'source': source,
        'roles_found': 0,
        'roles_saved': 0,
        'errors': 0,
        'roles': []
    }

    try:
        # Get roles from the specified source
        if source == "work_at_startup":
            roles_data = scrape_work_at_startup()
        elif source == "hn_who_is_hiring":
            roles_data = scrape_hn_hiring()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown source: {source}")

        stats['roles_found'] = len(roles_data)
        logger.info("Found %d roles from %s", len(roles_data), source)

        # Save each role to database with deduplication
        stats['duplicates_skipped'] = 0

        for role_data in roles_data:
            try:
                # Check for duplicates before creating
                # First check by URL (most reliable)
                existing_role = None
                if role_data.get('jd_url'):
                    existing_role = crud.get_role_by_url(db, role_data['jd_url'])

                # If no URL match, check by company + title
                if not existing_role:
                    existing_role = crud.get_role_by_company_and_title(
                        db,
                        role_data.get('company_name', ''),
                        role_data.get('title', '')
                    )

                if existing_role:
                    logger.info("Skipping duplicate: %s - %s", role_data.get('company_name'), role_data.get('title'))
                    stats['duplicates_skipped'] += 1
                    continue

                # Create RoleCreate schema from scraped data
                role = RoleCreate(**role_data)

                # Save to database using existing create_role logic
                created_role = crud.create_role(db, role)

                stats['roles_saved'] += 1
                stats['roles'].append({
                    'company_name': created_role.company_name,
                    'title': created_role.title,
                    'id': str(created_role.id)
                })
                logger.info("Saved: %s - %s", created_role.company_name, created_role.title)

            except Exception as e:
                logger.error("Error saving role: %s", e)
                stats['errors'] += 1
                continue

        logger.info("Scrape complete - Saved %d/%d roles", stats['roles_saved'], stats['roles_found'])

        return {
            "success": True,
            "message": f"Scraped {stats['roles_found']} jobs, saved {stats['roles_saved']} to database",
            **stats
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error scraping jobs: {str(e)}"
        )


# Match Routes
@router.post("/matches/", response_model=MatchInDB, tags=["matches"])
def create_match(match: MatchCreate, db: Session = Depends(get_db)):
    """Create a new match between candidate and role"""
    # Verify candidate and role exist
    candidate = crud.get_candidate(db, match.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    role = crud.get_role(db, match.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Check for existing match
    existing = db.query(Match).filter(
        Match.candidate_id == match.candidate_id,
        Match.role_id == match.role_id,
    ).first()
    if existing:
        # If requesting star, update and return existing match
        if match.starred and not existing.starred:
            existing.starred = True
            db.commit()
            db.refresh(existing)
            return existing
        raise HTTPException(status_code=409, detail="Match already exists for this candidate and role")

    return crud.create_match(db, match)


@router.get("/matches/all", tags=["matches"])
def list_all_matches(
    skip: int = 0, limit: int = 5000, min_score: int = 0, db: Session = Depends(get_db)
):
    """List all matches across all roles, sorted by score desc. Includes candidate, role, and fit_analysis."""
    matches = crud.get_all_matches(db, skip=skip, limit=limit, min_score=min_score)
    if not matches:
        return []
    result = []
    for m in matches:
        match_data = MatchInDB.model_validate(m).model_dump(mode='json')
        result.append(match_data)
    return result


@router.get("/matches/role/{role_id}", tags=["matches"])
def list_matches_for_role(
    role_id: UUID, skip: int = 0, limit: int = 2000, db: Session = Depends(get_db)
):
    """List all matches for a specific role, with other_match_count and email_events per candidate"""
    from sqlalchemy import func

    matches = crud.get_matches_for_role(db, role_id, skip=skip, limit=limit)

    if not matches:
        return []

    # Batch query: count other matches for each candidate (excluding this role)
    candidate_ids = [m.candidate_id for m in matches]
    counts = (
        db.query(Match.candidate_id, func.count(Match.id))
        .filter(Match.candidate_id.in_(candidate_ids), Match.role_id != role_id)
        .group_by(Match.candidate_id)
        .all()
    )
    count_map = {str(cid): cnt for cid, cnt in counts}

    # Batch-load email events for all candidates in one query
    from app.models.email_event import EmailEvent
    all_events = (
        db.query(EmailEvent)
        .filter(EmailEvent.candidate_id.in_(candidate_ids))
        .order_by(EmailEvent.candidate_id, EmailEvent.sequence.asc())
        .all()
    ) if candidate_ids else []
    events_by_candidate = {}
    for ev in all_events:
        cid = str(ev.candidate_id)
        if cid not in events_by_candidate:
            events_by_candidate[cid] = []
        events_by_candidate[cid].append({
            "id": str(ev.id),
            "event_type": ev.event_type.value,
            "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
            "subject": ev.subject,
            "body": ev.body,
            "resend_email_id": ev.resend_email_id,
            "metadata": ev.metadata_,
            "sequence": ev.sequence,
        })

    for m in matches:
        m.other_match_count = count_map.get(str(m.candidate_id), 0)

    # Serialize via Pydantic then attach email_events
    result = []
    for m in matches:
        match_data = MatchInDB.model_validate(m).model_dump(mode='json')
        cid = str(m.candidate_id)
        if match_data.get("candidate"):
            match_data["candidate"]["email_events"] = events_by_candidate.get(cid, [])
        result.append(match_data)

    return result


@router.get("/matches/candidate/{candidate_id}", response_model=List[MatchInDB], tags=["matches"])
def list_matches_for_candidate(
    candidate_id: UUID, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)
):
    """List all matches for a specific candidate"""
    return crud.get_matches_for_candidate(db, candidate_id, skip=skip, limit=limit)


@router.get("/matches/{match_id}", response_model=MatchInDB, tags=["matches"])
def get_match(match_id: UUID, db: Session = Depends(get_db)):
    """Get a specific match by ID"""
    match = crud.get_match(db, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@router.put("/matches/{match_id}", response_model=MatchInDB, tags=["matches"])
def update_match(match_id: UUID, match: MatchUpdate, db: Session = Depends(get_db)):
    """Update a match"""
    updated_match = crud.update_match(db, match_id, match)
    if not updated_match:
        raise HTTPException(status_code=404, detail="Match not found")
    return updated_match


@router.delete("/matches/{match_id}", tags=["matches"])
def delete_match(match_id: UUID, db: Session = Depends(get_db)):
    """Delete a match"""
    success = crud.delete_match(db, match_id)
    if not success:
        raise HTTPException(status_code=404, detail="Match not found")
    return {"message": "Match deleted successfully"}


@router.delete("/matches/role/{role_id}/clear", tags=["matches"])
def clear_matches_for_role(role_id: UUID, db: Session = Depends(get_db)):
    """Delete all matches for a specific role"""
    from app.models.fit_analysis import FitAnalysis

    matches = crud.get_matches_for_role(db, role_id, limit=10000)
    count = len(matches)

    for m in matches:
        # Delete related fit_analysis records first
        db.query(FitAnalysis).filter(FitAnalysis.match_id == m.id).delete()
        db.delete(m)

    db.commit()
    return {"message": f"Deleted {count} matches", "deleted": count}


@router.post("/matches/bulk-clear", tags=["matches"])
def bulk_clear_matches(payload: dict, db: Session = Depends(get_db)):
    """Delete all matches for multiple roles at once"""
    from app.models.fit_analysis import FitAnalysis

    role_ids = payload.get("role_ids", [])
    if not role_ids:
        raise HTTPException(status_code=400, detail="No role_ids provided")

    total_deleted = 0
    for rid in role_ids:
        matches = crud.get_matches_for_role(db, UUID(rid), limit=10000)
        for m in matches:
            db.query(FitAnalysis).filter(FitAnalysis.match_id == m.id).delete()
            db.delete(m)
        total_deleted += len(matches)

    db.commit()
    return {"message": f"Deleted {total_deleted} matches across {len(role_ids)} roles", "deleted": total_deleted}


@router.post("/matches/role/{role_id}/analyze-unanalyzed", tags=["matches", "analysis"])
def analyze_unanalyzed_matches(role_id: UUID, db: Session = Depends(get_db)):
    """
    Find matched candidates for a role that haven't been analyzed (no archetype),
    run VibeChekk on them, then re-run CrossChekk with the real data.

    Returns immediately with a job_id. Poll /ingestion/job/status/{job_id} for progress.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    from app.models.fit_analysis import FitAnalysis
    import threading

    role = crud.get_role(db, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Find matches where the candidate has no archetype (unanalyzed)
    matches = db.query(Match).filter(Match.role_id == role_id).all()
    unanalyzed = []
    for m in matches:
        candidate = crud.get_candidate(db, m.candidate_id)
        if candidate and not candidate.archetype:
            unanalyzed.append({'match_id': str(m.id), 'candidate_id': str(candidate.id)})

    if not unanalyzed:
        return {
            "message": "All matched candidates already have archetypes",
            "total_unanalyzed": 0,
            "job_id": None
        }

    # Create job record for progress tracking
    job = IngestionJob(
        status=JobStatus.running,
        job_type='analyze_unanalyzed',
        role_id=role_id,
        total_candidates=len(unanalyzed),
        processed_count=0,
        candidates_saved=0,
        error_count=0,
        recent_logs=[],
        stats={'phase': 'vibechekk', 'vibechekk_done': 0, 'crosschekk_done': 0, 'total': len(unanalyzed)}
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_id = str(job.id)
    logger.info("Created analyze-unanalyzed job %s for %d candidates on role %s", job_id, len(unanalyzed), role.title)

    def process_in_background(unanalyzed_list, role_id_str, job_id_str):
        from app.db.base import SessionLocal
        from app.models.ingestion_job import IngestionJob, JobStatus
        from app.services.fit_score_calculator import calculate_fit_score, parse_jd
        from app.core.config import settings
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from threading import Lock
        from sqlalchemy.orm.attributes import flag_modified
        import pytz

        bg_db = SessionLocal()
        try:
            bg_job = bg_db.query(IngestionJob).filter(IngestionJob.id == job_id_str).first()
            bg_role = crud.get_role(bg_db, UUID(role_id_str))

            def add_log(msg):
                if not bg_job.recent_logs:
                    bg_job.recent_logs = []
                est = pytz.timezone('US/Eastern')
                ts = datetime.now(est).strftime('%d/%m/%y %I:%M %p EST')
                bg_job.recent_logs.append({'timestamp': ts, 'message': msg})
                if len(bg_job.recent_logs) > 5000:
                    bg_job.recent_logs = bg_job.recent_logs[-5000:]
                flag_modified(bg_job, 'recent_logs')

            # ── Phase 1: VibeChekk (archetype analysis) with 10 workers ──
            add_log(f"Phase 1: Running VibeChekk on {len(unanalyzed_list)} candidates...")
            bg_db.commit()

            vibechekk_done = 0
            vibechekk_lock = Lock()

            def run_vibechekk(candidate_id_str):
                from app.db.base import SessionLocal as WSessionLocal
                worker_db = WSessionLocal()
                try:
                    result = run_candidate_analysis(UUID(candidate_id_str), worker_db)
                    return {'candidate_id': candidate_id_str, 'success': True, 'archetype': result.get('archetype'), 'tier': result.get('tier')}
                except Exception as e:
                    return {'candidate_id': candidate_id_str, 'success': False, 'error': str(e)}
                finally:
                    worker_db.close()

            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(run_vibechekk, item['candidate_id']): item for item in unanalyzed_list}
                for future in as_completed(futures):
                    # Check if stopped
                    bg_db.refresh(bg_job)
                    if bg_job.status == JobStatus.stopped:
                        executor.shutdown(wait=False, cancel_futures=True)
                        return

                    result = future.result()
                    with vibechekk_lock:
                        vibechekk_done += 1
                        cid_short = result['candidate_id'][:8]
                        if result['success']:
                            add_log(f"✓ VibeChekk {cid_short}... → {result.get('archetype', '?')} ({result.get('tier', '?')})")
                            bg_job.candidates_saved = (bg_job.candidates_saved or 0) + 1
                        else:
                            add_log(f"✗ VibeChekk {cid_short}... → Error: {result.get('error', '?')[:60]}")
                            bg_job.error_count = (bg_job.error_count or 0) + 1

                        bg_job.processed_count = vibechekk_done
                        bg_job.stats = {**(bg_job.stats or {}), 'phase': 'vibechekk', 'vibechekk_done': vibechekk_done}
                        flag_modified(bg_job, 'stats')
                        bg_db.commit()

            # ── Phase 2: CrossChekk (fit analysis) with 5 workers ──
            add_log(f"Phase 2: Running CrossChekk on {len(unanalyzed_list)} candidates...")
            bg_job.stats = {**(bg_job.stats or {}), 'phase': 'crosschekk', 'crosschekk_done': 0}
            flag_modified(bg_job, 'stats')
            bg_db.commit()

            parsed_jd = parse_jd(bg_role.jd_text or "", bg_role.title, getattr(bg_role, 'seniority_level', None))
            crosschekk_done = 0
            crosschekk_lock = Lock()

            def run_crosschekk(item):
                from app.db.base import SessionLocal as WSessionLocal
                worker_db = WSessionLocal()
                try:
                    candidate = crud.get_candidate(worker_db, UUID(item['candidate_id']))
                    if not candidate:
                        return {'candidate_id': item['candidate_id'], 'match_id': item['match_id'], 'success': False, 'error': 'Candidate not found'}

                    vibe_report = candidate.vibe_report or {}
                    tech_stack = candidate.tech_stack or []
                    if not tech_stack and vibe_report.get('verified_skills'):
                        tech_stack = [s.get('name') for s in vibe_report.get('verified_skills', []) if s.get('name')]
                    if not tech_stack and candidate.github_languages:
                        tech_stack = candidate.github_languages

                    candidate_data = {
                        'name': candidate.name or candidate.github_username,
                        'github_username': candidate.github_username,
                        'github_url': candidate.github_url,
                        'yoe': candidate.yoe or 3,
                        'tech_stack': tech_stack,
                        'archetype': candidate.archetype,
                        'tier': candidate.tier,
                        'tier_badge': candidate.tier_badge,
                        'tier_percentile': candidate.tier_percentile,
                        'location': candidate.location_raw,
                        'current_role': candidate.current_role,
                        'current_company': candidate.current_company,
                        'notes': getattr(candidate, 'notes', '') or '',
                        'resume_text': getattr(candidate, 'resume_text', '') or '',
                        'linkedin_text': getattr(candidate, 'linkedin_text', '') or '',
                        'github_metrics': {
                            'followers': candidate.github_followers,
                            'public_repos': candidate.github_public_repos,
                            'commits_30d': candidate.github_commits_30d,
                            'commits_90d': candidate.github_commits_90d,
                            'total_commits': candidate.github_total_commits,
                            'original_repos': candidate.github_original_repos,
                            'total_stars': candidate.github_total_stars,
                            'languages': candidate.github_languages or []
                        },
                        'vibe_report': vibe_report
                    }

                    fit_result = calculate_fit_score(settings.DEEPSEEK_API_KEY, candidate_data, parsed_jd)
                    return {
                        'candidate_id': item['candidate_id'],
                        'match_id': item['match_id'],
                        'success': True,
                        'fit_result': fit_result
                    }
                except Exception as e:
                    return {'candidate_id': item['candidate_id'], 'match_id': item['match_id'], 'success': False, 'error': str(e)}
                finally:
                    worker_db.close()

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(run_crosschekk, item): item for item in unanalyzed_list}
                for future in as_completed(futures):
                    bg_db.refresh(bg_job)
                    if bg_job.status == JobStatus.stopped:
                        executor.shutdown(wait=False, cancel_futures=True)
                        return

                    result = future.result()
                    with crosschekk_lock:
                        crosschekk_done += 1
                        cid_short = result['candidate_id'][:8]

                        if result['success']:
                            fit_result = result['fit_result']
                            try:
                                match_obj = crud.get_match(bg_db, UUID(result['match_id']))
                                candidate_obj = crud.get_candidate(bg_db, UUID(result['candidate_id']))

                                # Delete old FitAnalysis
                                bg_db.query(FitAnalysis).filter(FitAnalysis.match_id == match_obj.id).delete()
                                bg_db.flush()

                                # Save new FitAnalysis
                                fit_analysis = FitAnalysis(
                                    candidate_id=candidate_obj.id,
                                    role_id=bg_role.id,
                                    match_id=match_obj.id,
                                    fit_score=int(fit_result.get('fitScore', 0)),
                                    recommendation=fit_result.get('recommendation', 'SKIP'),
                                    skills_matched=fit_result.get('skillsMatch', {}).get('matched', []),
                                    skills_missing=fit_result.get('skillsMatch', {}).get('missing', []),
                                    skills_extra=fit_result.get('skillsMatch', {}).get('extra', []),
                                    candidate_level=('Mid-Level' if fit_result.get('experienceMatch', {}).get('candidateLevel') == 'Mid' else fit_result.get('experienceMatch', {}).get('candidateLevel')),
                                    required_level=parsed_jd.get('seniority', fit_result.get('experienceMatch', {}).get('requiredLevel')),
                                    experience_meets=1 if parsed_jd.get('seniority') == 'Flexible' else (1 if fit_result.get('experienceMatch', {}).get('meets') else 0),
                                    strengths=fit_result.get('strengthsForRole', []),
                                    concerns=fit_result.get('concernsForRole', []),
                                    ai_summary=fit_result.get('aiSummary'),
                                    ai_summary_short=fit_result.get('aiSummaryShort'),
                                    full_analysis=fit_result
                                )
                                bg_db.add(fit_analysis)

                                # Update match score
                                match_obj.match_score = int(fit_result.get('fitScore', 0))
                                match_obj.score_breakdown = {
                                    **(match_obj.score_breakdown or {}),
                                    'crosschekk_score': fit_result.get('fitScore', 0),
                                    'recommendation': fit_result.get('recommendation')
                                }

                                score = fit_result.get('fitScore', 0)
                                rec = fit_result.get('recommendation', '?')
                                add_log(f"✓ CrossChekk {cid_short}... → {score} ({rec})")
                            except Exception as e:
                                add_log(f"✗ CrossChekk {cid_short}... → DB error: {str(e)[:60]}")
                                bg_job.error_count = (bg_job.error_count or 0) + 1
                        else:
                            add_log(f"✗ CrossChekk {cid_short}... → Error: {result.get('error', '?')[:60]}")
                            bg_job.error_count = (bg_job.error_count or 0) + 1

                        bg_job.stats = {**(bg_job.stats or {}), 'phase': 'crosschekk', 'crosschekk_done': crosschekk_done}
                        flag_modified(bg_job, 'stats')
                        bg_db.commit()

            # Mark completed
            bg_job.status = JobStatus.completed
            bg_job.completed_at = datetime.utcnow()
            bg_job.stats = {**(bg_job.stats or {}), 'phase': 'done'}
            flag_modified(bg_job, 'stats')
            add_log(f"Done: {vibechekk_done} analyzed, {crosschekk_done} scored")
            bg_db.commit()
            logger.info("Job %s completed: %d VibeChekk, %d CrossChekk", job_id_str, vibechekk_done, crosschekk_done)

        except Exception as e:
            logger.error("Job %s failed: %s", job_id_str, e)
            try:
                bg_job.status = JobStatus.failed
                bg_job.error_message = str(e)
                bg_db.commit()
            except Exception:
                pass
        finally:
            bg_db.close()

    thread = threading.Thread(
        target=process_in_background,
        args=(unanalyzed, str(role_id), job_id),
        daemon=True
    )
    thread.start()

    return {
        "message": f"Analyzing {len(unanalyzed)} unanalyzed candidates",
        "job_id": job_id,
        "total_unanalyzed": len(unanalyzed),
        "status": "running"
    }


@router.post("/matches/{match_id}/star", tags=["matches"])
def toggle_match_star(match_id: UUID, db: Session = Depends(get_db)):
    """Toggle starred status on a match. Also increments/decrements the candidate's star_count."""
    match = crud.get_match(db, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    match.starred = not match.starred

    # Update candidate's accumulated star_count
    candidate = crud.get_candidate(db, match.candidate_id)
    if candidate:
        if match.starred:
            candidate.star_count = (candidate.star_count or 0) + 1
        else:
            candidate.star_count = max((candidate.star_count or 0) - 1, 0)

    db.commit()
    db.refresh(match)
    return {"starred": match.starred, "match_id": str(match.id), "star_count": candidate.star_count if candidate else 0}


@router.post("/candidates/{candidate_id}/unstar-all", tags=["candidates", "starred"])
def unstar_all_matches(candidate_id: UUID, db: Session = Depends(get_db)):
    """Remove all stars from a candidate (unstar every match, set star_count to 0)."""
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    starred_matches = db.query(Match).filter(
        Match.candidate_id == candidate_id, Match.starred == True
    ).all()
    for m in starred_matches:
        m.starred = False

    candidate.star_count = 0
    db.commit()

    return {"success": True, "unstarred_count": len(starred_matches)}


# ─── Bookmarks (Outreach-level candidate flagging) ──────────────────────
@router.post("/candidates/{candidate_id}/bookmark", tags=["candidates", "outreach"])
def toggle_candidate_bookmark(candidate_id: UUID, db: Session = Depends(get_db)):
    """Toggle bookmarked status on a candidate (for flagging high-intent outreach replies).
    Uses raw SQL to avoid triggering updated_at onupdate (bookmark shouldn't change sort order)."""
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    new_value = not (candidate.bookmarked or False)
    # Raw update to bypass SQLAlchemy onupdate=datetime.utcnow on updated_at
    from sqlalchemy import text
    db.execute(
        text("UPDATE candidates SET bookmarked = :val WHERE id = :cid"),
        {"val": new_value, "cid": candidate_id},
    )
    db.commit()
    return {"bookmarked": new_value, "candidate_id": str(candidate_id)}


# ─── Toggle Warm Status (manual override) ──────────────────────────────
@router.post("/candidates/{candidate_id}/toggle-warm", tags=["candidates"])
def toggle_candidate_warm(candidate_id: UUID, db: Session = Depends(get_db)):
    """Toggle manually_warmed flag (and sync behavior_tier).
    Uses raw SQL to avoid triggering updated_at onupdate."""
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    # Toggle based on manually_warmed (the source of truth for the UI),
    # NOT behavior_tier which may be set by ingestion scoring.
    is_warming = not bool(candidate.manually_warmed)
    new_tier = "hot" if is_warming else "cold"
    from sqlalchemy import text
    db.execute(
        text("UPDATE candidates SET behavior_tier = :val, manually_warmed = :mw WHERE id = :cid"),
        {"val": new_tier, "mw": is_warming, "cid": candidate_id},
    )
    db.commit()
    return {"behavior_tier": new_tier, "manually_warmed": is_warming, "candidate_id": str(candidate_id)}


# ─── Admin Update Links ────────────────────────────────────────────────
class AdminUpdateLinksRequest(BaseModel):
    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    website_url: Optional[str] = None
    github_url: Optional[str] = None


@router.put("/candidates/{candidate_id}/links", tags=["candidates"])
def update_candidate_links(candidate_id: UUID, request: AdminUpdateLinksRequest, db: Session = Depends(get_db)):
    """Update candidate social/professional links (admin only)."""
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    updates = {}
    if request.linkedin_url is not None:
        updates["linkedin_url"] = request.linkedin_url or None
    if request.twitter_url is not None:
        updates["twitter_url"] = request.twitter_url or None
    if request.website_url is not None:
        updates["website_url"] = request.website_url or None
    if request.github_url is not None:
        updates["github_url"] = request.github_url or None
    if updates:
        from app.schemas.candidate import CandidateUpdate
        crud.update_candidate(db, candidate_id, CandidateUpdate(**updates))
        db.commit()
    return {"success": True, "updated": list(updates.keys()), "candidate_id": str(candidate_id)}


@router.post("/matches/{match_id}/analyze", tags=["matches", "analysis"])
def analyze_match(match_id: UUID, db: Session = Depends(get_db)):
    """
    Run CrossChekk FitScore analysis for a candidate-role match.

    This compares the candidate's skills and experience against
    the role requirements and generates a SEND/SKIP recommendation.
    """
    from app.core.config import settings
    from app.services.fit_score_calculator import calculate_fit_score, parse_jd
    from app.models.fit_analysis import FitAnalysis

    # Get match
    match = crud.get_match(db, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Get candidate and role
    candidate = crud.get_candidate(db, match.candidate_id)
    role = crud.get_role(db, match.role_id)

    if not candidate or not role:
        raise HTTPException(status_code=404, detail="Candidate or role not found")

    # Check if DeepSeek API key is configured
    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="DeepSeek API key not configured"
        )

    # Parse JD
    parsed_jd = parse_jd(role.jd_text or "", role.title, getattr(role, 'seniority_level', None))

    # Prepare candidate data
    candidate_data = {
        'github_username': candidate.github_username,
        'name': candidate.name,
        'archetype': candidate.archetype,
        'tier': candidate.tier,
        'tech_stack': candidate.tech_stack or [],
        'vibe_report': candidate.vibe_report or {},
        'github_metrics': candidate.github_metrics if hasattr(candidate, 'github_metrics') and candidate.github_metrics else {},
        'yoe': getattr(candidate, 'yoe', 0) or 0,
        'current_role': getattr(candidate, 'current_role', None),
        'current_company': getattr(candidate, 'current_company', None),
        'location': candidate.location_raw,
        'notes': getattr(candidate, 'notes', ''),
        'resume_text': getattr(candidate, 'resume_text', '') or '',
        'linkedin_text': getattr(candidate, 'linkedin_text', '') or '',
    }

    try:
        # Calculate fit score
        fit_result = calculate_fit_score(
            settings.DEEPSEEK_API_KEY,
            candidate_data,
            parsed_jd
        )

        # Delete any existing fit analysis for this match (so re-runs replace old data)
        db.query(FitAnalysis).filter(FitAnalysis.match_id == match_id).delete()
        db.flush()

        # Save fit analysis to database
        fit_analysis = FitAnalysis(
            candidate_id=candidate.id,
            role_id=role.id,
            match_id=match.id,
            fit_score=int(fit_result.get('fitScore', 0)),
            recommendation=fit_result.get('recommendation', 'SKIP'),
            skills_matched=fit_result.get('skillsMatch', {}).get('matched', []),
            skills_missing=fit_result.get('skillsMatch', {}).get('missing', []),
            skills_extra=fit_result.get('skillsMatch', {}).get('extra', []),
            # Normalize "Mid" → "Mid-Level" for better display
            candidate_level=('Mid-Level' if fit_result.get('experienceMatch', {}).get('candidateLevel') == 'Mid' else fit_result.get('experienceMatch', {}).get('candidateLevel')),
            # Use parsed JD seniority directly — don't trust DeepSeek to echo it back correctly
            required_level=parsed_jd.get('seniority', fit_result.get('experienceMatch', {}).get('requiredLevel')),
            # If required level is "Flexible" (JD didn't specify seniority), always meets requirement
            experience_meets=1 if parsed_jd.get('seniority') == 'Flexible' else (1 if fit_result.get('experienceMatch', {}).get('meets') else 0),
            strengths=fit_result.get('strengthsForRole', []),
            concerns=fit_result.get('concernsForRole', []),
            ai_summary=fit_result.get('aiSummary'),
            ai_summary_short=fit_result.get('aiSummaryShort'),
            full_analysis=fit_result
        )

        db.add(fit_analysis)
        db.commit()
        db.refresh(fit_analysis)

        # Update match score
        from app.schemas.match import MatchUpdate
        match_update = MatchUpdate(match_score=int(fit_result.get('fitScore', 0)))
        crud.update_match(db, match_id, match_update)

        return {
            "message": "CrossChekk analysis complete",
            "match_id": match_id,
            "fit_analysis_id": fit_analysis.id,
            "fit_score": fit_result.get('fitScore'),
            "recommendation": fit_result.get('recommendation'),
            "skills_matched": fit_result.get('skillsMatch', {}).get('matched', []),
            "skills_missing": fit_result.get('skillsMatch', {}).get('missing', []),
            "ai_summary": fit_result.get('aiSummary'),
            "ai_summary_short": fit_result.get('aiSummaryShort')
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"FitScore analysis failed: {str(e)}"
        )


@router.post("/matching/crosschekk-candidate/{candidate_id}", tags=["matching", "analysis"])
def crosschekk_candidate(
    candidate_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Start a background CrossChekk job for a single candidate against selected roles.

    Accepts: { "role_ids": ["uuid1", "uuid2", ...] }

    Returns immediately with a job_id. Poll /ingestion/job/status/{job_id} for progress.
    Results accumulate in checkpoint_data.results[role_id] as each role completes.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    import threading

    role_ids = body.get("role_ids", [])
    if not role_ids:
        raise HTTPException(status_code=400, detail="role_ids is required")

    # Validate candidate exists
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Check DeepSeek API key
    from app.core.config import settings
    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="DeepSeek API key not configured")

    # Validate roles exist and collect info
    roles_info = []
    for rid_str in role_ids:
        rid = UUID(rid_str) if isinstance(rid_str, str) else rid_str
        role = crud.get_role(db, rid)
        if role:
            roles_info.append({"id": str(role.id), "title": role.title, "company": role.company_name})

    if not roles_info:
        raise HTTPException(status_code=400, detail="No valid roles found")

    cname = candidate.name or candidate.github_username or "Unknown"
    cid = str(candidate_id)

    # Create background job
    job = IngestionJob(
        status=JobStatus.running,
        job_type='crosschekk_candidate',
        total_candidates=1,
        total_batches=len(roles_info),
        processed_count=0,
        candidates_saved=0,
        error_count=0,
        recent_logs=[],
        checkpoint_data={
            "candidate_id": cid,
            "candidate_name": cname,
            "roles": roles_info,
            "total_analyses": len(roles_info),
            "results": {},  # { role_id: { fit_score, recommendation, ... } }
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_id = str(job.id)
    roles_copy = list(roles_info)

    def run_candidate_crosschekk():
        from app.db.base import SessionLocal
        from app.models.ingestion_job import IngestionJob as IJModel, JobStatus as JS
        from app.models.fit_analysis import FitAnalysis
        from app.models.match import Match
        from app.services.fit_score_calculator import calculate_fit_score, parse_jd
        from app.services.scoring import calculate_match_score
        from app.schemas.match import MatchCreate
        from sqlalchemy.orm.attributes import flag_modified
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading as _threading

        PARALLEL_WORKERS = 3

        job_lock = _threading.Lock()
        counters = {"done": 0, "errors": 0, "cached": 0}

        coord_db = SessionLocal()

        def coord_add_log(coord_job, message):
            timestamp = datetime.utcnow().strftime('%H:%M:%S')
            logs = coord_job.recent_logs or []
            logs.append({'timestamp': timestamp, 'message': message})
            coord_job.recent_logs = logs[-100:]
            flag_modified(coord_job, 'recent_logs')

        def coord_flush(coord_job):
            coord_job.processed_count = counters["done"] + counters["errors"] + counters["cached"]
            coord_job.candidates_saved = counters["done"]
            coord_job.error_count = counters["errors"]
            flag_modified(coord_job, 'checkpoint_data')
            coord_db.commit()

        def analyze_one_role(role_info, candidate_data):
            w_db = SessionLocal()
            try:
                role = w_db.query(Role).filter(Role.id == role_info["id"]).first()
                if not role:
                    return {"role_id": role_info["id"], "error": "Role not found", "_cached": False}

                # Ensure match exists
                match = w_db.query(Match).filter(
                    Match.candidate_id == cid, Match.role_id == role.id
                ).first()
                if not match:
                    from app.services.scoring import calculate_match_score as calc_ms
                    cand_obj = w_db.query(Candidate).filter(Candidate.id == cid).first()
                    if cand_obj:
                        ms, sb = calc_ms(cand_obj, role)
                        match = Match(candidate_id=cid, role_id=role.id, match_score=ms, score_breakdown=sb)
                    else:
                        match = Match(candidate_id=cid, role_id=role.id)
                    w_db.add(match)
                    w_db.flush()

                # Check cached
                existing_fa = w_db.query(FitAnalysis).filter(FitAnalysis.match_id == match.id).first()
                if existing_fa and existing_fa.fit_score is not None:
                    return {
                        "role_id": str(role.id),
                        "role_title": role.title,
                        "company_name": role.company_name,
                        "match_id": str(match.id),
                        "match_score": match.match_score,
                        "fit_score": existing_fa.fit_score,
                        "recommendation": existing_fa.recommendation,
                        "skills_matched": existing_fa.skills_matched or [],
                        "skills_missing": existing_fa.skills_missing or [],
                        "skills_extra": existing_fa.skills_extra or [],
                        "strengths": existing_fa.strengths or [],
                        "concerns": existing_fa.concerns or [],
                        "ai_summary_short": existing_fa.ai_summary_short,
                        "ai_summary": existing_fa.ai_summary,
                        "candidate_level": existing_fa.candidate_level,
                        "required_level": existing_fa.required_level,
                        "cached": True,
                        "_cached": True,
                    }

                # Run analysis
                parsed_jd = parse_jd(role.jd_text or "", role.title, getattr(role, 'seniority_level', None))
                fit_result = calculate_fit_score(settings.DEEPSEEK_API_KEY, candidate_data, parsed_jd)

                fa = FitAnalysis(
                    candidate_id=cid,
                    role_id=role.id,
                    match_id=match.id,
                    fit_score=int(fit_result.get('fitScore', 0)),
                    recommendation=fit_result.get('recommendation', 'SKIP'),
                    skills_matched=fit_result.get('skillsMatch', {}).get('matched', []),
                    skills_missing=fit_result.get('skillsMatch', {}).get('missing', []),
                    skills_extra=fit_result.get('skillsMatch', {}).get('extra', []),
                    candidate_level=('Mid-Level' if fit_result.get('experienceMatch', {}).get('candidateLevel') == 'Mid'
                                     else fit_result.get('experienceMatch', {}).get('candidateLevel')),
                    required_level=parsed_jd.get('seniority', fit_result.get('experienceMatch', {}).get('requiredLevel')),
                    experience_meets=(1 if parsed_jd.get('seniority') == 'Flexible'
                                      else (1 if fit_result.get('experienceMatch', {}).get('meets') else 0)),
                    strengths=fit_result.get('strengthsForRole', []),
                    concerns=fit_result.get('concernsForRole', []),
                    ai_summary=fit_result.get('aiSummary'),
                    ai_summary_short=fit_result.get('aiSummaryShort'),
                    full_analysis=fit_result,
                )
                w_db.add(fa)
                match.match_score = int(fit_result.get('fitScore', 0))
                w_db.commit()

                return {
                    "role_id": str(role.id),
                    "role_title": role.title,
                    "company_name": role.company_name,
                    "match_id": str(match.id),
                    "match_score": int(fit_result.get('fitScore', 0)),
                    "fit_score": int(fit_result.get('fitScore', 0)),
                    "recommendation": fit_result.get('recommendation', 'SKIP'),
                    "skills_matched": fit_result.get('skillsMatch', {}).get('matched', []),
                    "skills_missing": fit_result.get('skillsMatch', {}).get('missing', []),
                    "skills_extra": fit_result.get('skillsMatch', {}).get('extra', []),
                    "strengths": fit_result.get('strengthsForRole', []),
                    "concerns": fit_result.get('concernsForRole', []),
                    "ai_summary_short": fit_result.get('aiSummaryShort'),
                    "ai_summary": fit_result.get('aiSummary'),
                    "candidate_level": fit_result.get('experienceMatch', {}).get('candidateLevel'),
                    "required_level": parsed_jd.get('seniority'),
                    "cached": False,
                    "_cached": False,
                }

            except Exception as e:
                return {
                    "role_id": role_info["id"],
                    "role_title": role_info.get("title", ""),
                    "company_name": role_info.get("company", ""),
                    "error": str(e)[:200],
                    "_cached": False,
                }
            finally:
                w_db.close()

        try:
            coord_job = coord_db.query(IJModel).filter(IJModel.id == job_id).first()
            coord_add_log(coord_job, f"Starting CrossChekk for {cname} against {len(roles_copy)} roles")
            coord_db.commit()

            # Prepare candidate data
            prep_db = SessionLocal()
            try:
                cand = prep_db.query(Candidate).filter(Candidate.id == cid).first()
                candidate_data = {
                    'github_username': cand.github_username,
                    'name': cand.name,
                    'archetype': cand.archetype,
                    'tier': cand.tier,
                    'tech_stack': cand.tech_stack or [],
                    'vibe_report': cand.vibe_report or {},
                    'github_metrics': cand.github_metrics if hasattr(cand, 'github_metrics') and cand.github_metrics else {},
                    'yoe': getattr(cand, 'yoe', 0) or 0,
                    'current_role': getattr(cand, 'current_role', None),
                    'current_company': getattr(cand, 'current_company', None),
                    'location': cand.location_raw,
                    'notes': getattr(cand, 'notes', ''),
                    'resume_text': getattr(cand, 'resume_text', '') or '',
                    'linkedin_text': getattr(cand, 'linkedin_text', '') or '',
                }
            finally:
                prep_db.close()

            with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
                future_to_role = {
                    pool.submit(analyze_one_role, ri, candidate_data): ri
                    for ri in roles_copy
                }

                for future in as_completed(future_to_role):
                    rinfo = future_to_role[future]
                    result = future.result()
                    if result is None:
                        continue

                    with job_lock:
                        was_cached = result.pop("_cached", False)
                        cp = coord_job.checkpoint_data or {}
                        cp["results"][rinfo["id"]] = result
                        coord_job.checkpoint_data = cp

                        if result.get("error"):
                            counters["errors"] += 1
                            coord_add_log(coord_job, f"  {rinfo['company']} — {rinfo['title']}: ERROR - {result['error'][:80]}")
                        elif was_cached:
                            counters["cached"] += 1
                            coord_add_log(coord_job, f"  {rinfo['company']} — {rinfo['title']}: {result.get('fit_score', 0)} (cached)")
                        else:
                            counters["done"] += 1
                            coord_add_log(coord_job, f"  {rinfo['company']} — {rinfo['title']}: {result.get('fit_score', 0)} ({result.get('recommendation', 'SKIP')})")

                        coord_job.current_search = f"{cname}: {rinfo['company']} — {rinfo['title']}"
                        coord_flush(coord_job)

            # Complete
            coord_db.refresh(coord_job)
            if coord_job.status != JS.stopped:
                coord_job.status = JS.completed
                coord_job.completed_at = datetime.utcnow()
                coord_add_log(coord_job, f"CrossChekk complete: {counters['done']} analyzed, {counters['cached']} cached, {counters['errors']} errors")
                coord_db.commit()

        except Exception as e:
            try:
                coord_job.status = JS.failed
                coord_job.completed_at = datetime.utcnow()
                coord_job.error_message = str(e)[:500]
                coord_db.commit()
            except Exception:
                pass
            logger.error("CrossChekk candidate job %s failed: %s", job_id, e)
        finally:
            coord_db.close()

    thread = threading.Thread(target=run_candidate_crosschekk, daemon=True)
    thread.start()

    return {
        "job_id": job_id,
        "candidate_id": cid,
        "candidate_name": cname,
        "total_roles": len(roles_info),
        "status": "running",
    }


# Matching Engine Routes
@router.post("/matching/generate/{role_id}", tags=["matching"])
def generate_matches(role_id: UUID, limit: int = 20, db: Session = Depends(get_db)):
    """Generate and return matches for a role without saving to database"""
    from app.services.matching import generate_matches_for_role

    matches = generate_matches_for_role(db, str(role_id), limit=limit)
    return {
        "role_id": role_id,
        "matches_count": len(matches),
        "matches": matches
    }


@router.post("/matching/create/{role_id}", tags=["matching"])
def create_matches(
    role_id: UUID,
    limit: int = 20,
    tier: Optional[str] = Query(None, description="Filter by candidate tier"),
    archetype: Optional[str] = Query(None, description="Filter by candidate archetype"),
    warmth: Optional[str] = Query(None, description="Filter by warmth: cold, outreached, warm"),
    include_dormant: bool = Query(False, description="Include dormant candidates"),
    previously_starred: bool = Query(False, description="Only include candidates with star_count > 0"),
    location_fit: Optional[str] = Query(None, description="Filter by location fit: strong, medium, weak, strong_medium"),
    exclusive: bool = Query(False, description="Only include candidates not matched to any other role"),
    db: Session = Depends(get_db),
):
    """Create Match records in database for a role, with optional filters"""
    from app.services.matching import create_matches_for_role

    filters = {}
    if tier:
        filters['tier'] = tier
    if archetype:
        filters['archetype'] = archetype
    if warmth:
        filters['warmth'] = warmth
    if include_dormant:
        filters['include_dormant'] = True
    if previously_starred:
        filters['previously_starred'] = True
    if location_fit:
        filters['location_fit'] = location_fit
    if exclusive:
        filters['exclusive'] = True
        filters['exclude_role_id'] = str(role_id)

    try:
        matches = create_matches_for_role(db, str(role_id), limit=limit, filters=filters)
        return {
            "role_id": role_id,
            "matches_created": len(matches),
            "message": f"Created {len(matches)} matches for role"
        }
    except Exception as e:
        logger.error("Failed to generate matches for role %s: %s", role_id, e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate matches: {str(e)}")


@router.post("/matching/regenerate-all", tags=["matching"])
def regenerate_all_matches(limit: int = 20, db: Session = Depends(get_db)):
    """Regenerate matches for all active roles"""
    from app.services.matching import regenerate_all_matches

    results = regenerate_all_matches(db, limit=limit)
    total_matches = sum(results.values())
    return {
        "roles_processed": len(results),
        "total_matches_created": total_matches,
        "details": results
    }


@router.get("/matching/bulk-generate/active", tags=["matching"])
def get_active_match_generation_job(db: Session = Depends(get_db)):
    """Check if there's an active (running/pending) match generation job."""
    from app.models.ingestion_job import IngestionJob, JobStatus
    job = db.query(IngestionJob).filter(
        IngestionJob.job_type == 'match_generation',
        IngestionJob.status.in_([JobStatus.pending, JobStatus.running]),
    ).order_by(IngestionJob.created_at.desc()).first()
    if job:
        return {"active": True, "job_id": str(job.id), "status": job.status.value}
    return {"active": False, "job_id": None}


class BulkMatchGenerateRequest(BaseModel):
    roles: List[Dict]  # [{ role_id, count, tier?, archetype?, warmth?, location_fit?, include_dormant?, previously_starred? }]


@router.post("/matching/bulk-generate/start", tags=["matching"])
def start_bulk_match_generation(
    body: BulkMatchGenerateRequest,
    db: Session = Depends(get_db),
):
    """
    Start a background bulk match generation job across multiple roles.

    Returns immediately with a job_id. Poll /ingestion/job/status/{job_id} for progress.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    import threading

    if not body.roles:
        raise HTTPException(status_code=400, detail="No roles provided")

    # Check for existing running match generation job
    existing = db.query(IngestionJob).filter(
        IngestionJob.job_type == 'match_generation',
        IngestionJob.status.in_([JobStatus.pending, JobStatus.running]),
    ).first()
    if existing:
        return {
            "success": False,
            "message": "A match generation job is already running",
            "job_id": str(existing.id),
            "status": existing.status.value,
        }

    # Validate roles and build info
    roles_info = []
    for r in body.roles:
        role = db.query(Role).filter(Role.id == r.get("role_id")).first()
        if role:
            roles_info.append({
                "role_id": str(role.id),
                "title": role.title,
                "company_name": role.company_name,
                "count": r.get("count", 20),
                "filters": {k: v for k, v in r.items() if k not in ("role_id", "count") and v},
            })

    if not roles_info:
        raise HTTPException(status_code=400, detail="No valid roles found")

    # Create job
    job = IngestionJob(
        status=JobStatus.running,
        job_type='match_generation',
        total_candidates=len(roles_info),  # repurpose: total roles
        total_batches=0,
        processed_count=0,
        candidates_saved=0,
        error_count=0,
        recent_logs=[],
        checkpoint_data={
            "roles": roles_info,
            "completed_roles": [],
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_id = str(job.id)
    roles_copy = list(roles_info)

    def run_match_generation_background():
        from app.db.base import SessionLocal
        from app.models.ingestion_job import IngestionJob as IJModel, JobStatus as JS
        from app.services.matching import generate_matches_for_role
        from app.services.fit_score_calculator import calculate_fit_score, parse_jd
        from app.models.fit_analysis import FitAnalysis
        from app.core.config import settings
        from sqlalchemy.orm.attributes import flag_modified
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading as _threading

        PARALLEL_WORKERS = 10

        job_lock = _threading.Lock()
        counters = {"done": 0, "errors": 0}
        stop_flag = _threading.Event()

        coord_db = SessionLocal()

        def coord_add_log(coord_job, message):
            ts = datetime.utcnow().strftime('%H:%M:%S')
            lg = coord_job.recent_logs or []
            lg.append({'timestamp': ts, 'message': message})
            coord_job.recent_logs = lg[-500:]
            flag_modified(coord_job, 'recent_logs')

        def coord_flush(coord_job):
            coord_job.processed_count = counters["done"] + counters["errors"]
            coord_job.candidates_saved = counters["done"]
            coord_job.error_count = counters["errors"]
            flag_modified(coord_job, 'checkpoint_data')
            coord_db.commit()

        def check_stopped(coord_job) -> bool:
            coord_db.refresh(coord_job)
            if coord_job.status == JS.stopped:
                stop_flag.set()
                return True
            return False

        def analyze_one_match(candidate_id: str, role_id: str, role_label: str,
                              candidate_data: dict, parsed_jd: dict, match_score: int,
                              score_breakdown: dict):
            """Worker: create/update match + run CrossChekk analysis in own DB session."""
            if stop_flag.is_set():
                return None
            w_db = SessionLocal()
            try:
                candidate = w_db.query(Candidate).filter(Candidate.id == candidate_id).first()
                if not candidate:
                    return {"status": "error", "error": "Candidate not found"}

                cname = candidate.github_username or candidate.name or "Unknown"

                # Ensure match exists
                match = w_db.query(Match).filter(
                    Match.candidate_id == candidate_id, Match.role_id == role_id
                ).first()
                if not match:
                    match = Match(
                        candidate_id=candidate_id, role_id=role_id,
                        match_score=match_score, score_breakdown=score_breakdown,
                    )
                    w_db.add(match)
                    w_db.flush()

                # Run CrossChekk
                if settings.DEEPSEEK_API_KEY:
                    fit_result = calculate_fit_score(settings.DEEPSEEK_API_KEY, candidate_data, parsed_jd)

                    # Replace old analysis
                    w_db.query(FitAnalysis).filter(FitAnalysis.match_id == match.id).delete()
                    w_db.flush()

                    fit_analysis = FitAnalysis(
                        candidate_id=candidate_id, role_id=role_id, match_id=match.id,
                        fit_score=int(fit_result.get('fitScore', 0)),
                        recommendation=fit_result.get('recommendation', 'SKIP'),
                        skills_matched=fit_result.get('skillsMatch', {}).get('matched', []),
                        skills_missing=fit_result.get('skillsMatch', {}).get('missing', []),
                        skills_extra=fit_result.get('skillsMatch', {}).get('extra', []),
                        candidate_level=fit_result.get('experienceMatch', {}).get('candidateLevel'),
                        required_level=fit_result.get('experienceMatch', {}).get('requiredLevel'),
                        experience_meets=1 if fit_result.get('experienceMatch', {}).get('meets') else 0,
                        strengths=fit_result.get('strengthsForRole', []),
                        concerns=fit_result.get('concernsForRole', []),
                        ai_summary=fit_result.get('aiSummary'),
                        ai_summary_short=fit_result.get('aiSummaryShort'),
                        full_analysis=fit_result,
                    )
                    w_db.add(fit_analysis)

                    match.match_score = int(fit_result.get('fitScore', 0))
                    match.score_breakdown = {
                        **score_breakdown,
                        'crosschekk_score': int(fit_result.get('fitScore', 0)),
                        'recommendation': fit_result.get('recommendation'),
                    }
                    w_db.commit()

                    return {
                        "status": "done", "cname": cname, "role_label": role_label,
                        "score": int(fit_result.get('fitScore', 0)),
                        "rec": fit_result.get('recommendation', 'SKIP'),
                    }
                else:
                    match.match_score = match_score
                    match.score_breakdown = score_breakdown
                    w_db.commit()
                    return {"status": "done", "cname": cname, "role_label": role_label, "score": match_score, "rec": "N/A"}

            except Exception as e:
                try:
                    w_db.rollback()
                except Exception:
                    pass
                return {"status": "error", "cname": candidate_data.get('name', '?'), "role_label": role_label, "error": str(e)[:100]}
            finally:
                w_db.close()

        try:
            coord_job = coord_db.query(IJModel).filter(IJModel.id == job_id).first()
            coord_add_log(coord_job, f"Starting match generation for {len(roles_copy)} roles with {PARALLEL_WORKERS} parallel workers")
            coord_db.commit()

            # Phase 1: Generate candidate lists for all roles (fast, sequential)
            work_items = []  # (candidate_id, role_id, role_label, candidate_data, parsed_jd, match_score, score_breakdown)
            prep_db = SessionLocal()
            try:
                for i, rinfo in enumerate(roles_copy):
                    role = prep_db.query(Role).filter(Role.id == rinfo['role_id']).first()
                    if not role:
                        coord_add_log(coord_job, f"  Role not found: {rinfo['role_id']}")
                        continue

                    role_label = f"{rinfo['company_name']} — {rinfo['title']}"
                    coord_add_log(coord_job, f"[{i+1}/{len(roles_copy)}] Finding candidates for {role_label}...")
                    coord_job.current_search = f"Preparing: {role_label}"
                    coord_db.commit()

                    matches_data = generate_matches_for_role(
                        prep_db, rinfo['role_id'], rinfo['count'],
                        filters=rinfo['filters'] if rinfo['filters'] else None,
                    )
                    parsed_jd = parse_jd(role.jd_text or "", role.title)

                    for md in matches_data:
                        candidate = prep_db.query(Candidate).filter(Candidate.id == md['candidate_id']).first()
                        if not candidate:
                            continue

                        # Build candidate data for CrossChekk (same as create_matches_for_role)
                        vibe_report = candidate.vibe_report or {}
                        tech_stack = candidate.tech_stack or []
                        if not tech_stack and vibe_report.get('verified_skills'):
                            tech_stack = [s.get('name') for s in vibe_report.get('verified_skills', []) if s.get('name')]
                        if not tech_stack and candidate.github_languages:
                            tech_stack = candidate.github_languages

                        candidate_data = {
                            "name": candidate.name or candidate.github_username,
                            "github_username": candidate.github_username,
                            "github_url": candidate.github_url,
                            "yoe": candidate.yoe or 3,
                            "tech_stack": tech_stack,
                            "archetype": candidate.archetype,
                            "tier": candidate.tier,
                            "tier_badge": candidate.tier_badge,
                            "tier_percentile": candidate.tier_percentile,
                            "location": candidate.location_raw,
                            "current_role": candidate.current_role,
                            "current_company": candidate.current_company,
                            "notes": getattr(candidate, 'notes', '') or '',
                            "resume_text": getattr(candidate, 'resume_text', '') or '',
                            "linkedin_text": getattr(candidate, 'linkedin_text', '') or '',
                            "github_metrics": {
                                "followers": candidate.github_followers,
                                "public_repos": candidate.github_public_repos,
                                "commits_30d": candidate.github_commits_30d,
                                "commits_90d": candidate.github_commits_90d,
                                "total_commits": candidate.github_total_commits,
                                "original_repos": candidate.github_original_repos,
                                "total_stars": candidate.github_total_stars,
                                "languages": candidate.github_languages or [],
                            },
                            "vibe_report": vibe_report,
                        }

                        work_items.append((
                            str(candidate.id), rinfo['role_id'], role_label,
                            candidate_data, parsed_jd,
                            md['score'], md['breakdown'],
                        ))

                    coord_add_log(coord_job, f"  {role_label}: {len(matches_data)} candidates queued")
                    coord_db.commit()
            finally:
                prep_db.close()

            total_work = len(work_items)
            coord_job.total_candidates = total_work
            coord_job.total_batches = len(roles_copy)
            coord_add_log(coord_job, f"Queued {total_work} analyses across {len(roles_copy)} roles — starting parallel analysis")
            coord_db.commit()

            # Phase 2: Run CrossChekk analyses in parallel
            with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
                future_to_info = {}
                for cid, rid, rlabel, cdata, pjd, mscore, sbd in work_items:
                    fut = pool.submit(analyze_one_match, cid, rid, rlabel, cdata, pjd, mscore, sbd)
                    future_to_info[fut] = (cid, rlabel)

                for future in as_completed(future_to_info):
                    if stop_flag.is_set():
                        break

                    cid, rlabel = future_to_info[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"status": "error", "cname": "?", "role_label": rlabel, "error": str(exc)[:100]}

                    if result is None:
                        continue

                    with job_lock:
                        if (counters["done"] + counters["errors"]) % 10 == 0:
                            if check_stopped(coord_job):
                                break

                        if result["status"] == "done":
                            counters["done"] += 1
                            coord_add_log(coord_job, f"  {result.get('cname', '?')} × {result['role_label']}: {result.get('score', '?')} ({result.get('rec', '')})")
                        else:
                            counters["errors"] += 1
                            coord_add_log(coord_job, f"  ERROR {result.get('cname', '?')} × {result['role_label']}: {result.get('error', '')[:80]}")

                        coord_job.current_search = f"{result.get('cname', '?')}: {result['role_label']}"
                        coord_flush(coord_job)

            # Complete
            coord_db.refresh(coord_job)
            if coord_job.status != JS.stopped:
                coord_job.status = JS.completed
                coord_job.completed_at = datetime.utcnow()
                coord_add_log(coord_job, f"Done: {counters['done']} analyzed, {counters['errors']} errors across {len(roles_copy)} roles")
                coord_db.commit()

        except Exception as e:
            try:
                coord_job.status = JS.failed
                coord_job.completed_at = datetime.utcnow()
                coord_job.error_message = str(e)[:500]
                coord_db.commit()
            except Exception:
                pass
        finally:
            coord_db.close()

    thread = threading.Thread(target=run_match_generation_background, daemon=True)
    thread.start()

    return {
        "success": True,
        "job_id": job_id,
        "roles_count": len(roles_info),
    }


# ===========================
# MATCH BUILDER TEMPLATES
# ===========================

@router.get("/match-templates/", tags=["match-templates"])
def list_match_templates(db: Session = Depends(get_db)):
    """List all saved match builder templates"""
    from app.models.match_template import MatchTemplate
    templates = db.query(MatchTemplate).order_by(MatchTemplate.updated_at.desc()).all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "segments": t.segments,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in templates
    ]


@router.post("/match-templates/", tags=["match-templates"])
def create_match_template(
    data: dict,
    db: Session = Depends(get_db),
):
    """Create or update a match builder template (upsert by name)"""
    from app.models.match_template import MatchTemplate

    name = data.get("name", "").strip()
    segments = data.get("segments", [])
    if not name:
        raise HTTPException(status_code=400, detail="Template name is required")

    existing = db.query(MatchTemplate).filter(MatchTemplate.name == name).first()
    if existing:
        existing.segments = segments
        from datetime import datetime
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        template = existing
    else:
        template = MatchTemplate(name=name, segments=segments)
        db.add(template)
        db.commit()
        db.refresh(template)

    return {
        "id": str(template.id),
        "name": template.name,
        "segments": template.segments,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
    }


@router.delete("/match-templates/{template_id}", tags=["match-templates"])
def delete_match_template(template_id: UUID, db: Session = Depends(get_db)):
    """Delete a match builder template"""
    from app.models.match_template import MatchTemplate

    template = db.query(MatchTemplate).filter(MatchTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"message": "Template deleted"}


# ===========================
# Compose Draft Routes
# ===========================

@router.get("/compose-drafts/latest", tags=["compose-drafts"])
def get_latest_compose_draft(db: Session = Depends(get_db)):
    """Get the latest non-expired compose draft batch."""
    from app.models.compose_draft import ComposeDraft

    # Clean up expired drafts
    db.query(ComposeDraft).filter(ComposeDraft.expires_at < datetime.utcnow()).delete()
    db.commit()

    draft = db.query(ComposeDraft).order_by(ComposeDraft.created_at.desc()).first()
    if not draft:
        return {"draft": None}

    return {
        "draft": {
            "id": str(draft.id),
            "template": draft.template,
            "emails": draft.emails,
            "created_at": draft.created_at.isoformat() if draft.created_at else None,
            "expires_at": draft.expires_at.isoformat() if draft.expires_at else None,
        }
    }


@router.post("/compose-drafts/", tags=["compose-drafts"])
def save_compose_draft(
    data: dict,
    db: Session = Depends(get_db),
):
    """Save a compose draft batch. Replaces any existing draft."""
    from app.models.compose_draft import ComposeDraft
    from datetime import timedelta

    template = data.get("template", "")
    emails = data.get("emails", [])

    if not emails:
        raise HTTPException(status_code=400, detail="No emails to save")

    # Delete all existing drafts (only keep one active batch)
    db.query(ComposeDraft).delete()

    draft = ComposeDraft(
        template=template,
        emails=emails,
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    return {
        "id": str(draft.id),
        "template": draft.template,
        "emails": draft.emails,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "expires_at": draft.expires_at.isoformat() if draft.expires_at else None,
    }


@router.delete("/compose-drafts/", tags=["compose-drafts"])
def delete_compose_drafts(db: Session = Depends(get_db)):
    """Delete all compose drafts (after sending)."""
    from app.models.compose_draft import ComposeDraft
    deleted = db.query(ComposeDraft).delete()
    db.commit()
    return {"deleted": deleted}


# GitHub Ingestion Routes
@router.post("/ingestion/github/user/{username}", tags=["ingestion"])
def ingest_github_user(username: str, db: Session = Depends(get_db)):
    """Ingest a single GitHub user as a candidate"""
    from app.services.github_ingestion import ingest_candidate
    from app.schemas.candidate import CandidateCreate

    try:
        # Check if already exists
        existing = crud.get_candidate_by_github_username(db, username)
        if existing:
            return {
                "message": "Candidate already exists",
                "candidate_id": existing.id
            }

        # Ingest candidate
        candidate_data = ingest_candidate(username)

        # Check if candidate was filtered by hard filters
        # For manual adds, still create the candidate with basic GitHub data
        if candidate_data.get('filtered'):
            filter_reason = candidate_data.get('reason', 'unknown')
            logger.info("%s was filtered (%s) - fetching basic data for manual add", username, filter_reason)

            from app.services.github_ingestion import (
                get_user_details, get_user_repos, get_user_activity,
                get_recent_contributions, check_profile_readme,
                parse_location, calculate_location_fit,
            )
            from app.services.behavior_scoring import calculate_behavior_score

            # Fetch basic GitHub profile data
            basic_data = get_user_details(username)
            if not basic_data or basic_data.get('filtered'):
                raise HTTPException(status_code=400, detail=f"GitHub user '{username}' not found or is a bot/org account")

            # Get repos for tech stack
            repo_data = get_user_repos(username, max_repos=50)
            basic_data.update(repo_data)

            # Get activity data (commits, last active)
            try:
                activity_data = get_user_activity(username)
                basic_data.update(activity_data)
            except Exception as e:
                logger.warning("Failed to get activity for %s: %s", username, e)

            # Get contribution history
            try:
                current_yr, prev_yr = get_recent_contributions(username)
                basic_data['github_current_year_commits'] = current_yr
                basic_data['github_previous_year_commits'] = prev_yr
                basic_data['github_total_commits'] = current_yr + prev_yr
            except Exception as e:
                logger.warning("Failed to get contributions for %s: %s", username, e)

            # Check profile README
            try:
                readme_data = check_profile_readme(username)
                basic_data.update(readme_data)
            except Exception as e:
                logger.warning("Failed to get README for %s: %s", username, e)

            # Derive fields
            basic_data['location_country'] = parse_location(basic_data.get('location_raw'))
            basic_data['location_fit'] = calculate_location_fit(basic_data['location_country'])
            basic_data['tech_stack'] = basic_data.get('github_languages', [])

            # Use commit email as fallback if no profile email
            if not basic_data.get('email') and basic_data.get('commit_email'):
                basic_data['email'] = basic_data['commit_email']

            # Calculate behavior score
            try:
                behavior_score, behavior_tier, breakdown = calculate_behavior_score(basic_data)
                basic_data['behavior_score'] = behavior_score
                basic_data['behavior_tier'] = behavior_tier
                basic_data['score_breakdown'] = {'behavior': breakdown}
            except Exception as e:
                logger.warning("Failed to calculate behavior score for %s: %s", username, e)

            basic_data['status'] = 'new'
            basic_data['source'] = 'manual'
            candidate_data = basic_data

        # Log behavior score for debugging
        behavior_score = candidate_data.get('behavior_score', 0)
        behavior_tier = candidate_data.get('behavior_tier', 'unknown')
        logger.info("%s - Behavior Score: %s, Tier: %s", username, behavior_score, behavior_tier)

        # Create candidate (removed threshold check - accept all candidates)
        try:
            candidate = CandidateCreate(**candidate_data)
            logger.info("Pydantic validation passed for %s", username)
        except Exception as schema_error:
            logger.error("Schema validation failed: %s", schema_error)
            logger.error("Data keys: %s", list(candidate_data.keys()))
            raise

        try:
            created = crud.create_candidate(db, candidate)
            logger.info("Database record created for %s", username)
        except Exception as db_error:
            logger.error("Database creation failed: %s", db_error)
            raise

        # Auto-enrich LinkedIn if email exists and no LinkedIn URL
        enrichment_info = None
        if created.email and not created.linkedin_url:
            from app.core.config import settings
            from app.services.pdl_enrichment import enrich_by_email
            from app.services.exa_search import enrich_with_linkedin_fallback
            from app.schemas.candidate import CandidateUpdate

            try:
                # Try PDL first
                if settings.PDL_API_KEY:
                    pdl_result = enrich_by_email(settings.PDL_API_KEY, created.email)
                    if pdl_result.get('success') and pdl_result.get('linkedin_url'):
                        update_data = {'linkedin_url': pdl_result.get('linkedin_url')}
                        crud.update_candidate(db, created.id, CandidateUpdate(**update_data))
                        enrichment_info = {"method": "pdl", "linkedin_url": pdl_result.get('linkedin_url')}

                # Fallback to Exa if PDL failed
                if not enrichment_info and settings.EXA_API_KEY:
                    exa_result = enrich_with_linkedin_fallback(
                        settings.EXA_API_KEY,
                        name=created.name or "Unknown",
                        email=created.email,
                        company=created.current_company,
                        title=created.current_role,
                        location=created.location_country
                    )
                    if exa_result.get('success') and exa_result.get('linkedin_url'):
                        update_data = {'linkedin_url': exa_result.get('linkedin_url')}
                        crud.update_candidate(db, created.id, CandidateUpdate(**update_data))
                        enrichment_info = {"method": "exa", "linkedin_url": exa_result.get('linkedin_url')}

            except Exception as enrich_error:
                logger.warning("LinkedIn enrichment failed: %s", enrich_error)
                # Don't fail the whole ingestion if enrichment fails

        return {
            "message": "Candidate ingested successfully",
            "candidate_id": created.id,
            "fit_score": created.fit_score,
            "linkedin_enrichment": enrichment_info
        }
    except Exception as e:
        logger.error("Failed to ingest %s: %s", username, e)
        import traceback
        traceback.print_exc()

        # Handle duplicate key violation with user-friendly message
        error_str = str(e)
        if "duplicate key" in error_str.lower() or "unique constraint" in error_str.lower():
            # Try to get the existing candidate
            existing = crud.get_candidate_by_github_username(db, username)
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Candidate @{username} already exists in the system. Try searching for them in the candidate list."
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"A candidate with username '{username}' already exists."
                )

        raise HTTPException(status_code=500, detail=f"Failed to ingest user: {str(e)}")


@router.get("/ingestion/status", tags=["ingestion"])
def get_ingestion_status(db: Session = Depends(get_db)):
    """
    Get the current status of GitHub ingestion.

    Returns the most recent ingestion status, including progress and stats.
    Automatically marks stale "running" statuses as "failed" if they've been running for >30 minutes.
    """
    from app.models.ingestion_status import IngestionStatus
    from datetime import timedelta

    # Force fresh data from database (don't use SQLAlchemy cache)
    db.expire_all()

    # Get the most recent status
    status = db.query(IngestionStatus).order_by(IngestionStatus.created_at.desc()).first()

    if not status:
        return {
            "status": "idle",
            "message": "No recent ingestion activity"
        }

    # Refresh to ensure we have latest data from DB
    db.refresh(status)

    # Check for stale "running" status (no updates for 2 minutes = stream is dead)
    if status.status == 'running' and status.updated_at:
        time_since_update = datetime.utcnow() - status.updated_at
        if time_since_update > timedelta(minutes=2):
            # Mark as failed - stream is dead (no updates for 2+ minutes)
            status.status = 'failed'
            status.completed_at = datetime.utcnow()
            status.error_message = 'Stream disconnected (no updates for 2+ minutes)'
            db.commit()

    result = {
        "id": str(status.id),
        "status": status.status,
        "started_at": status.started_at.isoformat() if status.started_at else None,
        "completed_at": status.completed_at.isoformat() if status.completed_at else None,
        "current_search": status.current_search,
        "searches_completed": status.searches_completed,
        "searches_total": status.searches_total,
        "candidates_processed": status.candidates_processed,
        "candidates_saved": status.candidates_saved,
        "candidates_skipped": status.candidates_skipped,
        "stats": status.stats,
        "recent_logs": status.recent_logs or [],
        "error_message": status.error_message,
        "error_count": status.error_count,
        "updated_at": status.updated_at.isoformat() if status.updated_at else None,
    }
    logger.debug("Returning %d logs, searches: %d/%d", len(result['recent_logs']), status.searches_completed, status.searches_total)
    return result


@router.post("/ingestion/stop", tags=["ingestion"])
def stop_ingestion(db: Session = Depends(get_db)):
    """
    Stop the currently running GitHub ingestion.

    Marks the status as 'stopped' immediately - works even if stream is dead.
    """
    from app.models.ingestion_status import IngestionStatus

    # Get the most recent running status
    status = db.query(IngestionStatus)\
        .filter(IngestionStatus.status == 'running')\
        .order_by(IngestionStatus.created_at.desc())\
        .first()

    if not status:
        return {
            "success": False,
            "message": "No active ingestion process found"
        }

    # Immediately mark as stopped (don't just set flag - actually stop it)
    status.status = 'stopped'
    status.stop_requested = True
    status.completed_at = datetime.utcnow()
    status.updated_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "message": "Ingestion process stopped",
        "status_id": str(status.id)
    }


@router.post("/ingestion/start", tags=["ingestion"])
def start_ingestion(
    min_behavior_score: int = 30,  # Lowered from 40 to catch more mid-career + hireable candidates
    target_count: int = 500,
    db: Session = Depends(get_db)
):
    """
    Create a new ingestion job that will be processed by the worker.

    This endpoint creates a job record and returns immediately.
    A separate worker process polls for pending jobs and processes them in batches
    with checkpointing support (survives crashes and can resume).

    Use GET /ingestion/job/status/{job_id} to poll for progress updates.

    Args:
        min_behavior_score: Minimum behavior score threshold (default: 30, lowered to catch more mid-career + hireable candidates)
        target_count: Not used (deprecated, all candidates are evaluated)

    Returns:
        Job ID for tracking progress
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    import uuid

    # Check if there's already a pending or running job
    existing = db.query(IngestionJob)\
        .filter(IngestionJob.status.in_([JobStatus.pending, JobStatus.running]))\
        .order_by(IngestionJob.created_at.desc())\
        .first()

    if existing:
        return {
            "success": False,
            "message": f"A sourcing job is already {existing.status.value}",
            "job_id": str(existing.id),
            "status": existing.status.value
        }

    # Create new job record
    job = IngestionJob(
        id=uuid.uuid4(),
        status=JobStatus.pending,
        job_type='ingestion',
        min_behavior_score=min_behavior_score,
        recent_logs=[],
        stats={}
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info("Created job %s - worker will pick it up", job.id)

    return {
        "success": True,
        "message": "Ingestion job created. Worker will process it shortly.",
        "job_id": str(job.id),
        "status": job.status.value
    }


@router.post("/sourcing/github/targeted", tags=["sourcing"])
def start_targeted_github_sourcing(payload: dict, db: Session = Depends(get_db)):
    """
    Start a targeted GitHub sourcing job for a specific role.

    Searches GitHub for candidates matching the given languages/locations,
    ingests them, and auto-matches against the role.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    from app.services.github_ingestion import targeted_github_sourcing_background
    from app.db.base import SessionLocal
    import uuid

    from app.models.role import Role

    role_id = payload.get("role_id")
    if not role_id:
        raise HTTPException(status_code=400, detail="role_id is required")

    # Look up role for title/tech_stack (used for differentiated search)
    role = db.query(Role).filter(Role.id == UUID(role_id)).first()
    role_title = role.title if role else ""
    role_tech_stack = role.tech_stack or [] if role else []
    role_jd_text = role.jd_text or "" if role else ""

    languages = payload.get("languages", ["python", "typescript"])
    locations = payload.get("locations", ["United States OR USA"])
    count = payload.get("count", 50)
    min_repos = payload.get("min_repos", 5)
    hireable_only = payload.get("hireable_only", False)
    strategy = payload.get("strategy", "both")  # 'both', 'user_search', 'repo_discovery'

    # Create job record
    job = IngestionJob(
        id=uuid.uuid4(),
        status=JobStatus.pending,
        job_type='targeted_sourcing',
        role_id=UUID(role_id) if role_id else None,
        min_behavior_score=30,
        recent_logs=[],
        stats={},
        checkpoint_data={"role_id": role_id, "languages": languages, "locations": locations, "strategy": strategy},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Spawn background thread with its own DB session
    def run_in_background():
        bg_db = SessionLocal()
        try:
            targeted_github_sourcing_background(
                db=bg_db,
                job_id=str(job.id),
                role_id=role_id,
                languages=languages,
                locations=locations,
                count=count,
                min_repos=min_repos,
                hireable_only=hireable_only,
                role_title=role_title,
                tech_stack=role_tech_stack,
                jd_text=role_jd_text,
                strategy=strategy,
            )
        finally:
            bg_db.close()

    import threading
    t = threading.Thread(target=run_in_background, daemon=True)
    t.start()

    return {
        "success": True,
        "job_id": str(job.id),
        "message": f"Targeted sourcing started: {len(languages)} languages x {len(locations)} locations",
    }


@router.post("/sourcing/github/bulk-targeted", tags=["sourcing"])
def start_bulk_targeted_github_sourcing(payload: dict, db: Session = Depends(get_db)):
    """
    Start bulk targeted GitHub sourcing across multiple roles.

    Processes roles sequentially (sharing the GitHub token pool), but each role
    uses parallel workers internally (12 for eval, 5 for matching).
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    from app.services.github_ingestion import (
        bulk_targeted_github_sourcing_background,
        derive_languages_from_tech_stack,
        derive_locations_from_role,
    )
    from app.models.role import Role
    from app.db.base import SessionLocal
    import uuid

    role_ids = payload.get("role_ids", [])
    if not role_ids:
        raise HTTPException(status_code=400, detail="role_ids is required")

    count_per_role = payload.get("count_per_role", 50)
    min_repos = payload.get("min_repos", 5)
    strategy = payload.get("strategy", "both")  # 'both', 'user_search', 'repo_discovery'

    # Check for already-running bulk sourcing job
    existing = db.query(IngestionJob).filter(
        IngestionJob.job_type == 'bulk_targeted_sourcing',
        IngestionJob.status.in_([JobStatus.pending, JobStatus.running]),
    ).first()
    if existing:
        return {
            "success": False,
            "job_id": str(existing.id),
            "message": "A bulk sourcing job is already running",
        }

    # Build per-role configs: auto-derive languages + locations from role data
    role_configs = []
    for rid in role_ids:
        role = db.query(Role).filter(Role.id == UUID(rid)).first()
        if not role:
            continue

        tech_stack = role.tech_stack or []
        languages = derive_languages_from_tech_stack(tech_stack, role_title=role.title)
        locations = derive_locations_from_role(role)

        role_configs.append({
            "role_id": rid,
            "languages": languages,
            "locations": locations,
            "title": f"{role.company_name} - {role.title}",
            "role_title": role.title,
            "tech_stack": tech_stack,
            "jd_text": role.jd_text or "",
        })

    if not role_configs:
        raise HTTPException(status_code=400, detail="No valid roles found")

    # Create parent job
    job = IngestionJob(
        id=uuid.uuid4(),
        status=JobStatus.pending,
        job_type='bulk_targeted_sourcing',
        total_batches=len(role_configs),
        min_behavior_score=30,
        recent_logs=[],
        stats={},
        checkpoint_data={
            "role_ids": role_ids,
            "count_per_role": count_per_role,
            "role_configs": role_configs,
            "strategy": strategy,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Spawn background thread with its own DB session
    def run_in_background():
        bg_db = SessionLocal()
        try:
            bulk_targeted_github_sourcing_background(
                db=bg_db,
                job_id=str(job.id),
                role_configs=role_configs,
                count_per_role=count_per_role,
                min_repos=min_repos,
                db_factory=SessionLocal,
                strategy=strategy,
            )
        finally:
            bg_db.close()

    import threading
    t = threading.Thread(target=run_in_background, daemon=True, name=f"bulk-sourcing-{job.id}")
    t.start()

    return {
        "success": True,
        "job_id": str(job.id),
        "roles_count": len(role_configs),
        "message": f"Bulk sourcing started for {len(role_configs)} roles ({count_per_role} per role)",
    }


def _get_bulk_sourcing_sub_jobs(db: Session, parent_job) -> list:
    """Fetch sub-job progress for a bulk_targeted_sourcing parent job."""
    from app.models.ingestion_job import IngestionJob
    checkpoint = parent_job.checkpoint_data or {}
    sub_job_info = checkpoint.get('sub_jobs', [])
    if not sub_job_info:
        return []

    result = []
    for entry in sub_job_info:
        sub = db.query(IngestionJob).filter(
            IngestionJob.id == entry['job_id']
        ).first()
        if not sub:
            result.append({
                'job_id': entry['job_id'],
                'role_id': entry.get('role_id'),
                'title': entry.get('title', '?'),
                'status': 'pending',
            })
            continue

        sub_stats = sub.stats or {}
        # Determine phase — order matters: check evaluation/matching before searching
        # because searches_completed may lag behind actual progress
        if sub.status.value in ('pending',):
            phase = 'pending'
        elif sub.status.value == 'completed':
            phase = 'done'
        elif sub.status.value == 'failed':
            phase = 'failed'
        elif sub.status.value == 'stopped':
            phase = 'stopped'
        elif sub_stats.get('matching_current') is not None and sub_stats.get('matching_current', 0) > 0:
            phase = 'matching'
        elif (sub.processed_count or 0) > 0 or (sub.total_candidates or 0) > 0:
            phase = 'evaluating'
        elif sub.searches_completed and sub.searches_completed < (sub.searches_total or 1):
            phase = 'searching'
        else:
            phase = 'evaluating'

        result.append({
            'job_id': entry['job_id'],
            'role_id': entry.get('role_id'),
            'title': entry.get('title', '?'),
            'status': sub.status.value,
            'phase': phase,
            'searches_done': sub.searches_completed or 0,
            'searches_total': sub.searches_total or 0,
            'candidates_found': sub.total_candidates or 0,
            'evaluated': sub.processed_count or 0,
            'saved': sub.candidates_saved or 0,
            'errors': sub.error_count or 0,
            'matching_current': sub_stats.get('matching_current', 0),
            'matching_total': sub_stats.get('matching_total', 0),
            'matches_created': sub_stats.get('matches_created', 0),
            'current_search': sub.current_search,
        })
    return result


@router.get("/ingestion/job/status/{job_id}", tags=["ingestion"])
def get_job_status(job_id: UUID, db: Session = Depends(get_db)):
    """
    Get the current status of an ingestion job.

    Returns progress, stats, and recent logs for the job.
    """
    from app.models.ingestion_job import IngestionJob

    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Refresh to ensure we have latest data
    db.refresh(job)

    # Helper to safely get integer values
    def safe_int(val):
        return val if val is not None else 0

    total = safe_int(job.total_candidates)
    processed = safe_int(job.processed_count)

    return {
        "id": str(job.id),
        "status": job.status.value,
        "job_type": job.job_type,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,

        # Progress
        "total_candidates": total,
        "processed_count": processed,
        "current_batch": safe_int(job.current_batch),
        "total_batches": safe_int(job.total_batches),
        "progress_percentage": round((processed / total * 100), 1) if total > 0 else 0,

        # Search progress
        "current_search": job.current_search,
        "searches_completed": safe_int(job.searches_completed),
        "searches_total": safe_int(job.searches_total),

        # Stats
        "candidates_saved": safe_int(job.candidates_saved),
        "candidates_skipped": safe_int(job.candidates_skipped),
        "error_count": safe_int(job.error_count),
        "stats": job.stats or {},

        # Logs and errors
        "recent_logs": job.recent_logs or [],
        "error_message": job.error_message,

        # Config
        "min_behavior_score": safe_int(job.min_behavior_score) or 30,

        # Include checkpoint_data for job types that store results there
        **({"checkpoint_data": job.checkpoint_data} if job.job_type in ('crosschekk', 'starred_outreach') and job.checkpoint_data else {}),

        # For bulk targeted sourcing, include per-role sub-job progress
        **({"sub_jobs": _get_bulk_sourcing_sub_jobs(db, job)} if job.job_type == 'bulk_targeted_sourcing' and job.checkpoint_data else {}),
    }


@router.get("/ingestion/job/active-for-role/{role_id}", tags=["ingestion"])
def get_active_job_for_role(role_id: UUID, db: Session = Depends(get_db)):
    """
    Check if there's an active (running/pending) job for a specific role.

    Returns the job info if found, or {active: false} if no active job.
    Used by the frontend to resume polling after page refresh.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus

    job = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.role_id == role_id,
            IngestionJob.status.in_([JobStatus.running, JobStatus.pending]),
        )
        .order_by(IngestionJob.created_at.desc())
        .first()
    )

    if not job:
        return {"active": False}

    return {
        "active": True,
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status.value,
        "total_candidates": job.total_candidates or 0,
        "processed_count": job.processed_count or 0,
    }


@router.get("/ingestion/jobs/active-sourcing", tags=["ingestion"])
def get_active_sourcing_jobs(db: Session = Depends(get_db)):
    """
    Get ALL active sourcing jobs (both individual targeted_sourcing and bulk_targeted_sourcing).

    Used by the global Role Queue to display progress for all running sourcing jobs,
    regardless of whether they were started from a role page or from bulk sourcing.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus

    jobs = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.job_type.in_(['targeted_sourcing', 'bulk_targeted_sourcing']),
            IngestionJob.status.in_([JobStatus.running, JobStatus.pending]),
        )
        .order_by(IngestionJob.created_at.desc())
        .all()
    )

    result = []
    for job in jobs:
        db.refresh(job)
        job_data = {
            "id": str(job.id),
            "job_type": job.job_type,
            "status": job.status.value,
            "role_id": str(job.role_id) if job.role_id else None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "total_candidates": job.total_candidates or 0,
            "processed_count": job.processed_count or 0,
            "candidates_saved": job.candidates_saved or 0,
            "current_search": job.current_search,
            "searches_completed": job.searches_completed or 0,
            "searches_total": job.searches_total or 0,
            "current_batch": job.current_batch or 0,
            "total_batches": job.total_batches or 0,
            "stats": job.stats or {},
            "recent_logs": (job.recent_logs or [])[-5:],  # Last 5 logs only for summary
        }

        # For bulk jobs, include sub-job summary
        if job.job_type == 'bulk_targeted_sourcing' and job.checkpoint_data:
            job_data["sub_jobs"] = _get_bulk_sourcing_sub_jobs(db, job)

        result.append(job_data)

    return {"jobs": result, "count": len(result)}


@router.get("/ingestion/job/latest", tags=["ingestion"])
def get_latest_job(db: Session = Depends(get_db)):
    """
    Get the most recent ingestion job.

    Returns the latest job (pending, running, or completed) for the UI to track.
    """
    from app.models.ingestion_job import IngestionJob

    # Get most recent job
    job = db.query(IngestionJob).order_by(IngestionJob.created_at.desc()).first()

    if not job:
        return {
            "status": "idle",
            "message": "No ingestion jobs found"
        }

    # Refresh to ensure we have latest data
    db.refresh(job)

    # Helper to safely get integer values
    def safe_int(val):
        return val if val is not None else 0

    total = safe_int(job.total_candidates)
    processed = safe_int(job.processed_count)

    return {
        "id": str(job.id),
        "status": job.status.value,
        "job_type": job.job_type,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,

        # Progress
        "total_candidates": total,
        "processed_count": processed,
        "current_batch": safe_int(job.current_batch),
        "total_batches": safe_int(job.total_batches),
        "progress_percentage": round((processed / total * 100), 1) if total > 0 else 0,

        # Search progress
        "current_search": job.current_search,
        "searches_completed": safe_int(job.searches_completed),
        "searches_total": safe_int(job.searches_total),

        # Stats
        "candidates_saved": safe_int(job.candidates_saved),
        "candidates_skipped": safe_int(job.candidates_skipped),
        "error_count": safe_int(job.error_count),
        "stats": job.stats or {},

        # Logs and errors
        "recent_logs": job.recent_logs or [],
        "error_message": job.error_message,

        # Config
        "min_behavior_score": safe_int(job.min_behavior_score) or 30,
    }


@router.get("/ingestion/github/nightly/stream", tags=["ingestion"])
def run_nightly_ingestion_stream(
    min_behavior_score: int = 30,  # Lowered from 40 to catch more mid-career + hireable candidates
    target_count: int = 500,
    db: Session = Depends(get_db)
):
    """
    Run manual GitHub sourcing with Server-Sent Events (SSE) streaming.

    Returns real-time progress updates as candidates are searched, evaluated, and saved.
    """
    from fastapi.responses import StreamingResponse
    from app.services.github_ingestion import nightly_github_ingestion_stream
    from app.models.ingestion_status import IngestionStatus

    # Clean up any stale "running" statuses before starting new one
    stale_statuses = db.query(IngestionStatus).filter(IngestionStatus.status == 'running').all()
    for stale in stale_statuses:
        stale.status = 'failed'
        stale.completed_at = datetime.utcnow()
        stale.error_message = 'Process interrupted by new search'
    db.commit()

    return StreamingResponse(
        nightly_github_ingestion_stream(
            db,
            min_behavior_score=min_behavior_score,
            target_count=target_count
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.post("/ingestion/github/nightly", tags=["ingestion"])
def run_nightly_ingestion(
    min_behavior_score: int = 30,  # Lowered from 40 to catch more mid-career + hireable candidates
    target_count: int = 500,
    db: Session = Depends(get_db)
):
    """
    Run manual GitHub sourcing (non-streaming version).

    Searches GitHub for candidates matching criteria, scores them on behavior signals
    (activity/intent/quality), and ingests only hot (>= 70) and warm (>= 30) candidates.

    Args:
        min_behavior_score: Minimum behavior score to ingest (default: 30 = warm tier)
        target_count: Max candidates to ingest per sourcing run (default: 500)

    Returns:
        Stats about the sourcing run
    """
    from app.services.github_ingestion import nightly_github_ingestion

    try:
        stats = nightly_github_ingestion(
            db,
            min_behavior_score=min_behavior_score,
            target_count=target_count
        )
        return {
            "message": "Sourcing completed",
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sourcing failed: {str(e)}")


@router.post("/candidates/{candidate_id}/enrich-linkedin", tags=["candidates", "enrichment"])
def enrich_candidate_linkedin(candidate_id: UUID, db: Session = Depends(get_db)):
    """
    Enrich candidate with LinkedIn profile using email-to-LinkedIn mapping.

    Strategy:
    1. Try People Data Labs (PDL) first
    2. If PDL fails, fallback to Exa AI semantic search
    3. Update candidate with LinkedIn URL and enriched data
    """
    from app.core.config import settings
    from app.services.pdl_enrichment import enrich_by_email
    from app.services.exa_search import enrich_with_linkedin_fallback
    from app.schemas.candidate import CandidateUpdate

    # Get candidate
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Check if candidate has email
    if not candidate.email:
        raise HTTPException(
            status_code=400,
            detail="Candidate has no email address to enrich"
        )

    # Check if already has LinkedIn
    if candidate.linkedin_url:
        return {
            "message": "Candidate already has LinkedIn URL",
            "linkedin_url": candidate.linkedin_url,
            "method": "existing"
        }

    enrichment_result = None
    method = None

    # Try PDL first
    if settings.PDL_API_KEY:
        logger.info("Trying PDL enrichment for %s", candidate.email)
        pdl_result = enrich_by_email(settings.PDL_API_KEY, candidate.email)

        if pdl_result.get('success') and pdl_result.get('linkedin_url'):
            enrichment_result = pdl_result
            method = "pdl"
            logger.info("PDL enrichment success: %s", pdl_result.get('linkedin_url'))
        else:
            logger.warning("PDL enrichment failed: %s", pdl_result.get('error'))
    else:
        logger.info("PDL API key not configured, skipping PDL enrichment")

    # Fallback to Exa if PDL failed
    if not enrichment_result and settings.EXA_API_KEY:
        logger.info("Trying Exa fallback enrichment for %s", candidate.name or candidate.email)

        exa_result = enrich_with_linkedin_fallback(
            settings.EXA_API_KEY,
            name=candidate.name or "Unknown",
            email=candidate.email,
            company=candidate.current_company,
            title=candidate.current_role,
            location=candidate.location_country
        )

        if exa_result.get('success') and exa_result.get('linkedin_url'):
            enrichment_result = exa_result
            method = "exa"
            logger.info("Exa enrichment success: %s", exa_result.get('linkedin_url'))
        else:
            logger.warning("Exa enrichment failed: %s", exa_result.get('error'))
    elif not enrichment_result:
        logger.info("Exa API key not configured, skipping Exa fallback enrichment")

    # Fallback to CaptainData if PDL and Exa both failed
    if not enrichment_result and settings.CAPTAINDATA_API_KEY:
        logger.info("Trying CaptainData fallback enrichment for %s", candidate.name or candidate.email)
        from app.services.captaindata_enrichment import enrich_linkedin_profile as cd_enrich

        # CaptainData needs a LinkedIn URL to work — try to construct one from name
        # This is a long-shot fallback; CaptainData is primarily for pulling profile data
        # from a known LinkedIn URL, but we try anyway
        candidate_name = candidate.name or ""
        if candidate_name:
            guessed_url = f"https://www.linkedin.com/in/{candidate_name.lower().replace(' ', '-')}"
            cd_result = cd_enrich(settings.CAPTAINDATA_API_KEY, guessed_url, full_enrich=False)
            if cd_result.get('success') and cd_result.get('linkedin_url'):
                enrichment_result = {
                    'success': True,
                    'linkedin_url': cd_result.get('linkedin_url'),
                    'name': cd_result.get('full_name'),
                    'title': cd_result.get('job_title'),
                    'company': cd_result.get('company_name'),
                    'location_country': cd_result.get('location'),
                }
                method = "captaindata"
                logger.info("CaptainData fallback success: %s", cd_result.get('linkedin_url'))
            else:
                logger.warning("CaptainData fallback failed: %s", cd_result.get('error'))
    elif not enrichment_result:
        logger.info("CaptainData API key not configured, skipping CaptainData fallback")

    # If all enrichment methods failed
    if not enrichment_result:
        raise HTTPException(
            status_code=404,
            detail="Could not find LinkedIn profile via PDL, Exa, or CaptainData"
        )

    # Update candidate with enriched data
    update_data = {
        'linkedin_url': enrichment_result.get('linkedin_url')
    }

    # Add other enriched fields if available (PDL provides more data)
    if method == "pdl":
        if enrichment_result.get('name') and not candidate.name:
            update_data['name'] = enrichment_result.get('name')

        if enrichment_result.get('title') and not candidate.current_role:
            update_data['current_role'] = enrichment_result.get('title')

        if enrichment_result.get('company') and not candidate.current_company:
            update_data['current_company'] = enrichment_result.get('company')

        if enrichment_result.get('location_country') and not candidate.location_country:
            update_data['location_country'] = enrichment_result.get('location_country')

    # Update candidate
    update_schema = CandidateUpdate(**update_data)
    updated_candidate = crud.update_candidate(db, candidate_id, update_schema)

    return {
        "message": "LinkedIn profile enrichment successful",
        "candidate_id": candidate_id,
        "linkedin_url": enrichment_result.get('linkedin_url'),
        "method": method,
        "enriched_fields": list(update_data.keys())
    }


@router.post("/candidates/{candidate_id}/pull-linkedin", tags=["candidates", "enrichment"])
def pull_linkedin_profile(candidate_id: UUID, db: Session = Depends(get_db)):
    """
    Pull full LinkedIn profile data using CaptainData.

    Requires the candidate to already have a linkedin_url (from PDL/Exa enrichment).
    Fetches the full profile (experiences, skills, education, headline, summary)
    and stores it in linkedin_data + updates candidate fields.
    """
    from app.core.config import settings
    from app.services.captaindata_enrichment import enrich_linkedin_profile, format_linkedin_text
    from app.schemas.candidate import CandidateUpdate

    if not settings.CAPTAINDATA_API_KEY:
        raise HTTPException(status_code=500, detail="CAPTAINDATA_API_KEY not configured")

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not candidate.linkedin_url:
        raise HTTPException(
            status_code=400,
            detail="Candidate has no LinkedIn URL. Run enrich-linkedin first."
        )

    # Call CaptainData to pull full profile
    cd_result = enrich_linkedin_profile(
        settings.CAPTAINDATA_API_KEY,
        candidate.linkedin_url,
        full_enrich=True
    )

    if not cd_result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=f"CaptainData failed: {cd_result.get('error', 'Unknown error')}"
        )

    # Format the full profile text for AI analysis
    linkedin_text = format_linkedin_text(cd_result)

    # Build update dict — only overwrite fields that are currently empty
    update_data = {}

    if linkedin_text:
        update_data["linkedin_data"] = linkedin_text

    if cd_result.get("full_name") and not candidate.name:
        update_data["name"] = cd_result["full_name"]

    if cd_result.get("job_title") and not candidate.current_role:
        update_data["current_role"] = cd_result["job_title"]

    if cd_result.get("company_name") and not candidate.current_company:
        update_data["current_company"] = cd_result["company_name"]

    if cd_result.get("location") and not candidate.location_raw:
        update_data["location_raw"] = cd_result["location"]

    # Extract tech-related skills into tech_stack if empty
    if cd_result.get("skills") and not candidate.tech_stack:
        update_data["tech_stack"] = cd_result["skills"]

    # Update the canonical linkedin_url if CaptainData returned a cleaner one
    if cd_result.get("linkedin_url") and cd_result["linkedin_url"] != candidate.linkedin_url:
        update_data["linkedin_url"] = cd_result["linkedin_url"]

    if update_data:
        update_schema = CandidateUpdate(**update_data)
        crud.update_candidate(db, candidate_id, update_schema)

    return {
        "message": "LinkedIn profile pulled successfully via CaptainData",
        "candidate_id": str(candidate_id),
        "full_name": cd_result.get("full_name"),
        "headline": cd_result.get("headline"),
        "job_title": cd_result.get("job_title"),
        "company_name": cd_result.get("company_name"),
        "location": cd_result.get("location"),
        "skills_count": len(cd_result.get("skills", [])),
        "experiences_count": len(cd_result.get("experiences", [])),
        "education_count": len(cd_result.get("education", [])),
        "updated_fields": list(update_data.keys()),
        "linkedin_data_length": len(linkedin_text) if linkedin_text else 0,
    }


# Role Sourcing Routes
@router.post("/sourcing/work-at-startup", tags=["sourcing"])
def scrape_work_at_startup(db: Session = Depends(get_db)):
    """Scrape Work at a Startup for new roles"""
    from app.services.role_sourcing import scrape_work_at_startup
    from app.schemas.role import RoleCreate

    try:
        roles_data = scrape_work_at_startup()
        saved = 0

        for role_data in roles_data:
            try:
                role = RoleCreate(**role_data)
                crud.create_role(db, role)
                saved += 1
            except Exception as e:
                logger.error("Error saving role: %s", e)

        return {
            "message": "Work at a Startup scraping completed",
            "found": len(roles_data),
            "saved": saved
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")


@router.post("/sourcing/hn-hiring", tags=["sourcing"])
def scrape_hn_hiring(db: Session = Depends(get_db)):
    """Scrape HN Who's Hiring for new roles"""
    from app.services.role_sourcing import scrape_hn_hiring
    from app.schemas.role import RoleCreate

    try:
        roles_data = scrape_hn_hiring()
        saved = 0

        for role_data in roles_data:
            try:
                role = RoleCreate(**role_data)
                crud.create_role(db, role)
                saved += 1
            except Exception as e:
                logger.error("Error saving role: %s", e)

        return {
            "message": "HN Who's Hiring scraping completed",
            "found": len(roles_data),
            "saved": saved
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")


@router.post("/sourcing/nightly", tags=["sourcing"])
def run_nightly_sourcing(db: Session = Depends(get_db)):
    """Run the nightly role sourcing job"""
    from app.services.role_sourcing import nightly_role_sourcing

    try:
        stats = nightly_role_sourcing(db)
        return {
            "message": "Nightly role sourcing completed",
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sourcing failed: {str(e)}")


# ---------- Company Page Admin ----------

@router.post("/matches/{match_id}/hide-from-company-page", tags=["matches"])
def toggle_hide_from_company_page(match_id: str, db: Session = Depends(get_db)):
    """Toggle whether a match is hidden from the public company page."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    match.hidden_from_company_page = not match.hidden_from_company_page
    db.commit()
    return {"match_id": str(match.id), "hidden_from_company_page": match.hidden_from_company_page}


class UpdateMatchNotesRequest(BaseModel):
    notes: Optional[str] = None


@router.put("/matches/{match_id}/notes", tags=["matches"])
def update_match_notes(match_id: str, request: UpdateMatchNotesRequest, db: Session = Depends(get_db)):
    """Update notes on a match (shown on candidate profile page for clients)."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    match.notes = request.notes
    db.commit()
    return {"match_id": str(match.id), "notes": match.notes}


# Public API Routes (no auth required)

@router.get("/public/company/{company_slug}", tags=["public"])
def get_company_page(company_slug: str, include_hidden: bool = False, db: Session = Depends(get_db)):
    """
    Public company page: returns all active roles for a company
    with their top starred/recommended candidates.

    Used for recruiting.chekk.dev/c/{company-slug} pages sent to hiring managers.
    """
    from sqlalchemy import func as sa_func
    from app.models.fit_analysis import FitAnalysis
    from app.models.role import RoleStatus

    # Normalize slug → company name match
    slug = company_slug.lower().replace('-', ' ').replace('_', ' ')
    roles = db.query(Role).filter(
        sa_func.lower(sa_func.replace(sa_func.replace(Role.company_name, '-', ' '), '_', ' ')).like(f'%{slug}%')
    ).filter(Role.status.notin_([RoleStatus.placed, RoleStatus.lost])).order_by(Role.position.asc().nullslast(), Role.created_at.desc()).all()

    if not roles:
        raise HTTPException(status_code=404, detail=f"No active roles found for '{company_slug}'")

    company_name = roles[0].company_name
    company_stage = roles[0].company_stage.value.replace('_', ' ') if roles[0].company_stage else None
    notable_investors = roles[0].notable_investors or []
    company_page_notes = next((r.company_page_notes for r in roles if r.company_page_notes), None)

    role_results = []
    for role in roles:
        # Get starred matches for this role
        if include_hidden:
            # Admin view: include hidden candidates too
            starred_matches = db.query(Match).filter(
                Match.role_id == role.id,
                Match.starred == True,
            ).all()
        else:
            starred_matches = db.query(Match).filter(
                Match.role_id == role.id,
                Match.starred == True,
                Match.hidden_from_company_page == False,
            ).all()

        if not starred_matches:
            # Include role even without starred candidates (shows the role exists)
            role_results.append({
                "id": str(role.id),
                "title": role.title,
                "tech_stack": role.tech_stack or [],
                "location_requirement": role.location_requirement.value if role.location_requirement else None,
                "location_cities": role.location_cities or [],
                "seniority_level": role.seniority_level,
                "candidates": [],
            })
            continue

        # Get fit analyses for starred matches
        match_ids = [m.id for m in starred_matches]
        candidate_ids = [m.candidate_id for m in starred_matches]
        match_map = {m.candidate_id: m for m in starred_matches}

        fits = db.query(FitAnalysis).filter(
            FitAnalysis.match_id.in_(match_ids)
        ).all()
        fit_map = {f.candidate_id: f for f in fits}

        candidates = db.query(Candidate).filter(Candidate.id.in_(candidate_ids)).all()

        candidate_results = []
        for c in candidates:
            match = match_map.get(c.id)
            fit = fit_map.get(c.id)

            # Determine warmth/engagement status for display
            warmth = 'new'
            if c.warmup_replied_at or c.outreach_status == 'replied':
                warmth = 'replied'
            elif c.screening_status == 'completed':
                warmth = 'screened'
            elif c.warmup_email_opened_at:
                warmth = 'opened'
            elif c.outreach_status in ('sent', 'screening_sent'):
                warmth = 'contacted'

            # Build role slug for profile link — strip anything that isn't alphanumeric or hyphen
            role_slug = re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', role.title.lower())).strip('-')

            candidate_results.append({
                "match_id": str(match.id) if match else None,
                "candidate_id": str(c.id),
                "name": c.name or c.github_username,
                "github_username": c.github_username,
                "archetype": c.archetype,
                "tier": c.tier,
                "tier_badge": c.tier_badge,
                "location": c.location_raw or c.location_country,
                "current_role": c.current_role,
                "current_company": c.current_company,
                "yoe": c.yoe,
                "tech_stack": (c.tech_stack or c.github_languages or [])[:8],
                "fit_score": fit.fit_score if fit else (match.match_score if match else None),
                "recommendation": fit.recommendation if fit else None,
                "ai_summary_short": fit.ai_summary_short if fit else None,
                "strengths": (fit.strengths or [])[:3] if fit else [],
                "warmth": warmth,
                "profile_url": f"/r/{company_slug}/{role_slug}/{c.github_username}",
                "has_screening": c.screening_status == 'completed',
                "client_vote": match.client_vote if match else None,
                "bookmarked": bool(c.bookmarked),
                "behavior_tier": c.behavior_tier,
                "hidden": bool(match.hidden_from_company_page) if match else False,
            })

        # Sort by fit_score descending
        candidate_results.sort(key=lambda x: x.get('fit_score') or 0, reverse=True)

        # For non-admin: skip roles hidden from company page that have no visible candidates
        if not include_hidden and role.hide_from_company_page and not candidate_results:
            continue

        role_results.append({
            "id": str(role.id),
            "title": role.title,
            "tech_stack": role.tech_stack or [],
            "location_requirement": role.location_requirement.value if role.location_requirement else None,
            "location_cities": role.location_cities or [],
            "seniority_level": role.seniority_level,
            "candidates": candidate_results,
            "hide_from_company_page": bool(role.hide_from_company_page),
        })

    return {
        "success": True,
        "company_name": company_name,
        "company_stage": company_stage,
        "notable_investors": notable_investors,
        "role_count": len(role_results),
        "total_candidates": len({c["candidate_id"] for r in role_results for c in r["candidates"]}),
        "roles": role_results,
        "notes": company_page_notes,
    }


@router.post("/public/company/vote/{match_id}", tags=["public"])
def vote_on_candidate(match_id: str, vote: str, db: Session = Depends(get_db)):
    """
    Public endpoint for hiring managers to thumbs-up or thumbs-down a candidate.
    vote: 'up', 'down', or 'none' (to clear)
    """
    if vote not in ('up', 'down', 'none'):
        raise HTTPException(status_code=400, detail="vote must be 'up', 'down', or 'none'")
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    match.client_vote = vote if vote != 'none' else None
    db.commit()
    return {"match_id": str(match.id), "client_vote": match.client_vote}


@router.get("/public/company/search-candidates", tags=["public"])
def search_candidates_for_company_page(q: str, role_id: str, db: Session = Depends(get_db)):
    """Search candidates by name to add/show on the company page.

    Prioritizes existing matches for the role that aren't currently visible
    (not starred or hidden), then includes unmatched candidates as a secondary pool.
    """
    from sqlalchemy import func as sa_func
    if not q or len(q) < 2:
        return {"candidates": []}

    q_lower = q.lower()

    # 1) Search existing matches for this role where candidate name matches
    #    and the match is NOT already starred+visible on the company page
    existing_matches = (
        db.query(Match, Candidate)
        .join(Candidate, Match.candidate_id == Candidate.id)
        .filter(
            Match.role_id == role_id,
            sa_func.lower(Candidate.name).contains(q_lower),
        )
        .all()
    )

    results = []
    seen_ids = set()

    for match, candidate in existing_matches:
        # Skip if already starred and visible (already on company page)
        if match.starred and not match.hidden_from_company_page:
            continue
        cid = str(candidate.id)
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        results.append({
            "id": cid,
            "name": candidate.name,
            "github_username": candidate.github_username,
            "archetype": candidate.archetype,
            "tier": candidate.tier,
            "fit_score": match.match_score,
            "has_existing_match": True,
        })

    # 2) If we have fewer than 8 results, also search unmatched candidates
    if len(results) < 8:
        matched_cids = set(
            str(m.candidate_id) for m in db.query(Match).filter(Match.role_id == role_id).all()
        )
        matched_cids.update(seen_ids)

        unmatched = (
            db.query(Candidate)
            .filter(sa_func.lower(Candidate.name).contains(q_lower))
            .limit(10)
            .all()
        )
        for c in unmatched:
            cid = str(c.id)
            if cid in matched_cids:
                continue
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            results.append({
                "id": cid,
                "name": c.name,
                "github_username": c.github_username,
                "archetype": c.archetype,
                "tier": c.tier,
                "fit_score": None,
                "has_existing_match": False,
            })
            if len(results) >= 8:
                break

    # Sort by fit_score descending (existing matches first, then unmatched)
    results.sort(key=lambda r: (r["fit_score"] or 0), reverse=True)

    return {"candidates": results[:8]}


@router.post("/public/company/add-to-role", tags=["public"])
def add_candidate_to_role_company_page(candidate_id: str, role_id: str, db: Session = Depends(get_db)):
    """Add a candidate to a role on the company page by creating a starred match."""
    import uuid as _uuid

    # Check if match already exists
    existing = db.query(Match).filter(
        Match.candidate_id == candidate_id,
        Match.role_id == role_id,
    ).first()

    if existing:
        # Re-star and unhide it
        existing.starred = True
        existing.hidden_from_company_page = False
        db.commit()
        return {"match_id": str(existing.id), "action": "restored"}

    # Create new match + star it
    new_match = Match(
        id=_uuid.uuid4(),
        candidate_id=candidate_id,
        role_id=role_id,
        starred=True,
        hidden_from_company_page=False,
    )
    db.add(new_match)

    # Increment star count on candidate
    candidate = crud.get_candidate(db, candidate_id)
    if candidate:
        candidate.star_count = (candidate.star_count or 0) + 1

    db.commit()
    return {"match_id": str(new_match.id), "action": "created"}


@router.post("/public/company/toggle-role-visibility", tags=["public"])
def toggle_role_company_page_visibility(role_id: str, db: Session = Depends(get_db)):
    """Toggle whether a role appears in the 'sourcing in progress' section for clients."""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    role.hide_from_company_page = not bool(role.hide_from_company_page)
    db.commit()
    return {"role_id": str(role.id), "hide_from_company_page": role.hide_from_company_page}


@router.post("/public/company/notes", tags=["public"])
def update_company_page_notes(company_slug: str, notes: str = "", db: Session = Depends(get_db)):
    """Update the admin notes displayed on a company page. Stored on the first role for that company."""
    from app.models.role import RoleStatus
    slug = company_slug.lower().replace('-', ' ').replace('_', ' ')
    roles = db.query(Role).filter(
        sa_func.lower(sa_func.replace(sa_func.replace(Role.company_name, '-', ' '), '_', ' ')).like(f'%{slug}%')
    ).filter(Role.status.notin_([RoleStatus.placed, RoleStatus.lost])).order_by(Role.created_at.asc()).all()
    if not roles:
        raise HTTPException(status_code=404, detail="Company not found")
    # Store on the first (oldest) role for this company
    roles[0].company_page_notes = notes.strip() if notes.strip() else None
    db.commit()
    return {"success": True, "notes": roles[0].company_page_notes}


@router.get("/candidates/{candidate_id}/email-chain", tags=["candidates"])
def get_candidate_email_chain(candidate_id: UUID, db: Session = Depends(get_db)):
    """Return the full email event chain for a candidate."""
    from app.services.email_events import get_email_chain
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return {"candidate_id": str(candidate_id), "events": get_email_chain(db, candidate_id)}


@router.get("/public/candidates/{username}", tags=["public"])
def get_public_candidate_profile(username: str, db: Session = Depends(get_db)):
    """
    Get public candidate profile by GitHub username.

    Returns full vibe_report data for display on recruiting.chekk.dev/{username}
    """
    try:
        candidate = crud.get_candidate_by_github_username(db, username)

        if not candidate:
            raise HTTPException(
                status_code=404,
                detail=f"Candidate @{username} not found. They may not be in our system yet."
            )

        # Return full candidate data including vibe_report
        return {
            "success": True,
            "candidate": {
                "id": str(candidate.id),
                "name": candidate.name,
                "github_username": candidate.github_username,
                "email": candidate.email,
                "linkedin_url": candidate.linkedin_url,
                "github_url": candidate.github_url,
                "website_url": candidate.website_url,
                "twitter_url": candidate.twitter_url,
                "current_role": candidate.current_role,
                "current_company": candidate.current_company,
                "behavior_tier": candidate.behavior_tier,

                # Location
                "location_country": candidate.location_country,
                "location_raw": candidate.location_raw,

                # Bio
                "bio": candidate.github_bio,

                # GitHub Stats
                "github_followers": candidate.github_followers or 0,
                "github_public_repos": candidate.github_public_repos or 0,
                "github_languages": candidate.github_languages or [],
                "github_commits_90d": candidate.github_commits_90d or 0,
                "github_commits_30d": candidate.github_commits_30d or 0,
                "github_total_commits": candidate.github_total_commits or 0,
                "github_total_stars": candidate.github_total_stars or 0,

                # Analysis Results
                "archetype": candidate.archetype,
                "tier": candidate.tier,
                "tier_badge": candidate.tier_badge,
                "tier_percentile": candidate.tier_percentile,
                "vibe_report": candidate.vibe_report or {},

                # Resume
                "resume_text": candidate.resume_text,
                "has_resume_pdf": candidate.resume_pdf is not None,

                # Screening
                "screening_status": candidate.screening_status,
                "screening_summary": candidate.screening_summary,
                "screening_transcript": candidate.screening_transcript,
                "screening_data": candidate.screening_data,
                "screening_audio_url": candidate.screening_audio_url,
                "screening_completed_at": candidate.screening_completed_at.isoformat() if candidate.screening_completed_at else None,

                # Voice answers (strip audio_base64 — served via /voice-audio/{index})
                "voice_answers": [
                    {k: v for k, v in answer.items() if k != "audio_base64"}
                    if answer else None
                    for answer in (candidate.voice_answers or [])
                ] if candidate.voice_answers else None,

                # Flags
                "bookmarked": bool(candidate.bookmarked),
                "manually_warmed": bool(candidate.manually_warmed),

                # Notes
                "linkedin_text": candidate.linkedin_text,

                # Visibility
                "role_pages_disabled": bool(candidate.role_pages_disabled),

                # Metadata
                "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
                "updated_at": candidate.updated_at.isoformat() if candidate.updated_at else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching public profile for %s: %s", username, e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching profile: {str(e)}")


@router.get("/public/role-profile/{company_name}/{username}", tags=["public"])
def get_role_candidate_profile(company_name: str, username: str, role_id: Optional[str] = None, role_slug: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Get candidate profile contextualized for a specific role/company.

    Returns candidate data + CrossChekk fit analysis + role info.
    Used for recruiting.chekk.dev/r/{company}/{role-slug}/{username} pages sent to hirers.

    role_slug: slugified role title (e.g. "software-engineer") for URL-based disambiguation.
    role_id: UUID of the exact role (legacy support).
    """
    try:
        candidate = crud.get_candidate_by_github_username(db, username)
        if not candidate:
            raise HTTPException(status_code=404, detail=f"Candidate @{username} not found.")

        # Block access when role pages are disabled for this candidate
        if candidate.role_pages_disabled:
            raise HTTPException(status_code=404, detail="This profile page is not available.")

        from app.models.fit_analysis import FitAnalysis

        # If role_id is provided, use it directly to find the exact role
        if role_id:
            from uuid import UUID as PyUUID
            try:
                rid = PyUUID(role_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid role_id format")
            matched_role = db.query(Role).filter(Role.id == rid).first()
            if not matched_role:
                raise HTTPException(status_code=404, detail=f"Role {role_id} not found.")
            fit = db.query(FitAnalysis).filter(
                FitAnalysis.candidate_id == candidate.id,
                FitAnalysis.role_id == matched_role.id,
            ).order_by(FitAnalysis.created_at.desc()).first()
        else:
            # Find roles by company_name (case-insensitive, slugified match)
            from sqlalchemy import func
            slug = company_name.lower().replace('-', ' ').replace('_', ' ')
            roles = db.query(Role).filter(
                func.lower(func.replace(Role.company_name, '-', ' ')).like(f'%{slug}%')
            ).all()

            if not roles:
                raise HTTPException(status_code=404, detail=f"No roles found for company '{company_name}'.")

            # If role_slug is provided, narrow down to the matching role by title
            if role_slug:
                import re as _re
                slug_normalized = _re.sub(r'[^a-z0-9]+', ' ', role_slug.lower()).strip()
                matching = [r for r in roles if _re.sub(r'[^a-z0-9]+', ' ', r.title.lower()).strip() == slug_normalized]
                if matching:
                    roles = matching

            # Find the best fit analysis for this candidate across matching roles
            role_ids = [r.id for r in roles]
            role_map = {r.id: r for r in roles}
            best_fit = db.query(FitAnalysis).filter(
                FitAnalysis.candidate_id == candidate.id,
                FitAnalysis.role_id.in_(role_ids),
            ).order_by(FitAnalysis.fit_score.desc(), FitAnalysis.created_at.desc()).first()

            fit = best_fit
            matched_role = role_map.get(best_fit.role_id) if best_fit else None

            if not matched_role:
                # No fit analysis — use first role for context
                matched_role = roles[0]

        vibe_report = candidate.vibe_report or {}

        # Look up the match to get notes
        from app.models.match import Match as MatchModel
        match_obj = db.query(MatchModel).filter(
            MatchModel.candidate_id == candidate.id,
            MatchModel.role_id == matched_role.id,
        ).first()

        return {
            "success": True,
            "match_id": str(match_obj.id) if match_obj else None,
            "match_notes": match_obj.notes if match_obj else None,
            "candidate": {
                "id": str(candidate.id),
                "name": candidate.name,
                "github_username": candidate.github_username,
                "email": candidate.email,
                "linkedin_url": candidate.linkedin_url,
                "github_url": candidate.github_url,
                "website_url": candidate.website_url,
                "location_country": candidate.location_country,
                "location_raw": candidate.location_raw,
                "bio": candidate.github_bio,
                "current_role": candidate.current_role,
                "current_company": candidate.current_company,
                "github_followers": candidate.github_followers or 0,
                "github_public_repos": candidate.github_public_repos or 0,
                "github_languages": candidate.github_languages or [],
                "github_commits_90d": candidate.github_commits_90d or 0,
                "github_commits_30d": candidate.github_commits_30d or 0,
                "github_total_commits": candidate.github_total_commits or 0,
                "github_total_stars": candidate.github_total_stars or 0,
                "archetype": candidate.archetype,
                "tier": candidate.tier,
                "tier_badge": candidate.tier_badge,
                "tier_percentile": candidate.tier_percentile,
                "vibe_report": vibe_report,
                "resume_text": candidate.resume_text,
                "has_resume_pdf": candidate.resume_pdf is not None,
                "screening_status": candidate.screening_status,
                "screening_summary": candidate.screening_summary,
                "voice_answers": [
                    {k: v for k, v in answer.items() if k != "audio_base64"}
                    if answer else None
                    for answer in (candidate.voice_answers or [])
                ] if candidate.voice_answers else None,
            },
            "role": {
                "id": str(matched_role.id),
                "title": matched_role.title,
                "company_name": matched_role.company_name,
                "company_stage": matched_role.company_stage.value if matched_role.company_stage else None,
                "location_requirement": matched_role.location_requirement.value if matched_role.location_requirement else None,
                "location_cities": matched_role.location_cities,
                "tech_stack": matched_role.tech_stack or [],
                "urgency": matched_role.urgency.value if matched_role.urgency else None,
                "jd_url": matched_role.jd_url,
            },
            "fit_analysis": {
                "fit_score": fit.fit_score,
                "recommendation": fit.recommendation,
                "skills_matched": fit.skills_matched or [],
                "skills_missing": fit.skills_missing or [],
                "skills_extra": fit.skills_extra or [],
                "candidate_level": fit.candidate_level,
                "required_level": fit.required_level,
                "experience_meets": fit.experience_meets,
                "strengths": fit.strengths or [],
                "concerns": fit.concerns or [],
                "ai_summary": fit.ai_summary,
                "ai_summary_short": fit.ai_summary_short,
            } if fit else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching role profile for %s/%s: %s", company_name, username, e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching profile: {str(e)}")


@router.post("/candidates/{candidate_id}/generate-outreach", tags=["candidates", "outreach"])
def generate_candidate_outreach(
    candidate_id: UUID,
    role_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """
    Generate personalized outreach email template for candidate.

    Uses DeepSeek to create customized cold outreach based on:
    - Candidate's GitHub analysis and vibe_report
    - Their verified skills and highlights
    - Optional role context (if recruiting for specific position)
    """
    from app.core.config import settings
    from app.services.outreach_generator import generate_outreach_template

    # Get candidate
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Check if candidate has GitHub username
    if not candidate.github_username:
        raise HTTPException(
            status_code=400,
            detail="Outreach generation requires a GitHub username. This feature only works for candidates with GitHub profiles."
        )

    # Auto-analyze if candidate hasn't been analyzed yet
    if not candidate.vibe_report:
        try:
            from app.services.candidate_analysis import run_candidate_analysis
            run_candidate_analysis(candidate.id, db)
            db.refresh(candidate)
        except Exception as e:
            logger.error("Auto-analyze failed for %s during outreach generation: %s", candidate_id, e)
            raise HTTPException(
                status_code=500,
                detail=f"Auto-analysis failed: {str(e)[:200]}"
            )
        if not candidate.vibe_report:
            raise HTTPException(
                status_code=400,
                detail="Candidate analysis did not produce a vibe report. Cannot generate outreach."
            )

    # Build candidate data
    candidate_data = {
        'id': str(candidate.id),
        'name': candidate.name,
        'github_username': candidate.github_username,
        'email': candidate.email,
        'archetype': candidate.archetype,
        'tier': candidate.tier,
        'vibe_report': candidate.vibe_report,
        'github_languages': candidate.github_languages or []
    }

    # Optional: get role context with full details for role-specific outreach
    role_context = None
    fit_analysis_data = None
    if role_id:
        role = crud.get_role(db, role_id)
        if role:
            comp_str = ''
            if role.comp_max:
                comp_str = f"up to ${role.comp_max // 1000}K"
            elif role.comp_min:
                comp_str = f"${role.comp_min // 1000}K+"
            equity_str = 'significant equity' if comp_str else ''
            loc_req = role.location_requirement.value if role.location_requirement else ''
            loc_cities = ', '.join(role.location_cities) if role.location_cities else ''
            if loc_req == 'remote':
                location_str = 'Remote'
            elif loc_req == 'onsite' and loc_cities:
                location_str = f"{loc_cities} (onsite)"
            elif loc_req == 'hybrid' and loc_cities:
                location_str = f"{loc_cities} (hybrid)"
            elif loc_cities:
                location_str = loc_cities
            elif loc_req:
                location_str = loc_req.capitalize()
            else:
                location_str = 'Flexible'
            role_context = {
                'company': role.company_name,
                'title': role.title,
                'description': role.jd_text or '',
                'tech_stack': role.tech_stack or [],
                'comp': comp_str,
                'equity': equity_str,
                'location': location_str,
                'stage': role.company_stage.value.replace('_', ' ') if role.company_stage else '',
                'investors': role.notable_investors or [],
            }

            # Get fit analysis for this candidate-role pair
            from app.models.fit_analysis import FitAnalysis
            fit = db.query(FitAnalysis).filter(
                FitAnalysis.candidate_id == candidate_id,
                FitAnalysis.role_id == role_id,
            ).order_by(FitAnalysis.created_at.desc()).first()
            if fit:
                fit_analysis_data = {
                    'fit_score': fit.fit_score,
                    'recommendation': fit.recommendation,
                    'strengths': fit.strengths or [],
                    'concerns': fit.concerns or [],
                    'ai_summary': fit.ai_summary,
                }

    # If candidate has already been sent outreach and we have a role_id,
    # generate a follow-up pitch instead of a cold intro
    candidate_already_sent = (
        candidate.outreach_status and candidate.outreach_status.value == 'sent'
    ) or candidate.warmup_email_sent_at is not None

    if candidate_already_sent and role_id and role_context:
        from app.services.outreach_generator import generate_role_pitch

        # Determine if candidate opened the prior email
        candidate_opened = (
            candidate.warmup_email_opened_at is not None
            or (candidate.outreach_status and candidate.outreach_status.value in ('opened', 'clicked', 'replied'))
            or candidate.warmup_replied_at is not None
        )
        logger.info("Candidate %s already sent outreach (opened=%s) — routing to role pitch", candidate_id, candidate_opened)

        email_history = {
            'outreach_subject': candidate.sent_outreach_subject or candidate.outreach_subject or '',
            'outreach_body': candidate.sent_outreach_body or candidate.outreach_body or '',
            'reply_text': candidate.warmup_reply_text or '',
            'followup_body': candidate.followup_body or '',
        }
        role_data = {
            'title': role_context.get('title', 'Software Engineer'),
            'company': role_context.get('company', 'a startup'),
            'jd_text': role_context.get('description', ''),
            'tech_stack': role_context.get('tech_stack', []),
            'comp': role_context.get('comp', ''),
            'equity': role_context.get('equity', 'significant equity'),
            'location': role_context.get('location', 'Flexible'),
            'stage': role_context.get('stage', ''),
            'investors': role_context.get('investors', []),
        }
        candidate_for_pitch = {
            'name': candidate.name,
            'github_username': candidate.github_username,
            'archetype': candidate.archetype,
            'tier': candidate.tier,
            'tech_stack': candidate.tech_stack or candidate.github_languages or [],
            'linkedin_text': candidate.linkedin_text or '',
            'resume_text': candidate.resume_text or '',
        }
        try:
            result = generate_role_pitch(
                api_key=settings.DEEPSEEK_API_KEY,
                candidate=candidate_for_pitch,
                role=role_data,
                email_history=email_history,
                fit_analysis=fit_analysis_data,
                candidate_opened=candidate_opened,
            )
            # Persist draft on the match record only (don't touch candidate fields)
            if result.get('success') and result.get('subject') and result.get('body'):
                from app.models.match import Match
                match = db.query(Match).filter(
                    Match.candidate_id == candidate_id,
                    Match.role_id == role_id,
                ).first()
                if match:
                    match.draft_subject = result['subject']
                    match.draft_body = result['body']
                db.commit()

            return {
                "success": True,
                "outreach": result,
                "candidate": {
                    "name": candidate.name,
                    "github_username": candidate.github_username,
                    "email": candidate.email
                }
            }
        except Exception as e:
            logger.error("Follow-up pitch generation failed, falling back to cold: %s", e)
            # Fall through to cold outreach generation below

    # Generate outreach template (cold intro)
    try:
        result = generate_outreach_template(
            api_key=settings.DEEPSEEK_API_KEY,
            candidate=candidate_data,
            github_token=settings.GITHUB_TOKEN,
            role_context=role_context,
            fit_analysis=fit_analysis_data,
        )

        # Persist draft so it survives page refresh
        if result.get('success') and result.get('subject') and result.get('body'):
            from app.models.candidate import OutreachStatus

            already_sent = candidate.outreach_status == OutreachStatus.sent

            if already_sent and role_id:
                # Candidate was already sent outreach — do NOT overwrite their
                # outreach_status/subject/body (that would destroy the sent record
                # and break warmth detection). Only save to the match draft.
                from app.models.match import Match
                match = db.query(Match).filter(
                    Match.candidate_id == candidate_id,
                    Match.role_id == role_id,
                ).first()
                if match:
                    match.draft_subject = result['subject']
                    match.draft_body = result['body']
            else:
                # First outreach (not yet sent) — safe to write to candidate record
                candidate.outreach_subject = result['subject']
                candidate.outreach_body = result['body']
                candidate.outreach_status = OutreachStatus.drafted
                candidate.outreach_type = "role_specific" if role_id else "generic"
                candidate.outreach_scheduled_for = None
                # Store denormalized role label for outreach queue display
                if role_id and role:
                    candidate.outreach_role_title = f"{role.title} @ {role.company_name}" if role.title and role.company_name else (role.title or role.company_name or None)
                elif not role_id:
                    candidate.outreach_role_title = None

                # Also persist draft on the match record (if role_id provided)
                if role_id:
                    from app.models.match import Match
                    match = db.query(Match).filter(
                        Match.candidate_id == candidate_id,
                        Match.role_id == role_id,
                    ).first()
                    if match:
                        match.draft_subject = result['subject']
                        match.draft_body = result['body']

            db.commit()
            db.refresh(candidate)

        return {
            "success": True,
            "outreach": result,
            "candidate": {
                "name": candidate.name,
                "github_username": candidate.github_username,
                "email": candidate.email
            }
        }

    except Exception as e:
        logger.error("Outreach generation failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate outreach template: {str(e)}"
        )


@router.post("/candidates/{candidate_id}/generate-role-pitch", tags=["candidates", "outreach"])
def generate_candidate_role_pitch(
    candidate_id: UUID,
    role_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Generate a role-specific follow-up email for a candidate we've already contacted.

    Unlike generate-outreach (cold intro), this generates a follow-up that:
    - References the prior email conversation
    - Pitches the specific role with company/title/comp details
    - Connects the candidate's skills to the role requirements
    """
    from app.core.config import settings
    from app.services.outreach_generator import generate_role_pitch

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    role = crud.get_role(db, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Determine if candidate opened the prior email
    candidate_opened = (
        candidate.warmup_email_opened_at is not None
        or (candidate.outreach_status and candidate.outreach_status.value in ('opened', 'clicked', 'replied'))
        or candidate.warmup_replied_at is not None
    )

    # Build email history from candidate record
    # Use sent_outreach_* snapshots (immutable) to get the actual email that was sent,
    # falling back to outreach_* (which may have been overwritten by regeneration)
    email_history = {
        'outreach_subject': candidate.sent_outreach_subject or candidate.outreach_subject or '',
        'outreach_body': candidate.sent_outreach_body or candidate.outreach_body or '',
        'reply_text': candidate.warmup_reply_text or '',
        'followup_body': candidate.followup_body or '',
    }

    # Build role data — same comp/equity/location formatting as generate-outreach
    comp_str = ''
    if role.comp_max:
        comp_str = f"up to ${role.comp_max // 1000}K"
    elif role.comp_min:
        comp_str = f"${role.comp_min // 1000}K+"
    equity_str = 'significant equity' if comp_str else ''
    loc_req = role.location_requirement.value if role.location_requirement else ''
    loc_cities = ', '.join(role.location_cities) if role.location_cities else ''
    if loc_req == 'remote':
        location_str = 'Remote'
    elif loc_req == 'onsite' and loc_cities:
        location_str = f"{loc_cities} (onsite)"
    elif loc_req == 'hybrid' and loc_cities:
        location_str = f"{loc_cities} (hybrid)"
    elif loc_cities:
        location_str = loc_cities
    elif loc_req:
        location_str = loc_req.capitalize()
    else:
        location_str = 'Flexible'
    role_data = {
        'title': role.title,
        'company': role.company_name,
        'jd_text': role.jd_text or '',
        'tech_stack': role.tech_stack or [],
        'comp': comp_str,
        'equity': equity_str,
        'location': location_str,
        'stage': role.company_stage.value.replace('_', ' ') if role.company_stage else '',
        'investors': role.notable_investors or [],
    }

    # Build candidate data
    candidate_data = {
        'name': candidate.name,
        'github_username': candidate.github_username,
        'archetype': candidate.archetype,
        'tier': candidate.tier,
        'tech_stack': candidate.tech_stack or candidate.github_languages or [],
        'linkedin_text': candidate.linkedin_text or '',
        'resume_text': candidate.resume_text or '',
    }

    # Get fit analysis for this candidate-role pair
    fit_analysis_data = None
    from app.models.fit_analysis import FitAnalysis
    fit = db.query(FitAnalysis).filter(
        FitAnalysis.candidate_id == candidate_id,
        FitAnalysis.role_id == role_id,
    ).order_by(FitAnalysis.created_at.desc()).first()
    if fit:
        fit_analysis_data = {
            'fit_score': fit.fit_score,
            'recommendation': fit.recommendation,
            'strengths': fit.strengths or [],
            'concerns': fit.concerns or [],
            'ai_summary': fit.ai_summary,
        }

    try:
        result = generate_role_pitch(
            api_key=settings.DEEPSEEK_API_KEY,
            candidate=candidate_data,
            role=role_data,
            email_history=email_history,
            fit_analysis=fit_analysis_data,
            candidate_opened=candidate_opened,
        )

        # Persist draft on the match record
        if result.get('subject') and result.get('body'):
            from app.models.match import Match
            match = db.query(Match).filter(
                Match.candidate_id == candidate_id,
                Match.role_id == role_id,
            ).first()
            if match:
                match.draft_subject = result['subject']
                match.draft_body = result['body']
                db.commit()

        return {
            "success": True,
            "outreach": result,
            "candidate": {
                "name": candidate.name,
                "github_username": candidate.github_username,
                "email": candidate.email
            }
        }

    except Exception as e:
        logger.error("Role pitch generation failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate role pitch: {str(e)}"
        )


@router.post("/candidates/{candidate_id}/generate-manual-followup", tags=["candidates", "outreach"])
def generate_manual_followup(
    candidate_id: UUID,
    context: str = "",
    db: Session = Depends(get_db),
):
    """
    Generate a follow-up email based on user-provided context and the existing email chain.

    The user describes what they want to say, and DeepSeek crafts a proper follow-up
    that fits naturally into the existing conversation thread.
    """
    from app.core.config import settings
    import requests as http_requests

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="DeepSeek API key not configured")

    # Build email chain — prefer email_events if available, fall back to scattered fields
    from app.services.email_events import get_email_chain
    events = get_email_chain(db, candidate_id)

    chain_parts = []
    if events:
        label_map = {
            'outreach_sent': 'YOUR INITIAL EMAIL',
            'screening_sent': 'YOUR SCREENING QUESTIONS',
            'followup_sent': 'YOUR FOLLOW-UP',
            'role_pitch_sent': 'YOUR ROLE PITCH',
            'candidate_replied': '{name} REPLIED',
            'screening_answered': '{name} ANSWERED SCREENING',
        }
        cand_name = (candidate.name or candidate.github_username or 'CANDIDATE').upper()
        for ev in events:
            et = ev.get('event_type', '')
            if et in label_map:
                label = label_map[et].replace('{name}', cand_name)
                body = ev.get('body') or ''
                subj = ev.get('subject') or ''
                part = f"{label}:"
                if subj:
                    part += f"\nSubject: {subj}"
                if body:
                    part += f"\n{body}"
                chain_parts.append(part)
    else:
        # Legacy fallback: build from scattered candidate fields
        if candidate.sent_outreach_subject or candidate.outreach_subject:
            subj = candidate.sent_outreach_subject or candidate.outreach_subject
            body = candidate.sent_outreach_body or candidate.outreach_body or ''
            chain_parts.append(f"YOUR INITIAL EMAIL:\nSubject: {subj}\n{body}")
        if candidate.warmup_reply_text:
            name = candidate.name or candidate.github_username
            chain_parts.append(f"{name.upper()} REPLIED:\n{candidate.warmup_reply_text}")
        if candidate.screening_body:
            chain_parts.append(f"YOUR SCREENING QUESTIONS:\n{candidate.screening_body}")
        elif candidate.followup_body and not candidate.followup_sent_at:
            # followup_body holds screening text only if no manual follow-up was sent
            chain_parts.append(f"YOUR SCREENING QUESTIONS:\n{candidate.followup_body}")
        if candidate.screening_transcript:
            name = candidate.name or candidate.github_username
            chain_parts.append(f"{name.upper()} ANSWERED SCREENING:\n{candidate.screening_transcript}")
        if candidate.followup_sent_at and candidate.followup_body:
            chain_parts.append(f"YOUR FOLLOW-UP:\n{candidate.followup_body}")

    email_chain = "\n\n---\n\n".join(chain_parts) if chain_parts else "No prior emails."
    candidate_name = candidate.name or candidate.github_username or "there"
    from app.services.screening_automation import extract_first_name
    candidate_first = extract_first_name(candidate_name)

    prompt = f"""Write a follow-up email for a recruiting conversation. The recruiter has told you EXACTLY what they want to communicate. Your job is to turn their intent into a well-crafted email that fits naturally into the existing thread.

## EXISTING EMAIL CHAIN
{email_chain}

## WHAT THE RECRUITER WANTS TO SAY
{context}

## RULES
- Write the email as if the recruiter is sending it — first person, their voice
- Reference the prior conversation naturally where relevant
- Keep the tone casual and direct, matching the existing thread style
- If the recruiter's intent involves declining, be graceful but firm
- If the recruiter's intent involves moving forward, be enthusiastic but not pushy
- Keep it concise: 50-150 words unless the context requires more
- Subject should be "Re: {{original subject}}" to keep the thread
- No em dashes. No generic filler. No "hope you're doing well."
- Address the candidate as {candidate_first}

Return as JSON:
{{
  "subject": "Re: ...",
  "body": "Hey {candidate_first},\\n\\n..."
}}"""

    try:
        response = http_requests.post(
            'https://api.deepseek.com/v1/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'
            },
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You write recruiting emails. You take the recruiter\'s intent and turn it into a polished email that continues an existing conversation thread. Return valid JSON only.'
                    },
                    {'role': 'user', 'content': prompt}
                ],
                'response_format': {'type': 'json_object'},
                'temperature': 0.7
            },
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        content = data['choices'][0]['message']['content']

        import json
        result = json.loads(content)

        return {
            "success": True,
            "subject": result.get("subject", f"Re: {candidate.outreach_subject or ''}"),
            "body": result.get("body", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate follow-up: {str(e)}")


@router.post("/candidates/dismiss", tags=["candidates", "outreach"])
def dismiss_candidates(
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Dismiss (reject) candidates from the outreach pipeline.
    Sets status to 'rejected' so they're hidden from default views.
    Body: { "candidate_ids": ["uuid1", "uuid2", ...] }
    """
    candidate_ids = body.get("candidate_ids", [])
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="No candidate IDs provided")

    dismissed = 0
    for cid in candidate_ids:
        candidate = crud.get_candidate(db, cid)
        if candidate:
            update_data = CandidateUpdate(status="rejected")
            crud.update_candidate(db, cid, update_data)
            candidate.dormant = True
            candidate.dormant_reason = "manual"
            db.commit()
            dismissed += 1

    return {"dismissed": dismissed, "message": f"Dismissed {dismissed} candidate(s)"}


@router.post("/candidates/undismiss", tags=["candidates", "outreach"])
def undismiss_candidates(
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Restore dismissed candidates back to the active pipeline.
    Sets status back to 'warm' (or 'contacted' if they haven't replied).
    Body: { "candidate_ids": ["uuid1", "uuid2", ...] }
    """
    candidate_ids = body.get("candidate_ids", [])
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="No candidate IDs provided")

    restored = 0
    for cid in candidate_ids:
        candidate = crud.get_candidate(db, cid)
        if candidate and candidate.status == CandidateStatus.rejected:
            new_status = "warm" if candidate.warmup_replied_at else "contacted"
            update_data = CandidateUpdate(status=new_status)
            crud.update_candidate(db, cid, update_data)
            candidate.dormant = False
            candidate.dormant_reason = None
            db.commit()
            restored += 1

    return {"restored": restored, "message": f"Restored {restored} candidate(s)"}


@router.post("/candidates/auto-dormant-sweep", tags=["candidates", "outreach"])
def auto_dormant_sweep(db: Session = Depends(get_db)):
    """
    Auto-move candidates to dormant who:
    - Had outreach sent (outreach_status = 'sent')
    - Had a follow-up sent (followup_sent_at is not null)
    - Never replied (warmup_replied_at is null)
    - Follow-up was sent >= 3 days ago
    - Not already dormant
    """
    from app.models.candidate import OutreachStatus
    cutoff = datetime.utcnow() - timedelta(days=3)

    eligible = (
        db.query(Candidate)
        .filter(
            Candidate.outreach_status == OutreachStatus.sent,
            Candidate.followup_sent_at.isnot(None),
            Candidate.followup_sent_at <= cutoff,
            Candidate.warmup_replied_at.is_(None),
            Candidate.dormant != True,
        )
        .all()
    )

    moved = 0
    for c in eligible:
        c.status = CandidateStatus.rejected
        c.dormant = True
        c.dormant_reason = "auto_no_reply"
        moved += 1

    if moved:
        db.commit()
    logger.info("Auto-dormant sweep: moved %d candidate(s)", moved)
    return {"moved": moved, "message": f"Auto-dormant: {moved} candidate(s) moved"}


class ComposeEmailRequest(BaseModel):
    candidate_ids: List[str]
    template: str  # Template with {name}, {first_name} placeholders or just intent for DeepSeek


@router.post("/candidates/compose-personalized", tags=["candidates", "outreach"])
def compose_personalized_email(
    body: ComposeEmailRequest,
    db: Session = Depends(get_db),
):
    """
    Generate personalized emails for multiple candidates based on a template/intent.
    DeepSeek personalizes each email based on the candidate's context and email history.

    Returns a list of {candidate_id, name, subject, body} for preview before sending.
    """
    from app.core.config import settings
    import requests as http_requests

    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="DeepSeek API key not configured")

    results = []
    for cid in body.candidate_ids:
        candidate = crud.get_candidate(db, cid)
        if not candidate:
            continue

        from app.services.screening_automation import extract_first_name
        first_name = extract_first_name(candidate.name, fallback=candidate.github_username or "there")
        name = candidate.name or candidate.github_username or "there"

        # Build context about this candidate
        context_parts = [f"Name: {name}"]
        if candidate.archetype:
            context_parts.append(f"Archetype: {candidate.archetype} ({candidate.tier})")
        if candidate.location_country:
            context_parts.append(f"Location: {candidate.location_country}")

        # Include notable repos/projects from vibe_report instead of raw language list
        vibe = candidate.vibe_report or {}
        highlights = vibe.get("highlights", [])
        if highlights:
            highlight_strs = []
            for h in highlights[:4]:
                if isinstance(h, dict):
                    highlight_strs.append(h.get("text") or h.get("detail", ""))
                elif isinstance(h, str):
                    highlight_strs.append(h)
            if highlight_strs:
                context_parts.append(f"Notable work: {'; '.join(s for s in highlight_strs if s)}")
        tech_signal = vibe.get("technical_signal", "")
        if tech_signal:
            context_parts.append(f"Technical signal: {tech_signal[:300]}")

        # Full email chain so DeepSeek can reference the actual conversation
        chain_parts = []
        if candidate.outreach_subject and candidate.outreach_body:
            chain_parts.append(f"YOUR INITIAL OUTREACH:\nSubject: {candidate.outreach_subject}\n{candidate.outreach_body}")
        if candidate.warmup_reply_text:
            chain_parts.append(f"{name.upper()} REPLIED:\n{candidate.warmup_reply_text[:500]}")
        if candidate.followup_body:
            chain_parts.append(f"YOUR FOLLOW-UP:\n{candidate.followup_body[:500]}")
        # Include screening answers if available
        if candidate.screening_transcript:
            chain_parts.append(f"{name.upper()} SCREENING ANSWERS:\n{candidate.screening_transcript[:500]}")

        candidate_context = "\n".join(context_parts)
        email_chain = "\n\n---\n\n".join(chain_parts) if chain_parts else "No prior emails."

        prompt = f"""Write a personalized email for this candidate based on the recruiter's template/intent.

CANDIDATE:
{candidate_context}

FULL EMAIL HISTORY:
{email_chain}

RECRUITER'S TEMPLATE/INTENT:
{body.template}

RULES:
- Personalize for THIS specific candidate — reference their repos, projects, or things discussed in the email chain. NEVER just list their programming languages.
- Keep the core message/intent from the template
- Address them as {first_name}
- Thread into existing conversation if there is one (use "Re: {{original subject}}")
- Keep it concise and natural
- No em dashes, no corporate fluff

Return ONLY valid JSON:
{{
  "subject": "the email subject",
  "body": "the full email body"
}}"""

        try:
            response = http_requests.post(
                'https://api.deepseek.com/v1/chat/completions',
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'
                },
                json={
                    'model': 'deepseek-chat',
                    'messages': [
                        {'role': 'system', 'content': 'You write recruiting emails. Return valid JSON only.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    'response_format': {'type': 'json_object'},
                    'temperature': 0.7
                },
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            content = data['choices'][0]['message']['content']
            result = json.loads(content)

            # Default subject to Re: original if not provided
            subject = result.get("subject", "")
            if not subject and candidate.outreach_subject:
                subject = f"Re: {candidate.outreach_subject}"

            results.append({
                "candidate_id": str(candidate.id),
                "name": name,
                "email": candidate.email,
                "subject": subject,
                "body": result.get("body", ""),
            })
        except Exception as e:
            logger.error("Failed to compose email for %s: %s", cid, e)
            results.append({
                "candidate_id": str(candidate.id),
                "name": name,
                "email": candidate.email,
                "subject": f"Re: {candidate.outreach_subject or ''}",
                "body": f"[Generation failed: {e}]",
                "error": str(e),
            })

    return {"emails": results}


class SendOutreachBody(BaseModel):
    subject: str
    body: str
    is_followup: bool = False
    cohort_name: Optional[str] = None


@router.post("/candidates/{candidate_id}/send-outreach", tags=["candidates", "outreach"])
def send_candidate_outreach(
    candidate_id: UUID,
    payload: Optional[SendOutreachBody] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    is_followup: bool = False,
    cohort_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Send approved outreach email to candidate via Resend API.

    Accepts either a JSON body or query params (JSON body preferred).
    is_followup=False (new outreach): resets entire activity timeline
    is_followup=True (follow-up nudge): keeps timeline, just updates sent timestamp
    """
    # Prefer JSON body, fall back to query params
    if payload:
        subject = payload.subject
        body = payload.body
        is_followup = payload.is_followup
        cohort_name = payload.cohort_name
    if not subject or not body:
        raise HTTPException(status_code=400, detail="subject and body are required")
    from app.services.email_sender import send_outreach_email
    from app.schemas.candidate import CandidateUpdate

    # Get candidate
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not candidate.email:
        raise HTTPException(status_code=400, detail="Candidate has no email address")

    # Send email via Resend
    try:
        result = send_outreach_email(
            to_email=candidate.email,
            subject=subject,
            body=body,
            candidate_name=candidate.name
        )

        if is_followup:
            # Follow-up: add separate follow-up entry, keep existing timeline intact
            # Store the full email body so it appears in the email chain
            # Also clear has_unread_reply since we've responded to their reply
            followup_full = f"Subject: {subject}\n\n{body}"
            update_data = CandidateUpdate(
                last_contact_date=datetime.utcnow().date(),
                last_contact_method="email",
                followup_sent_at=datetime.utcnow().isoformat(),
                followup_email_id=result.get("email_id"),
                followup_body=followup_full,
                has_unread_reply=False,
            )
        else:
            # New outreach: reset entire activity timeline
            from app.models.candidate import OutreachStatus
            update_data = CandidateUpdate(
                status="contacted",
                outreach_status=OutreachStatus.sent,
                outreach_subject=subject,
                outreach_body=body,
                last_contact_date=datetime.utcnow().date(),
                last_contact_method="email",
                warmup_email_sent_at=datetime.utcnow().isoformat(),
                warmup_email_id=result.get("email_id"),
                warmup_message_id=result.get("message_id"),
                warmup_email_opened_at=None,
                warmup_replied_at=None,
                warmup_reply_text=None,
                followup_sent_at=None,
                followup_email_id=None,
                screening_link_sent_at=None,
                screening_email_id=None,
                screening_email_opened_at=None,
                screening_link_clicked_at=None,
                screening_completed_at=None,
                screening_status=None,
                screening_transcript=None,
                screening_summary=None,
                screening_data=None,
                screening_audio_url=None,
            )
            # Snapshot the sent email so regeneration can't overwrite history
            candidate.sent_outreach_subject = subject
            candidate.sent_outreach_body = body

            # Assign cohort name if provided (e.g. from match screen)
            if cohort_name:
                candidate.outreach_cohort = cohort_name
        crud.update_candidate(db, candidate_id, update_data)

        # Append to email event log
        event_type = EmailEventType.followup_sent if is_followup else EmailEventType.outreach_sent
        append_email_event(
            db, candidate_id, event_type,
            subject=subject,
            body=body,
            resend_email_id=result.get("email_id"),
            message_id=result.get("message_id"),
        )
        db.commit()

        logger.info("Sent outreach email to %s, updated status to contacted", candidate.email)

        return {
            "success": True,
            "message": "Outreach email sent successfully",
            "email_id": result.get("email_id"),
            "candidate": {
                "name": candidate.name,
                "email": candidate.email,
                "status": "contacted"
            }
        }

    except Exception as e:
        logger.error("Failed to send outreach email: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send email: {str(e)}"
        )


# ===========================
# REPLY APPROVAL ENDPOINTS
# ===========================


class ApproveReplyRequest(BaseModel):
    body: Optional[str] = None  # Allow editing the draft before sending


@router.post("/candidates/{candidate_id}/approve-reply", tags=["candidates", "outreach"])
def approve_and_send_reply(
    candidate_id: UUID,
    request: ApproveReplyRequest = None,
    db: Session = Depends(get_db),
):
    """
    Approve and send a pending AI-drafted reply to a candidate.
    Optionally allows editing the body before sending.
    """
    from app.services.email_sender import send_outreach_email

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if candidate.screening_status not in ("pending_approval", "pending_approval_decline") and not candidate.has_unread_reply:
        raise HTTPException(status_code=400, detail=f"No pending reply to approve (status: {candidate.screening_status})")

    if not candidate.email:
        raise HTTPException(status_code=400, detail="Candidate has no email address")

    # Use edited body if provided, otherwise use the stored draft
    body = (request.body if request and request.body else candidate.screening_body)
    if not body:
        raise HTTPException(status_code=400, detail="No draft body found")

    # Thread into original conversation
    original_subject = candidate.sent_outreach_subject or candidate.outreach_subject or "your background"
    subject = f"Re: {original_subject}"

    is_decline = candidate.screening_status == "pending_approval_decline"

    try:
        result = send_outreach_email(
            to_email=candidate.email,
            subject=subject,
            body=body,
            candidate_name=candidate.name,
        )

        # Determine post-send status
        if is_decline:
            update_data = CandidateUpdate(
                screening_status="declined",
                screening_body=body,
                screening_link_sent_at=datetime.utcnow().isoformat(),
                screening_email_id=result.get("email_id"),
                status="rejected",
                has_unread_reply=False,
                last_contact_date=datetime.utcnow().date(),
                last_contact_method="email",
            )
        elif candidate.screening_completed_at:
            # This was a screening confirmation (answers already parsed)
            update_data = CandidateUpdate(
                screening_status="confirmed",
                screening_body=body,
                has_unread_reply=False,
                last_contact_date=datetime.utcnow().date(),
                last_contact_method="email",
            )
        else:
            # This was a follow-up with screening questions
            update_data = CandidateUpdate(
                screening_status="questions_sent",
                screening_body=body,
                screening_link_sent_at=datetime.utcnow().isoformat(),
                screening_email_id=result.get("email_id"),
                has_unread_reply=False,
                last_contact_date=datetime.utcnow().date(),
                last_contact_method="email",
            )

        crud.update_candidate(db, candidate_id, update_data)

        # Append to email event log
        event_type = EmailEventType.followup_sent if candidate.screening_completed_at else EmailEventType.screening_sent
        append_email_event(
            db, candidate_id, event_type,
            subject=subject, body=body,
            resend_email_id=result.get("email_id"),
            metadata={"type": "screening_confirmation"} if candidate.screening_completed_at else None,
        )
        db.commit()

        logger.info("Approved and sent reply to %s (%s)", candidate.email, candidate.name)

        return {
            "success": True,
            "message": "Reply approved and sent",
            "email_id": result.get("email_id"),
        }

    except Exception as e:
        logger.error("Failed to send approved reply to %s: %s", candidate.email, e)
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


@router.delete("/candidates/{candidate_id}/dismiss-reply", tags=["candidates", "outreach"])
def dismiss_pending_reply(
    candidate_id: UUID,
    db: Session = Depends(get_db),
):
    """Dismiss a pending AI-drafted reply without sending it."""
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if candidate.screening_status not in ("pending_approval", "pending_approval_decline") and not candidate.has_unread_reply:
        raise HTTPException(status_code=400, detail="No pending reply to dismiss")

    # Clear the draft but keep the candidate in a reasonable state
    update_data = CandidateUpdate(
        screening_status="dismissed",
        screening_body=None,
        has_unread_reply=False,
    )
    crud.update_candidate(db, candidate_id, update_data)
    db.commit()

    return {"success": True, "message": "Pending reply dismissed"}


# ===========================
# BULK OUTREACH ENDPOINTS
# ===========================

class BulkOutreachRequest(BaseModel):
    candidate_ids: Optional[List[str]] = None
    role_id: Optional[str] = None


@router.post("/candidates/bulk-generate-outreach", tags=["outreach"])
def bulk_generate_outreach_endpoint(
    body: Optional[BulkOutreachRequest] = None,
    status: Optional[str] = None,
    tier: Optional[str] = None,
    archetype_filter: Optional[str] = None,
    has_outreach: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """
    Bulk generate warm-up outreach emails for multiple candidates.

    Provide either candidate_ids or filters (status, tier, archetype_filter).
    Returns a job ID for polling progress via /ingestion/job/status/{job_id}.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    from app.services.bulk_outreach import bulk_generate_outreach
    from app.db.base import SessionLocal
    import threading

    # Extract candidate IDs and role_id from request body (if provided)
    candidate_ids = body.candidate_ids if body else None
    role_id_str = body.role_id if body else None

    # Resolve candidate IDs from filters if not provided directly
    if not candidate_ids:
        query = db.query(Candidate).filter(
            Candidate.archetype.isnot(None),  # Must be analyzed
            Candidate.email.isnot(None),  # Must have email
        )
        if status:
            query = query.filter(Candidate.status == status)
        if tier:
            query = query.filter(Candidate.tier == tier)
        if archetype_filter:
            query = query.filter(Candidate.archetype == archetype_filter)
        if has_outreach is not None:
            if has_outreach:
                query = query.filter(Candidate.outreach_status.isnot(None))
            else:
                query = query.filter(Candidate.outreach_status.is_(None))
        # Exclude already sent (when no explicit has_outreach filter)
        if has_outreach is None:
            query = query.filter(
                (Candidate.outreach_status.is_(None)) | (Candidate.outreach_status != 'sent')
            )
        candidates = query.all()
        candidate_ids = [str(c.id) for c in candidates]

    if not candidate_ids:
        raise HTTPException(status_code=400, detail="No candidates match filters (need analyzed + email)")

    # Create tracking job
    job = IngestionJob(
        status=JobStatus.running,
        job_type='bulk_outreach',
        role_id=role_id_str if role_id_str else None,
        total_candidates=len(candidate_ids),
        processed_count=0,
        candidates_saved=0,
        candidates_skipped=0,
        error_count=0,
        recent_logs=["Starting bulk outreach generation..."],
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Run in background thread
    job_id = str(job.id)
    ids_copy = list(candidate_ids)

    role_id_copy = role_id_str

    def run_in_background():
        bg_db = SessionLocal()
        try:
            bulk_generate_outreach(
                db=bg_db,
                candidate_ids=ids_copy,
                job_id=job_id,
                db_factory=SessionLocal,
                max_workers=6,
                role_id=role_id_copy,
            )
        except Exception as e:
            from app.core.logging import get_logger
            get_logger(__name__).error("Bulk outreach job failed: %s", e)
        finally:
            bg_db.close()

    thread = threading.Thread(target=run_in_background, daemon=True)
    thread.start()

    return {
        "message": f"Generating outreach for {len(candidate_ids)} candidates",
        "job_id": job_id,
        "total_count": len(candidate_ids),
        "status": "running",
    }


class BulkSendRequest(BaseModel):
    candidate_ids: Optional[List[str]] = None
    scheduled_for: Optional[str] = None
    send_all_drafted: bool = False
    cohort_name: Optional[str] = None  # Optional custom cohort label


@router.post("/candidates/bulk-send-outreach", tags=["outreach"])
def bulk_send_outreach_endpoint(
    body: Optional[BulkSendRequest] = None,
    # Keep query params for backwards compat (small lists, send_all_drafted, schedule)
    candidate_ids: Optional[List[str]] = Query(None),
    scheduled_for: Optional[str] = None,
    send_all_drafted: bool = False,
    db: Session = Depends(get_db),
):
    """
    Send or schedule drafted outreach emails.

    - Accepts candidate_ids in body (preferred for large lists) or query params.
    - If scheduled_for is provided (ISO datetime), schedules for later.
    - If scheduled_for is null, sends immediately.
    - If send_all_drafted=true and no candidate_ids, sends all drafted.
    """
    from app.models.candidate import OutreachStatus
    from app.services.bulk_outreach import bulk_send_outreach
    from app.db.base import SessionLocal
    import threading

    # Merge body and query params (body takes precedence)
    cohort_name = None
    if body:
        if body.candidate_ids:
            candidate_ids = body.candidate_ids
        if body.scheduled_for:
            scheduled_for = body.scheduled_for
        if body.send_all_drafted:
            send_all_drafted = body.send_all_drafted
        cohort_name = body.cohort_name

    # Resolve IDs
    if not candidate_ids and send_all_drafted:
        drafted = db.query(Candidate).filter(
            Candidate.outreach_status == OutreachStatus.drafted,
            Candidate.email.isnot(None),
        ).all()
        candidate_ids = [str(c.id) for c in drafted]

    if not candidate_ids:
        raise HTTPException(status_code=400, detail="No candidate IDs provided")

    # Generate cohort label if not provided
    if not cohort_name:
        from sqlalchemy import distinct, func as sa_func
        now = datetime.utcnow()
        date_prefix = now.strftime("%b %d")  # e.g. "Feb 12"
        # Count existing cohorts today to auto-increment
        existing = db.query(sa_func.count(distinct(Candidate.outreach_cohort))).filter(
            Candidate.outreach_cohort.like(f"{date_prefix}%")
        ).scalar() or 0
        cohort_name = f"{date_prefix} #{existing + 1}"

    # Assign cohort label to all candidates in this batch
    for cid in candidate_ids:
        c = db.query(Candidate).filter(Candidate.id == cid).first()
        if c:
            c.outreach_cohort = cohort_name
    db.commit()

    # If scheduling for later, just update the rows
    if scheduled_for:
        try:
            schedule_dt = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid scheduled_for datetime format")

        updated = 0
        for cid in candidate_ids:
            candidate = db.query(Candidate).filter(Candidate.id == cid).first()
            if candidate and candidate.outreach_status in (OutreachStatus.drafted, OutreachStatus.scheduled):
                candidate.outreach_status = OutreachStatus.scheduled
                candidate.outreach_scheduled_for = schedule_dt
                updated += 1

        db.commit()
        return {
            "message": f"Scheduled {updated} emails for {schedule_dt.isoformat()}",
            "scheduled_count": updated,
            "scheduled_for": schedule_dt.isoformat(),
        }

    # Send immediately in background
    ids_copy = list(candidate_ids)

    def send_in_background():
        result = bulk_send_outreach(ids_copy, SessionLocal, max_workers=1)
        from app.core.logging import get_logger
        get_logger(__name__).info("Bulk send result: %s", result)

    thread = threading.Thread(target=send_in_background, daemon=True)
    thread.start()

    return {
        "message": f"Sending {len(candidate_ids)} emails in background",
        "count": len(candidate_ids),
        "status": "sending",
    }


@router.delete("/outreach/clear", tags=["outreach"])
def clear_outreach_by_status(
    status: str = Query(..., description="'drafted' or 'scheduled'"),
    db: Session = Depends(get_db),
):
    """Clear all outreach for candidates with the given status.
    Resets outreach_status to null, clears subject/body/schedule fields.
    Only works for 'drafted' and 'scheduled' — refuses to clear 'sent'.
    """
    if status not in ('drafted', 'scheduled'):
        raise HTTPException(status_code=400, detail="Can only clear 'drafted' or 'scheduled'")

    count = db.query(Candidate).filter(
        Candidate.outreach_status == status
    ).update({
        Candidate.outreach_status: None,
        Candidate.outreach_subject: None,
        Candidate.outreach_body: None,
        Candidate.outreach_scheduled_for: None,
    }, synchronize_session='fetch')

    db.commit()
    logger.info("Cleared %d candidates with outreach_status=%s", count, status)
    return {"cleared": count, "status": status}


@router.put("/candidates/{candidate_id}/outreach-draft", tags=["outreach"])
def update_outreach_draft(
    candidate_id: UUID,
    subject: str = "",
    body: str = "",
    db: Session = Depends(get_db),
):
    """Update the subject/body of a drafted outreach email and set status to drafted."""
    from app.models.candidate import OutreachStatus

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if subject:
        candidate.outreach_subject = subject
    if body:
        candidate.outreach_body = body
    # Always set to drafted when saving new content — the frontend checklist
    # decides who to draft for, and generates cold vs follow-up accordingly
    candidate.outreach_status = OutreachStatus.drafted
    candidate.outreach_scheduled_for = None  # Clear any previous schedule
    candidate.updated_at = datetime.utcnow()
    db.commit()

    return {"message": "Draft updated", "candidate_id": str(candidate_id)}


# ===========================
# COHORT BUILDER ENDPOINTS
# ===========================

class CohortSegment(BaseModel):
    tier: Optional[str] = None
    archetype: Optional[str] = None
    location: Optional[str] = None
    role_ids: Optional[List[str]] = None  # Only include candidates matched to these roles
    count: int  # How many candidates to sample from this segment
    fill_remaining: bool = False  # If true, fill whatever is left after other segments

class BuildCohortRequest(BaseModel):
    segments: List[CohortSegment]
    total_size: int = 250  # Target cohort size


@router.post("/candidates/build-cohort", tags=["outreach"])
def build_cohort(
    request: BuildCohortRequest,
    db: Session = Depends(get_db),
):
    """
    Build a cohort of drafted candidates by sampling from segments.

    Each segment defines filters (tier, archetype, location) + a count.
    One segment can have fill_remaining=true to take whatever's left after other segments.
    Returns candidate IDs grouped by segment for preview.
    """
    from sqlalchemy import func

    # Base query: drafted OR un-outreached candidates with emails (exclude already sent)
    base_query = db.query(Candidate).filter(
        sa_or(
            Candidate.outreach_status == 'drafted',
            Candidate.outreach_status.is_(None),
        ),
        Candidate.email.isnot(None),
        Candidate.vibe_report.isnot(None),  # Must be analyzed
        Candidate.status != CandidateStatus.rejected,
    )

    used_ids: set = set()
    segment_results = []
    fill_segment_idx = None

    # First pass: handle all non-fill segments
    for idx, segment in enumerate(request.segments):
        if segment.fill_remaining:
            fill_segment_idx = idx
            segment_results.append(None)  # placeholder
            continue

        query = base_query
        if segment.tier:
            query = query.filter(Candidate.tier == segment.tier)
        if segment.archetype:
            query = query.filter(Candidate.archetype == segment.archetype)
        if segment.location:
            loc_raw = _get_raw_locations_for_normalized(db, segment.location)
            if loc_raw:
                query = query.filter(Candidate.location_country.in_(loc_raw))
            else:
                query = query.filter(Candidate.location_country == segment.location)
        if segment.role_ids:
            matched_ids = [r[0] for r in db.query(Match.candidate_id).filter(Match.role_id.in_(segment.role_ids)).distinct().all()]
            if matched_ids:
                query = query.filter(Candidate.id.in_(matched_ids))
            else:
                query = query.filter(False)  # No matches for these roles

        # Exclude already-used IDs
        if used_ids:
            query = query.filter(~Candidate.id.in_(used_ids))

        # Random sample
        sampled = query.order_by(func.random()).limit(segment.count).all()
        sampled_ids = [str(c.id) for c in sampled]
        used_ids.update(c.id for c in sampled)

        filters_desc = []
        if segment.tier:
            filters_desc.append(segment.tier)
        if segment.archetype:
            filters_desc.append(segment.archetype)
        if segment.location:
            filters_desc.append(segment.location)
        if segment.role_ids:
            role_names = []
            for rid in segment.role_ids:
                role_obj = db.query(Role).filter(Role.id == rid).first()
                if role_obj:
                    role_names.append(role_obj.title)
            if role_names:
                filters_desc.append(f"matched:{','.join(role_names)}")

        segment_results.append({
            "segment_index": idx,
            "filters": {"tier": segment.tier, "archetype": segment.archetype, "location": segment.location},
            "requested": segment.count,
            "matched": len(sampled_ids),
            "candidate_ids": sampled_ids,
            "label": " + ".join(filters_desc) if filters_desc else "All",
        })

    # Second pass: handle fill_remaining segment
    if fill_segment_idx is not None:
        segment = request.segments[fill_segment_idx]
        remaining_needed = request.total_size - len(used_ids)
        if remaining_needed < 0:
            remaining_needed = 0

        query = base_query
        if segment.tier:
            query = query.filter(Candidate.tier == segment.tier)
        if segment.archetype:
            query = query.filter(Candidate.archetype == segment.archetype)
        if segment.location:
            loc_raw = _get_raw_locations_for_normalized(db, segment.location)
            if loc_raw:
                query = query.filter(Candidate.location_country.in_(loc_raw))
            else:
                query = query.filter(Candidate.location_country == segment.location)
        if segment.role_ids:
            matched_ids = [r[0] for r in db.query(Match.candidate_id).filter(Match.role_id.in_(segment.role_ids)).distinct().all()]
            if matched_ids:
                query = query.filter(Candidate.id.in_(matched_ids))
            else:
                query = query.filter(False)
        if used_ids:
            query = query.filter(~Candidate.id.in_(used_ids))

        sampled = query.order_by(func.random()).limit(remaining_needed).all()
        sampled_ids = [str(c.id) for c in sampled]
        used_ids.update(c.id for c in sampled)

        filters_desc = []
        if segment.tier:
            filters_desc.append(segment.tier)
        if segment.archetype:
            filters_desc.append(segment.archetype)
        if segment.location:
            filters_desc.append(segment.location)
        if segment.role_ids:
            role_names = []
            for rid in segment.role_ids:
                role_obj = db.query(Role).filter(Role.id == rid).first()
                if role_obj:
                    role_names.append(role_obj.title)
            if role_names:
                filters_desc.append(f"matched:{','.join(role_names)}")

        segment_results[fill_segment_idx] = {
            "segment_index": fill_segment_idx,
            "filters": {"tier": segment.tier, "archetype": segment.archetype, "location": segment.location},
            "requested": remaining_needed,
            "matched": len(sampled_ids),
            "candidate_ids": sampled_ids,
            "label": ("Fill remaining" + (f" ({' + '.join(filters_desc)})" if filters_desc else "")),
            "fill_remaining": True,
        }

    all_ids = []
    for seg in segment_results:
        if seg:
            all_ids.extend(seg["candidate_ids"])

    return {
        "total_size": len(all_ids),
        "target_size": request.total_size,
        "segments": segment_results,
        "all_candidate_ids": all_ids,
    }


# ===========================
# REPLY TEXT BACKFILL
# ===========================

def _backfill_reply_text_from_resend(db: Session, api_key: str) -> list[dict]:
    """
    Shared helper: backfill warmup_reply_text for candidates who replied but have no text stored.
    Fetches received emails from Resend API and matches them to candidates by email address.
    Returns a list of dicts with details about each updated candidate.
    """
    import re
    import requests as http_requests
    from app.schemas.candidate import CandidateUpdate

    candidates_missing_text = db.query(Candidate).filter(
        Candidate.warmup_replied_at.isnot(None),
        (Candidate.warmup_reply_text.is_(None)) | (Candidate.warmup_reply_text == "")
    ).all()

    if not candidates_missing_text:
        return []

    missing_emails = {c.email: c for c in candidates_missing_text}
    logger.info("Backfilling reply text for %d candidates: %s", len(missing_emails), list(missing_emails.keys()))

    resp = http_requests.get(
        "https://api.resend.com/emails/receiving",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30
    )
    if resp.status_code != 200:
        logger.warning("Resend receiving API returned %d", resp.status_code)
        return []

    received_emails = resp.json().get("data", [])
    updated = []

    for received in received_emails:
        sender = received.get("from", "")
        if sender not in missing_emails:
            continue

        email_id = received["id"]
        detail_resp = http_requests.get(
            f"https://api.resend.com/emails/receiving/{email_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30
        )
        if detail_resp.status_code != 200:
            logger.warning("Failed to fetch email %s: %s", email_id, detail_resp.status_code)
            continue

        email_data = detail_resp.json()
        reply_text = email_data.get("text", "").strip()
        if not reply_text:
            reply_text = email_data.get("html", "").strip()

        if reply_text:
            clean = re.split(r'\nOn .+? wrote:\n', reply_text, maxsplit=1)[0].strip()
            if clean:
                reply_text = clean

            candidate = missing_emails[sender]
            update_data = CandidateUpdate(warmup_reply_text=reply_text)
            crud.update_candidate(db, candidate.id, update_data)
            updated.append({"username": candidate.github_username, "email": sender, "reply_preview": reply_text[:100]})
            logger.info("Backfilled reply text for %s: %s", candidate.github_username, reply_text[:80])
            del missing_emails[sender]

    return updated


def _backfill_followup_body_from_resend(db: Session, api_key: str) -> list[dict]:
    """
    Shared helper: backfill followup_body for candidates who were sent a follow-up
    but have no body stored. Fetches sent email content from Resend by screening_email_id.
    """
    import time
    import requests as http_requests
    from app.schemas.candidate import CandidateUpdate

    candidates_missing = db.query(Candidate).filter(
        Candidate.screening_link_sent_at.isnot(None),
        Candidate.screening_email_id.isnot(None),
        (Candidate.followup_body.is_(None)) | (Candidate.followup_body == "")
    ).all()

    if not candidates_missing:
        return []

    logger.info("Backfilling followup body for %d candidates", len(candidates_missing))
    updated = []

    for candidate in candidates_missing:
        try:
            resp = http_requests.get(
                f"https://api.resend.com/emails/{candidate.screening_email_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10
            )
            if resp.status_code == 429:
                logger.warning("Resend rate limit hit during followup backfill, stopping")
                break
            if resp.status_code != 200:
                logger.warning("Failed to fetch email %s: %s", candidate.screening_email_id, resp.status_code)
                continue

            data = resp.json()
            body = (data.get("text") or "").strip()

            if body:
                update_data = CandidateUpdate(followup_body=body)
                crud.update_candidate(db, candidate.id, update_data)
                updated.append({"username": candidate.github_username, "preview": body[:100]})
                logger.info("Backfilled followup body for %s", candidate.github_username)

            time.sleep(1)  # Rate limit courtesy
        except Exception as e:
            logger.warning("Error backfilling followup for %s: %s", candidate.github_username, e)

    return updated


def _backfill_sent_outreach_from_resend(db: Session, api_key: str) -> list[dict]:
    """
    Backfill sent_outreach_subject/body for candidates who were sent outreach
    but have no snapshot stored (because the columns didn't exist when they were sent,
    or because outreach_subject/body was overwritten by regeneration before the backfill ran).

    Fetches the original sent email from Resend using warmup_email_id.
    """
    import time
    import requests as http_requests

    candidates_missing = db.query(Candidate).filter(
        Candidate.warmup_email_sent_at.isnot(None),
        Candidate.warmup_email_id.isnot(None),
        (Candidate.sent_outreach_subject.is_(None)) | (Candidate.sent_outreach_subject == "")
    ).all()

    if not candidates_missing:
        return []

    logger.info("Backfilling sent_outreach from Resend for %d candidates", len(candidates_missing))
    updated = []

    for candidate in candidates_missing:
        try:
            resp = http_requests.get(
                f"https://api.resend.com/emails/{candidate.warmup_email_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10
            )
            if resp.status_code == 429:
                logger.warning("Resend rate limit hit during sent_outreach backfill, stopping")
                break
            if resp.status_code != 200:
                logger.warning("Failed to fetch email %s for %s: %s",
                               candidate.warmup_email_id, candidate.github_username, resp.status_code)
                continue

            data = resp.json()
            subject = (data.get("subject") or "").strip()
            body = (data.get("text") or "").strip()

            if subject and body:
                candidate.sent_outreach_subject = subject
                candidate.sent_outreach_body = body
                db.commit()
                updated.append({"username": candidate.github_username, "subject": subject[:60]})
                logger.info("Backfilled sent_outreach for %s: %s", candidate.github_username, subject[:60])

            time.sleep(0.5)  # Rate limit courtesy
        except Exception as e:
            db.rollback()
            logger.warning("Error backfilling sent_outreach for %s: %s", candidate.github_username, e)

    return updated


@router.post("/candidates/backfill-sent-outreach", tags=["outreach"])
def backfill_sent_outreach(db: Session = Depends(get_db)):
    """
    Backfill sent_outreach_subject/body from Resend API for all sent candidates
    missing their snapshot.
    """
    from app.core.config import settings

    if not settings.RESEND_API_KEY:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY not configured")

    updated = _backfill_sent_outreach_from_resend(db, settings.RESEND_API_KEY)
    if not updated:
        return {"status": "ok", "message": "No candidates need backfill", "updated": 0}
    return {"status": "ok", "updated": len(updated), "details": updated}


@router.post("/candidates/backfill-screening-transcripts", tags=["outreach"])
def backfill_screening_transcripts(db: Session = Depends(get_db)):
    """
    Re-fetch screening answer transcripts from Resend for candidates whose
    transcript looks like a quick acknowledgment (short, no substantive answers).

    Also backfills followup_body from followup_email_id for manual follow-ups
    that were sent but body not stored.
    """
    import re
    import time
    import requests as http_requests
    from app.core.config import settings
    from app.schemas.candidate import CandidateUpdate
    from app.services.screening_automation import parse_screening_answers

    if not settings.RESEND_API_KEY:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY not configured")

    results = {"screening_fixed": [], "followup_fixed": []}

    # PART 1: Fix screening transcripts that are just quick acks
    # Find candidates with short screening transcripts (likely quick acks)
    candidates_with_acks = db.query(Candidate).filter(
        Candidate.screening_status == "answered",
        Candidate.screening_transcript.isnot(None),
        Candidate.screening_transcript != "",
    ).all()

    short_ack_candidates = []
    for c in candidates_with_acks:
        transcript = c.screening_transcript.strip()
        # Quick acks: very short (< 80 chars), or just "Thanks", "Thank you", etc.
        is_short = len(transcript) < 80
        is_ack = any(ack in transcript.lower() for ack in ['thanks', 'thank you', 'got it', 'will do', 'sounds good'])
        no_substance = not any(kw in transcript.lower() for kw in ['remote', 'onsite', 'hybrid', 'timeline', 'looking', 'exploring', 'visa', 'citizen', 'authorization', 'salary', 'comp', 'resume', 'attached', 'relocat'])
        if is_short and is_ack and no_substance:
            short_ack_candidates.append(c)

    if short_ack_candidates:
        logger.info("Found %d candidates with quick-ack screening transcripts, fetching real answers from Resend", len(short_ack_candidates))

        # Fetch all received emails from Resend
        resp = http_requests.get(
            "https://api.resend.com/emails/receiving",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            timeout=30
        )
        if resp.status_code == 200:
            received_emails = resp.json().get("data", [])
            # Group received emails by sender
            emails_by_sender = {}
            for email in received_emails:
                sender = email.get("from", "")
                if sender not in emails_by_sender:
                    emails_by_sender[sender] = []
                emails_by_sender[sender].append(email)

            for candidate in short_ack_candidates:
                if candidate.email not in emails_by_sender:
                    continue

                # Get all emails from this sender, sorted by date (newest first)
                sender_emails = emails_by_sender[candidate.email]
                all_reply_texts = []

                for email_meta in sender_emails:
                    try:
                        detail_resp = http_requests.get(
                            f"https://api.resend.com/emails/receiving/{email_meta['id']}",
                            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                            timeout=10
                        )
                        if detail_resp.status_code != 200:
                            continue
                        email_data = detail_resp.json()
                        text = (email_data.get("text") or "").strip()
                        if not text:
                            text = (email_data.get("html") or "").strip()
                        if text:
                            clean = re.split(r'\nOn .+? wrote:\n', text, maxsplit=1)[0].strip()
                            if clean:
                                all_reply_texts.append(clean)
                        time.sleep(0.3)
                    except Exception as e:
                        logger.warning("Error fetching email for %s: %s", candidate.github_username, e)

                # Find the substantive reply (longest one that's not the first reply or the ack)
                first_reply = candidate.warmup_reply_text or ""
                best_screening_answer = ""
                for text in all_reply_texts:
                    # Skip if it's the same as the first reply
                    if text.strip()[:50] == first_reply.strip()[:50]:
                        continue
                    # Skip if it's the same as the current ack transcript
                    if text.strip()[:50] == candidate.screening_transcript.strip()[:50]:
                        continue
                    # Pick the longest remaining reply as the real screening answer
                    if len(text) > len(best_screening_answer):
                        best_screening_answer = text

                if best_screening_answer and len(best_screening_answer) > len(candidate.screening_transcript):
                    # Re-parse the real screening answer
                    parsed = parse_screening_answers(best_screening_answer, candidate.name)
                    update_data = CandidateUpdate(
                        screening_transcript=best_screening_answer,
                        screening_data=parsed,
                        screening_summary=parsed.get("summary", ""),
                    )
                    crud.update_candidate(db, candidate.id, update_data)
                    results["screening_fixed"].append({
                        "username": candidate.github_username,
                        "old_transcript": candidate.screening_transcript[:60],
                        "new_transcript": best_screening_answer[:100],
                    })
                    logger.info("Fixed screening transcript for %s: '%s' -> '%s'",
                                candidate.github_username, candidate.screening_transcript[:40], best_screening_answer[:60])

    # PART 2: Backfill followup_body for manual follow-ups sent via "Write Follow-up"
    candidates_missing_followup = db.query(Candidate).filter(
        Candidate.followup_sent_at.isnot(None),
        Candidate.followup_email_id.isnot(None),
        (Candidate.followup_body.is_(None)) | (Candidate.followup_body == "")
    ).all()

    for candidate in candidates_missing_followup:
        try:
            resp = http_requests.get(
                f"https://api.resend.com/emails/{candidate.followup_email_id}",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                timeout=10
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            subject = (data.get("subject") or "").strip()
            body = (data.get("text") or "").strip()
            if body:
                full_body = f"Subject: {subject}\n\n{body}" if subject else body
                update_data = CandidateUpdate(followup_body=full_body)
                crud.update_candidate(db, candidate.id, update_data)
                results["followup_fixed"].append({
                    "username": candidate.github_username,
                    "preview": body[:80],
                })
                logger.info("Backfilled followup_body for %s", candidate.github_username)
            time.sleep(0.5)
        except Exception as e:
            logger.warning("Error backfilling followup for %s: %s", candidate.github_username, e)

    total_fixed = len(results["screening_fixed"]) + len(results["followup_fixed"])
    if total_fixed == 0:
        return {"status": "ok", "message": "No candidates need backfill", "updated": 0}
    return {"status": "ok", "updated": total_fixed, "details": results}


@router.post("/candidates/backfill-reply-text", tags=["outreach"])
def backfill_reply_text(db: Session = Depends(get_db)):
    """
    Backfill warmup_reply_text for candidates who replied but have no reply text stored.
    Fetches received emails from Resend API and matches them to candidates by email address.
    """
    from app.core.config import settings

    if not settings.RESEND_API_KEY:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY not configured")

    updated = _backfill_reply_text_from_resend(db, settings.RESEND_API_KEY)
    if not updated:
        return {"status": "ok", "message": "No candidates need backfill", "updated": 0}
    return {"status": "ok", "updated": len(updated), "details": updated}


@router.post("/candidates/{candidate_id}/backfill-email-events", tags=["outreach"])
def backfill_candidate_email_events(candidate_id: UUID, db: Session = Depends(get_db)):
    """
    Backfill email_events from scattered candidate fields for a single candidate.
    Creates event records from warmup_email_sent_at, warmup_replied_at,
    screening_link_sent_at, screening_completed_at, and followup_sent_at.
    Skips if candidate already has email_events.
    """
    from app.models.email_event import EmailEvent, EmailEventType
    from app.services.email_events import append_email_event

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Check if already has events
    existing = db.query(EmailEvent).filter(EmailEvent.candidate_id == candidate_id).count()
    if existing > 0:
        return {"status": "skipped", "message": f"Candidate already has {existing} email events"}

    created = 0

    # 1. Initial outreach sent
    if candidate.warmup_email_sent_at:
        append_email_event(
            db, candidate_id, EmailEventType.outreach_sent,
            occurred_at=candidate.warmup_email_sent_at,
            subject=candidate.sent_outreach_subject or candidate.outreach_subject,
            body=candidate.sent_outreach_body or candidate.outreach_body,
            resend_email_id=candidate.warmup_email_id,
            message_id=candidate.warmup_message_id,
        )
        created += 1

    # 2. Email opened (warmup)
    if candidate.warmup_email_opened_at:
        append_email_event(
            db, candidate_id, EmailEventType.email_opened,
            occurred_at=candidate.warmup_email_opened_at,
            metadata={"email_type": "warmup"},
        )
        created += 1

    # 3. Candidate replied
    if candidate.warmup_replied_at:
        append_email_event(
            db, candidate_id, EmailEventType.candidate_replied,
            occurred_at=candidate.warmup_replied_at,
            body=candidate.warmup_reply_text,
        )
        created += 1

    # 4. Screening questions sent
    if candidate.screening_link_sent_at:
        screening_text = candidate.screening_body
        # Legacy: if screening_body not set, followup_body might hold screening text
        # (only if no manual follow-up was sent afterwards)
        if not screening_text and candidate.followup_body and not candidate.followup_sent_at:
            screening_text = candidate.followup_body
        append_email_event(
            db, candidate_id, EmailEventType.screening_sent,
            occurred_at=candidate.screening_link_sent_at,
            body=screening_text,
            resend_email_id=candidate.screening_email_id,
        )
        created += 1

    # 5. Screening email opened
    if candidate.screening_email_opened_at:
        append_email_event(
            db, candidate_id, EmailEventType.email_opened,
            occurred_at=candidate.screening_email_opened_at,
            metadata={"email_type": "screening"},
        )
        created += 1

    # 6. Screening answered
    if candidate.screening_completed_at and candidate.screening_transcript:
        append_email_event(
            db, candidate_id, EmailEventType.screening_answered,
            occurred_at=candidate.screening_completed_at,
            body=candidate.screening_transcript,
            metadata=candidate.screening_data,
        )
        created += 1

    # 7. Manual follow-up sent
    if candidate.followup_sent_at and candidate.followup_body:
        append_email_event(
            db, candidate_id, EmailEventType.followup_sent,
            occurred_at=candidate.followup_sent_at,
            body=candidate.followup_body,
            resend_email_id=candidate.followup_email_id,
        )
        created += 1

    db.commit()
    return {"status": "ok", "created": created, "candidate": candidate.name or candidate.github_username}


@router.post("/candidates/backfill-all-email-events", tags=["outreach"])
def backfill_all_email_events(db: Session = Depends(get_db)):
    """
    Backfill email_events for ALL candidates who have outreach data but no email_events.
    """
    from app.models.email_event import EmailEvent
    from sqlalchemy import func

    # Find candidates with outreach activity but no email_events
    candidates_with_events = (
        db.query(EmailEvent.candidate_id)
        .distinct()
        .subquery()
    )
    candidates_needing_backfill = (
        db.query(Candidate)
        .filter(Candidate.warmup_email_sent_at.isnot(None))
        .filter(~Candidate.id.in_(db.query(candidates_with_events.c.candidate_id)))
        .all()
    )

    results = []
    for candidate in candidates_needing_backfill:
        try:
            result = backfill_candidate_email_events(candidate.id, db)
            results.append({"name": candidate.name or candidate.github_username, **result})
        except Exception as e:
            results.append({"name": candidate.name or candidate.github_username, "status": "error", "detail": str(e)})

    return {"status": "ok", "total": len(results), "results": results}


@router.delete("/email-events/{event_id}", tags=["outreach"])
def delete_email_event(event_id: UUID, db: Session = Depends(get_db)):
    """Delete a single email event by ID (admin fix tool)."""
    from app.models.email_event import EmailEvent
    event = db.query(EmailEvent).filter(EmailEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    db.delete(event)
    db.commit()
    return {"status": "deleted", "event_type": event.event_type.value, "candidate_id": str(event.candidate_id)}


def _fetch_all_sent_emails_from_resend():
    """
    Paginate through Resend's GET /emails endpoint and return ALL sent emails.
    Returns a dict mapping recipient email (lowercase) -> list of sent email summaries.
    Each summary: {id, to, subject, created_at}
    """
    import time
    import requests as http_requests
    from app.core.config import settings

    headers = {"Authorization": f"Bearer {settings.RESEND_API_KEY}"}
    by_recipient = {}  # email -> [items]
    cursor = None
    page = 0
    while page < 100:  # safety cap: 100 pages × 100 = 10,000 emails max
        url = "https://api.resend.com/emails?limit=100"
        if cursor:
            url += f"&after={cursor}"
        try:
            resp = http_requests.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                logger.warning("Failed to list sent emails (page %d): %s", page, resp.status_code)
                break
            payload = resp.json()
            items = payload.get("data", [])
            if not items:
                break
            for item in items:
                to_list = item.get("to") or []
                for addr in to_list:
                    raw = (addr or "").strip().lower()
                    if not raw:
                        continue
                    # Extract email from "Name <email>" format if needed
                    if "<" in raw and ">" in raw:
                        key = raw.split("<")[-1].rstrip(">").strip()
                    else:
                        key = raw
                    if key:
                        by_recipient.setdefault(key, []).append(item)
            cursor = items[-1].get("id")
            if not payload.get("has_more"):
                break
            page += 1
            time.sleep(0.3)
        except Exception as e:
            logger.warning("Error listing sent emails (page %d): %s", page, e)
            break
    logger.info("Fetched %d pages of sent emails, %d unique recipients",
                page + 1, len(by_recipient))
    return by_recipient


@router.post("/candidates/{candidate_id}/rebuild-email-chain", tags=["outreach"])
def rebuild_email_chain_endpoint(candidate_id: UUID, db: Session = Depends(get_db)):
    """Nuclear rebuild of a candidate's email chain from Resend."""
    return rebuild_email_chain_from_resend(candidate_id, db)


def rebuild_email_chain_from_resend(candidate_id: UUID, db, sent_cache: dict = None):
    """
    Nuclear rebuild: delete all email_events for a candidate, then reconstruct
    the full chain from Resend (the single source of truth).

    1. Fetch ALL SENT emails to this candidate from Resend
    2. Fetch ALL RECEIVED emails from Resend receiving API
    3. Sort chronologically
    4. Classify and create events fresh
    5. Re-parse screening answers from correct email body
    """
    import re
    import time
    import requests as http_requests
    from app.core.config import settings
    from app.models.email_event import EmailEvent

    if not settings.RESEND_API_KEY:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY not configured")

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    headers = {"Authorization": f"Bearer {settings.RESEND_API_KEY}"}

    # ── Step 1: Collect ALL emails from Resend ──
    # Each entry: {timestamp, direction, type_hint, subject, body, resend_id}
    all_emails = []

    def _parse_ts(ts_str):
        """Parse timestamp string into a naive UTC datetime for consistent sorting."""
        if not ts_str:
            return None
        if not isinstance(ts_str, str):
            return None
        import re as _ts_re
        # Normalize: space→T, strip timezone completely (we treat everything as UTC)
        normalized = ts_str.strip()
        normalized = _ts_re.sub(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:)', r'\1T\2', normalized)
        # Remove timezone suffix entirely (+00, +00:00, Z) — we want naive UTC
        normalized = _ts_re.sub(r'[+-]\d{2}(:\d{2})?$', '', normalized)
        normalized = normalized.rstrip('Z')
        # Pad fractional seconds to 6 digits (Python 3.10 fromisoformat needs 0, 3, or 6)
        m = _ts_re.search(r'\.(\d+)$', normalized)
        if m:
            frac = m.group(1)
            if len(frac) not in (0, 3, 6):
                normalized = normalized[:m.start(1)] + frac.ljust(6, '0')[:6]
        try:
            return datetime.fromisoformat(normalized)
        except (ValueError, AttributeError):
            pass
        # Try RFC 2822: "Mon, 17 Feb 2026 19:22:54 +0000"
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(ts_str)
            return dt.replace(tzinfo=None)
        except (ValueError, TypeError):
            pass
        return None

    fetch_errors = []  # collect errors for debug output

    def _fetch_sent(resend_id, type_hint, fallback_ts=None):
        """Fetch a sent email by its Resend ID, with retry on rate limit."""
        if not resend_id:
            return
        for attempt in range(3):
            try:
                resp = http_requests.get(
                    f"https://api.resend.com/emails/{resend_id}",
                    headers=headers, timeout=10,
                )
                if resp.status_code == 429:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning("Rate limited on %s, waiting %ds (attempt %d)", resend_id, wait, attempt + 1)
                    time.sleep(wait)
                    continue
                if resp.status_code != 200:
                    err = f"{resend_id}: HTTP {resp.status_code}"
                    logger.warning("Failed to fetch sent email %s: %s %s", resend_id, resp.status_code, resp.text[:200])
                    fetch_errors.append(err)
                    return
                data = resp.json()
                ts = _parse_ts(data.get("created_at"))
                if ts is None and fallback_ts is not None:
                    ts = fallback_ts.replace(tzinfo=None) if hasattr(fallback_ts, 'tzinfo') and fallback_ts.tzinfo else fallback_ts
                all_emails.append({
                    "timestamp": ts,
                    "direction": "outbound",
                    "type_hint": type_hint,
                    "subject": (data.get("subject") or "").strip(),
                    "body": (data.get("text") or "").strip(),
                    "resend_id": resend_id,
                })
                time.sleep(0.5)
                return
            except Exception as e:
                logger.warning("Error fetching sent email %s (attempt %d): %s", resend_id, attempt + 1, e)
                time.sleep(1)
        fetch_errors.append(f"{resend_id}: failed after 3 attempts")

    # ── Fetch ALL outbound emails sent to this candidate from Resend ──
    # Use pre-fetched cache if available (rebuild-all passes this),
    # otherwise fetch the full list for just this candidate.
    sent_ids_seen = set()

    if candidate.email:
        if sent_cache is not None:
            # Use pre-fetched cache
            candidate_sent = sent_cache.get(candidate.email.lower(), [])
        else:
            # Fetch just for this candidate by paginating the full list
            candidate_sent = []
            try:
                cursor = None
                page = 0
                while page < 50:
                    url = "https://api.resend.com/emails?limit=100"
                    if cursor:
                        url += f"&after={cursor}"
                    resp = http_requests.get(url, headers=headers, timeout=30)
                    if resp.status_code != 200:
                        logger.warning("Failed to list sent emails (page %d): %s", page, resp.status_code)
                        break
                    payload = resp.json()
                    items = payload.get("data", [])
                    if not items:
                        break
                    for item in items:
                        to_list = item.get("to") or []
                        match = any(
                            candidate.email.lower() in (addr or "").lower()
                            for addr in to_list
                        )
                        if match:
                            candidate_sent.append(item)
                    cursor = items[-1].get("id")
                    if not payload.get("has_more"):
                        break
                    page += 1
                    time.sleep(0.3)
            except Exception as e:
                logger.warning("Error listing sent emails: %s", e)

        logger.info("Resend list: found %d sent emails for %s", len(candidate_sent), candidate.email)
        for item in candidate_sent:
            rid = item.get("id")
            if rid in sent_ids_seen:
                continue
            sent_ids_seen.add(rid)
            before_len = len(all_emails)
            _fetch_sent(rid, "__auto__", None)
            # Tag emails added from the list API
            for e in all_emails[before_len:]:
                e["_from_list"] = True

    # Also fetch by stored IDs as fallback (in case they weren't in the list)
    for rid, hint, fts in [
        (candidate.warmup_email_id, "outreach_sent", candidate.warmup_email_sent_at),
        (candidate.screening_email_id, "screening_sent", candidate.screening_link_sent_at),
        (candidate.followup_email_id, "followup_sent", candidate.followup_sent_at),
    ]:
        if rid and rid not in sent_ids_seen:
            sent_ids_seen.add(rid)
            _fetch_sent(rid, hint, fts)
        elif rid and rid in sent_ids_seen:
            logger.info("Stored ID %s (%s) already found via list API", rid, hint)

    # ── Now classify the __auto__ outbound emails properly ──
    # We need to assign the right type_hint to each outbound email.
    # Known IDs get their explicit type; others get classified by content.
    known_ids = {
        candidate.warmup_email_id: "outreach_sent",
        candidate.screening_email_id: "screening_sent",
        candidate.followup_email_id: "followup_sent",
    }
    for email in all_emails:
        if email["direction"] != "outbound":
            continue
        if email["type_hint"] != "__auto__":
            continue
        rid = email["resend_id"]
        if rid in known_ids:
            email["type_hint"] = known_ids[rid]
        else:
            body_lower = (email["body"] or "").lower()
            subj = (email["subject"] or "").lower()
            # Screening questions detection (auto-sent after candidate first reply)
            if ("open to onsite" in body_lower
                    or ("timeline" in body_lower and "visa" in body_lower)
                    or "could you share a few quick details" in body_lower):
                email["type_hint"] = "screening_sent"
            else:
                # Default: follow-up (covers both auto-confirmations and manual follow-ups)
                email["type_hint"] = "followup_sent"

    # Fetch ALL inbound emails from Resend receiving API
    if candidate.email:
        try:
            recv_resp = http_requests.get(
                "https://api.resend.com/emails/receiving",
                headers=headers, timeout=30,
            )
            if recv_resp.status_code == 200:
                for recv_email in recv_resp.json().get("data", []):
                    if recv_email.get("from") != candidate.email:
                        continue
                    recv_id = recv_email.get("id")
                    # Try timestamp from list-level data first
                    list_ts = (
                        _parse_ts(recv_email.get("created_at"))
                        or _parse_ts(recv_email.get("date"))
                        or _parse_ts(recv_email.get("received_at"))
                    )
                    try:
                        detail_resp = http_requests.get(
                            f"https://api.resend.com/emails/receiving/{recv_id}",
                            headers=headers, timeout=10,
                        )
                        if detail_resp.status_code != 200:
                            continue
                        data = detail_resp.json()
                        # Try every plausible timestamp field from detail response
                        detail_ts = (
                            _parse_ts(data.get("created_at"))
                            or _parse_ts(data.get("date"))
                            or _parse_ts(data.get("received_at"))
                            or _parse_ts(data.get("timestamp"))
                        )
                        ts = detail_ts or list_ts
                        debug_fields = None
                        if not ts:
                            raw_val = data.get("created_at")
                            logger.info("No timestamp for inbound %s: raw created_at=%r type=%s",
                                        recv_id, raw_val, type(raw_val).__name__)
                            debug_fields = {"keys": list(data.keys()), "raw_created_at": str(raw_val)}
                        all_emails.append({
                            "timestamp": ts,
                            "direction": "inbound",
                            "type_hint": None,  # classified below
                            "subject": (data.get("subject") or "").strip(),
                            "body": (data.get("text") or data.get("html") or "").strip(),
                            "resend_id": recv_id,
                            "_debug_fields": debug_fields,
                        })
                        time.sleep(0.3)
                    except Exception as e:
                        logger.warning("Error fetching received email %s: %s", recv_id, e)
        except Exception as e:
            logger.warning("Error listing received emails: %s", e)

    if not all_emails:
        return {"status": "no_emails_found", "candidate": candidate.name or candidate.github_username}

    # ── Step 2: Sort by timestamp ──
    # For emails with no timestamp, use datetime.max so they sort to the end
    # (better to show unknown-time emails last than first)
    all_emails.sort(key=lambda e: e["timestamp"] or datetime.max)

    # ── Step 3: Delete old events ──
    deleted = db.query(EmailEvent).filter(EmailEvent.candidate_id == candidate_id).delete()

    # ── Step 4: Create fresh events in order ──
    created_events = []
    screening_sent_ts = None
    has_screening_answer = False
    seen_confirmation = False  # Track if we already emitted an auto-confirmation

    for email in all_emails:
        ts = email["timestamp"]
        direction = email["direction"]
        body = email["body"]

        if direction == "outbound":
            event_type = EmailEventType[email["type_hint"]]  # outreach_sent, screening_sent, followup_sent
            if email["type_hint"] == "screening_sent":
                screening_sent_ts = ts
            # Check if this is the auto-confirmation (screening_confirmation)
            # The auto-generated confirmation always contains
            # "Appreciate you sharing all of that" — use this exact phrase
            # to distinguish from manual follow-ups that might use similar words.
            metadata = None
            is_auto_confirmation = False
            if email["type_hint"] == "followup_sent":
                body_lower = (body or "").lower()
                if "appreciate you sharing all of that" in body_lower:
                    is_auto_confirmation = True
                    metadata = {"type": "screening_confirmation"}

            # Skip duplicate auto-confirmations (caused by old webhook bug
            # re-triggering process_screening_reply_delayed on short replies)
            if is_auto_confirmation:
                if seen_confirmation:
                    logger.info("Skipping duplicate auto-confirmation for %s (resend_id=%s)",
                                candidate.name, email["resend_id"])
                    continue
                seen_confirmation = True
        else:
            # Inbound — classify based on context
            clean = re.split(r'\n\s*>?\s*On .+? wrote:\s*\n', body, maxsplit=1)[0].strip()
            clean = "\n".join(
                line for line in clean.split("\n")
                if not line.strip().startswith(">")
            ).strip()

            if screening_sent_ts and not has_screening_answer and len(clean) >= 80:
                event_type = EmailEventType.screening_answered
                has_screening_answer = True
            else:
                event_type = EmailEventType.candidate_replied
            metadata = None

        evt = append_email_event(
            db, candidate_id, event_type,
            occurred_at=ts,
            subject=email["subject"],
            body=body,
            resend_email_id=email["resend_id"],
            metadata=metadata,
        )
        created_events.append({
            "seq": evt.sequence,
            "event_type": event_type.value,
            "occurred_at": ts.isoformat() if ts else None,
            "subject": email["subject"][:80] if email["subject"] else None,
            "body_preview": (body or "")[:120],
        })

    # ── Step 4b: Re-insert open events from legacy candidate fields ──
    # Resend sent/received APIs don't include open tracking data, so we
    # restore opens from the candidate's legacy timestamp fields.
    if candidate.warmup_email_opened_at:
        # Find the outreach_sent event to insert after
        outreach_evt = next(
            (e for e in created_events if e["event_type"] == "outreach_sent"), None
        )
        evt = append_email_event(
            db, candidate_id, EmailEventType.email_opened,
            occurred_at=candidate.warmup_email_opened_at,
            metadata={"email_type": "warmup"},
        )
        created_events.append({
            "seq": evt.sequence,
            "event_type": "email_opened",
            "occurred_at": candidate.warmup_email_opened_at.isoformat() if candidate.warmup_email_opened_at else None,
            "subject": None,
            "body_preview": "",
        })

    if candidate.screening_email_opened_at:
        evt = append_email_event(
            db, candidate_id, EmailEventType.email_opened,
            occurred_at=candidate.screening_email_opened_at,
            metadata={"email_type": "screening"},
        )
        created_events.append({
            "seq": evt.sequence,
            "event_type": "email_opened",
            "occurred_at": candidate.screening_email_opened_at.isoformat() if candidate.screening_email_opened_at else None,
            "subject": None,
            "body_preview": "",
        })

    db.commit()

    # ── Step 5: Re-parse screening answers if we found a screening_answered event ──
    # Find the event we classified as screening_answered from created_events
    screening_reparsed = False
    if has_screening_answer:
        for ev_info, email in zip(created_events, all_emails):
            if ev_info["event_type"] == "screening_answered":
                body = email["body"]
                # Strip quoted text to get just the candidate's answer
                clean = re.split(r'\n\s*>?\s*On .+? wrote:\s*\n', body, maxsplit=1)[0].strip()
                clean = "\n".join(
                    line for line in clean.split("\n")
                    if not line.strip().startswith(">")
                ).strip()
                try:
                    from app.services.screening_automation import parse_screening_answers
                    parsed = parse_screening_answers(clean, candidate.name or "")
                    from app.schemas.candidate import CandidateUpdate as CU
                    update = CU(
                        screening_data=parsed,
                        screening_summary=parsed.get("summary", ""),
                        screening_status="answered",
                        screening_completed_at=email["timestamp"].isoformat() if email["timestamp"] else datetime.utcnow().isoformat(),
                        status="ready",
                    )
                    crud.update_candidate(db, candidate_id, update)
                    db.commit()
                    screening_reparsed = True
                    logger.info("Re-parsed screening answers for %s", candidate.name)
                except Exception as e:
                    logger.error("Failed to re-parse screening answers for %s: %s", candidate.name, e)
                break

    return {
        "status": "rebuilt",
        "candidate": candidate.name or candidate.github_username,
        "old_events_deleted": deleted,
        "new_events_created": len(created_events),
        "chain": created_events,
        "screening_reparsed": screening_reparsed,
    }


@router.post("/candidates/rebuild-all-email-chains", tags=["outreach"])
def rebuild_all_email_chains(db: Session = Depends(get_db)):
    """
    Nuclear rebuild of email chains for ALL candidates with outreach activity.
    Pre-fetches the full Resend sent-email list once, then rebuilds each candidate.
    """
    from app.core.config import settings

    candidates = (
        db.query(Candidate)
        .filter(Candidate.warmup_email_sent_at.isnot(None))
        .all()
    )

    # Pre-fetch ALL sent emails from Resend once (avoids N×pagination)
    sent_cache = {}
    if settings.RESEND_API_KEY:
        try:
            sent_cache = _fetch_all_sent_emails_from_resend()
        except Exception as e:
            logger.error("Failed to pre-fetch sent emails: %s", e)

    results = []
    for candidate in candidates:
        try:
            result = rebuild_email_chain_from_resend(candidate.id, db, sent_cache=sent_cache)
            results.append({
                "name": candidate.name or candidate.github_username,
                **result,
            })
        except Exception as e:
            results.append({
                "name": candidate.name or candidate.github_username,
                "status": "error",
                "detail": str(e),
            })

    rebuilt_count = sum(1 for r in results if r.get("status") == "rebuilt")
    reparsed_count = sum(1 for r in results if r.get("screening_reparsed"))

    return {
        "total": len(results),
        "rebuilt": rebuilt_count,
        "screening_reparsed": reparsed_count,
        "results": results,
    }


@router.post("/candidates/backfill-open-events", tags=["outreach"])
def backfill_open_events(db: Session = Depends(get_db)):
    """
    Backfill email_opened events from Resend for all sent candidates.

    For each candidate with sent emails, checks each stored resend_email_id
    against Resend's GET /emails/{id} API. If last_event is 'opened' or
    'clicked' but no email_opened event exists in the chain for that email,
    creates one.

    Also backfills from legacy warmup_email_opened_at / screening_email_opened_at
    fields.
    """
    import time
    import requests as http_requests
    from app.core.config import settings
    from app.models.email_event import EmailEvent
    from app.schemas.candidate import CandidateUpdate

    if not settings.RESEND_API_KEY:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY not configured")

    headers = {"Authorization": f"Bearer {settings.RESEND_API_KEY}"}

    # Get all candidates with outreach activity
    candidates = (
        db.query(Candidate)
        .filter(Candidate.warmup_email_sent_at.isnot(None))
        .all()
    )

    results = {"total": len(candidates), "opens_created": 0, "legacy_created": 0, "errors": [], "details": []}

    for candidate in candidates:
        # Collect all resend_email_ids from this candidate's email_events
        sent_events = (
            db.query(EmailEvent)
            .filter(
                EmailEvent.candidate_id == candidate.id,
                EmailEvent.event_type.in_([
                    EmailEventType.outreach_sent,
                    EmailEventType.screening_sent,
                    EmailEventType.followup_sent,
                    EmailEventType.role_pitch_sent,
                ]),
                EmailEvent.resend_email_id.isnot(None),
            )
            .all()
        )

        # Get existing open events for this candidate
        existing_opens = (
            db.query(EmailEvent)
            .filter(
                EmailEvent.candidate_id == candidate.id,
                EmailEvent.event_type == EmailEventType.email_opened,
            )
            .all()
        )
        existing_open_resend_ids = {e.resend_email_id for e in existing_opens if e.resend_email_id}

        for sent_evt in sent_events:
            rid = sent_evt.resend_email_id
            if rid in existing_open_resend_ids:
                continue  # Already have an open event for this email

            # Check Resend API for open status
            try:
                resp = http_requests.get(
                    f"https://api.resend.com/emails/{rid}",
                    headers=headers, timeout=10,
                )
                if resp.status_code == 429:
                    time.sleep(2)
                    resp = http_requests.get(
                        f"https://api.resend.com/emails/{rid}",
                        headers=headers, timeout=10,
                    )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                last_event = data.get("last_event", "")

                if last_event in ("opened", "clicked"):
                    email_type = sent_evt.event_type.value.replace("_sent", "")
                    # Use occurred_at from the sent event + 1 hour as approximate open time
                    # (Resend doesn't return exact open timestamp via API)
                    approx_open_time = (sent_evt.occurred_at + timedelta(hours=1)) if sent_evt.occurred_at else datetime.utcnow()
                    # But prefer legacy fields if available
                    if email_type == "outreach" and candidate.warmup_email_opened_at:
                        approx_open_time = candidate.warmup_email_opened_at
                    elif email_type == "screening" and candidate.screening_email_opened_at:
                        approx_open_time = candidate.screening_email_opened_at

                    append_email_event(
                        db, candidate.id, EmailEventType.email_opened,
                        occurred_at=approx_open_time,
                        resend_email_id=rid,
                        metadata={"email_type": email_type},
                    )
                    results["opens_created"] += 1
                    results["details"].append(f"{candidate.name}: {email_type} opened")

                time.sleep(0.3)  # Rate limit
            except Exception as e:
                results["errors"].append(f"{candidate.name} ({rid}): {str(e)}")

        # Also check legacy fields as fallback
        has_any_open = len(existing_opens) > 0 or results["opens_created"] > 0
        if not has_any_open:
            if candidate.warmup_email_opened_at:
                append_email_event(
                    db, candidate.id, EmailEventType.email_opened,
                    occurred_at=candidate.warmup_email_opened_at,
                    resend_email_id=candidate.warmup_email_id,
                    metadata={"email_type": "warmup"},
                )
                results["legacy_created"] += 1

            if candidate.screening_email_opened_at:
                append_email_event(
                    db, candidate.id, EmailEventType.email_opened,
                    occurred_at=candidate.screening_email_opened_at,
                    resend_email_id=candidate.screening_email_id,
                    metadata={"email_type": "screening"},
                )
                results["legacy_created"] += 1

    db.commit()
    return results


@router.post("/candidates/{candidate_id}/backfill-resume", tags=["outreach"])
def backfill_candidate_resume(candidate_id: UUID, db: Session = Depends(get_db)):
    """
    Re-fetch resume PDF from Resend inbound emails for a specific candidate.
    Searches Resend receiving API for emails from this candidate's email address,
    downloads any PDF attachments, extracts text, and stores on the candidate.
    """
    import io
    import requests as http_requests
    from app.core.config import settings
    from app.schemas.candidate import CandidateUpdate

    if not settings.RESEND_API_KEY:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY not configured")

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if not candidate.email:
        raise HTTPException(status_code=400, detail="Candidate has no email address")

    # Fetch all received emails from Resend
    resp = http_requests.get(
        "https://api.resend.com/emails/receiving",
        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        timeout=30
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Resend API error: {resp.status_code}")

    received_emails = resp.json().get("data", [])
    candidate_emails = [e for e in received_emails if e.get("from") == candidate.email]

    if not candidate_emails:
        return {"status": "no_emails", "message": f"No inbound emails found from {candidate.email}"}

    # Check each email for PDF attachments
    for recv_email in candidate_emails:
        email_id = recv_email["id"]
        detail_resp = http_requests.get(
            f"https://api.resend.com/emails/receiving/{email_id}",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            timeout=15
        )
        if detail_resp.status_code != 200:
            continue

        email_detail = detail_resp.json()
        attachments = email_detail.get("attachments", [])
        pdf_attachments = [a for a in attachments if
                          a.get("content_type", "").lower() == "application/pdf"
                          or (a.get("filename") or "").lower().endswith(".pdf")]

        if not pdf_attachments:
            continue

        for pdf_att in pdf_attachments:
            att_id = pdf_att.get("id")
            if not att_id:
                continue

            att_resp = http_requests.get(
                f"https://api.resend.com/emails/receiving/{email_id}/attachments/{att_id}",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                timeout=15
            )
            if att_resp.status_code != 200:
                continue

            att_data = att_resp.json()
            download_url = att_data.get("download_url")
            if not download_url:
                continue

            pdf_resp = http_requests.get(download_url, timeout=30)
            if pdf_resp.status_code != 200:
                continue

            pdf_bytes = pdf_resp.content
            if len(pdf_bytes) > 10 * 1024 * 1024:
                continue

            try:
                from PyPDF2 import PdfReader
                pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
                resume_text = ""
                for page in pdf_reader.pages:
                    text = page.extract_text()
                    if text:
                        resume_text += text + "\n"

                if not resume_text.strip():
                    continue

                from app.services.resume_parser import parse_resume_fields
                parsed_fields = parse_resume_fields(resume_text.strip())

                update_dict = {"resume_text": resume_text.strip()}
                if parsed_fields.get('yoe') is not None:
                    update_dict['yoe'] = parsed_fields['yoe']
                if parsed_fields.get('current_company'):
                    update_dict['current_company'] = parsed_fields['current_company']
                if parsed_fields.get('current_role'):
                    update_dict['current_role'] = parsed_fields['current_role']

                update_data = CandidateUpdate(**update_dict)
                crud.update_candidate(db, candidate_id, update_data)
                candidate.resume_pdf = pdf_bytes
                db.commit()

                return {
                    "status": "ok",
                    "message": "Resume extracted and stored",
                    "username": candidate.github_username,
                    "resume_length": len(resume_text.strip()),
                    "pages": len(pdf_reader.pages),
                    "filename": pdf_att.get("filename"),
                }
            except Exception as e:
                logger.error("Error extracting PDF for %s: %s", candidate.github_username, e)
                continue

    return {"status": "no_resume", "message": f"Found {len(candidate_emails)} email(s) from {candidate.email} but none had valid PDF attachments"}


@router.get("/candidates/{candidate_id}/debug-inbound", tags=["outreach"])
def debug_candidate_inbound(candidate_id: UUID, db: Session = Depends(get_db)):
    """Debug: show raw Resend receiving API data for a candidate's inbound emails."""
    import requests as http_requests
    from app.core.config import settings

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    headers = {"Authorization": f"Bearer {settings.RESEND_API_KEY}"}

    # Get all inbound emails
    resp = http_requests.get("https://api.resend.com/emails/receiving", headers=headers, timeout=30)
    if resp.status_code != 200:
        return {"error": f"Resend API: {resp.status_code}", "body": resp.text[:500]}

    all_emails = resp.json().get("data", [])
    matched = [e for e in all_emails if (e.get("from") or "").lower() == (candidate.email or "").lower()]

    results = []
    for recv in matched:
        detail = http_requests.get(
            f"https://api.resend.com/emails/receiving/{recv['id']}",
            headers=headers, timeout=15
        )
        detail_json = detail.json() if detail.status_code == 200 else {"error": detail.status_code}
        results.append({
            "list_entry": recv,
            "detail": detail_json,
        })

    return {
        "candidate": {"name": candidate.name, "email": candidate.email},
        "total_inbound": len(all_emails),
        "matched_emails": len(matched),
        "emails": results,
    }


@router.post("/candidates/bulk-backfill-resumes", tags=["outreach"])
def bulk_backfill_resumes(db: Session = Depends(get_db)):
    """
    Scan ALL Resend inbound emails, match to candidates by email address,
    and extract PDF resumes for any candidate that doesn't already have one.
    Uses cursor-based pagination to iterate through all inbound emails.
    """
    import io
    import requests as http_requests
    from app.core.config import settings
    from app.schemas.candidate import CandidateUpdate

    if not settings.RESEND_API_KEY:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY not configured")

    headers = {"Authorization": f"Bearer {settings.RESEND_API_KEY}"}

    # Build a lookup of candidate emails -> candidates (only those without resumes)
    candidates_without_resume = db.query(Candidate).filter(
        Candidate.email.isnot(None),
        Candidate.resume_text.is_(None),
    ).all()
    email_to_candidate = {}
    for c in candidates_without_resume:
        if c.email:
            email_to_candidate[c.email.lower()] = c

    if not email_to_candidate:
        return {"status": "ok", "message": "All candidates with emails already have resumes", "extracted": 0}

    # Fetch ALL inbound emails from Resend (with pagination)
    all_inbound = []
    last_id = None
    while True:
        params = {}
        if last_id:
            params["after"] = last_id
        resp = http_requests.get(
            "https://api.resend.com/emails/receiving",
            headers=headers,
            params=params,
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("Resend receiving API error: %s", resp.status_code)
            break
        data = resp.json().get("data", [])
        if not data:
            break
        all_inbound.extend(data)
        # If fewer than 100 returned and no limit was set, we got everything
        if len(data) < 100:
            break
        last_id = data[-1]["id"]

    logger.info("Bulk resume backfill: found %d inbound emails, %d candidates need resumes",
                len(all_inbound), len(email_to_candidate))

    results = {"extracted": 0, "checked": 0, "no_attachment": 0, "errors": [], "details": []}

    for recv_email in all_inbound:
        from_email = (recv_email.get("from") or "").lower()
        if from_email not in email_to_candidate:
            continue

        candidate = email_to_candidate[from_email]
        # Skip if we already extracted for this candidate (from an earlier email)
        if candidate.resume_text:
            continue

        results["checked"] += 1
        email_id = recv_email["id"]

        try:
            detail_resp = http_requests.get(
                f"https://api.resend.com/emails/receiving/{email_id}",
                headers=headers,
                timeout=15,
            )
            if detail_resp.status_code != 200:
                continue

            attachments = detail_resp.json().get("attachments", [])
            pdf_attachments = [a for a in attachments if
                              a.get("content_type", "").lower() == "application/pdf"
                              or (a.get("filename") or "").lower().endswith(".pdf")]

            if not pdf_attachments:
                results["no_attachment"] += 1
                continue

            for pdf_att in pdf_attachments:
                att_id = pdf_att.get("id")
                if not att_id:
                    continue

                att_resp = http_requests.get(
                    f"https://api.resend.com/emails/receiving/{email_id}/attachments/{att_id}",
                    headers=headers,
                    timeout=15,
                )
                if att_resp.status_code != 200:
                    continue

                download_url = att_resp.json().get("download_url")
                if not download_url:
                    continue

                pdf_resp = http_requests.get(download_url, timeout=30)
                if pdf_resp.status_code != 200:
                    continue

                pdf_bytes = pdf_resp.content
                if len(pdf_bytes) > 10 * 1024 * 1024:
                    continue

                from PyPDF2 import PdfReader
                pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
                resume_text = ""
                for page in pdf_reader.pages:
                    text = page.extract_text()
                    if text:
                        resume_text += text + "\n"

                if not resume_text.strip():
                    continue

                from app.services.resume_parser import parse_resume_fields
                parsed = parse_resume_fields(resume_text.strip())
                update_dict = {"resume_text": resume_text.strip()}
                if parsed.get('yoe') is not None:
                    update_dict['yoe'] = parsed['yoe']
                if parsed.get('current_company'):
                    update_dict['current_company'] = parsed['current_company']
                if parsed.get('current_role'):
                    update_dict['current_role'] = parsed['current_role']

                crud.update_candidate(db, candidate.id, CandidateUpdate(**update_dict))
                candidate.resume_pdf = pdf_bytes
                db.commit()
                # Refresh local ref so we skip this candidate on future emails
                candidate.resume_text = resume_text.strip()

                results["extracted"] += 1
                results["details"].append(f"{candidate.name} ({candidate.github_username}): {pdf_att.get('filename')} - {len(resume_text.strip())} chars")
                logger.info("Bulk backfill: extracted resume for %s from %s", candidate.github_username, pdf_att.get("filename"))
                break  # Only first valid PDF per candidate
        except Exception as e:
            results["errors"].append(f"{candidate.name}: {str(e)}")

    return results


# ===========================
# AI SCREENING ENDPOINTS (VAPI)
# ===========================

@router.post("/candidates/{candidate_id}/mark-replied", tags=["candidates", "screening"])
def mark_candidate_replied(
    candidate_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Mark candidate as replied to warm-up email.
    Triggers automatic screening link email after 6-minute delay.
    """
    from app.schemas.candidate import CandidateUpdate
    from app.services.screening_automation import trigger_screening_link_email

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not candidate.email:
        raise HTTPException(status_code=400, detail="Candidate has no email address")

    # Update warm-up replied timestamp
    update_data = CandidateUpdate(
        warmup_replied_at=datetime.utcnow().isoformat(),
        status="warm"
    )
    updated_candidate = crud.update_candidate(db, candidate_id, update_data)

    # Trigger delayed screening link email (6 minutes)
    trigger_screening_link_email(updated_candidate, db)

    return {
        "success": True,
        "message": "Candidate marked as replied. Screening link will be sent in 6 minutes.",
        "warmup_replied_at": updated_candidate.warmup_replied_at
    }


@router.get("/candidates/{candidate_id}/screening-link", tags=["candidates", "screening"])
def get_screening_link(
    candidate_id: UUID,
    db: Session = Depends(get_db)
):
    """Get screening link for a candidate."""
    from app.core.config import settings
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not candidate.github_username:
        raise HTTPException(status_code=400, detail="Candidate has no GitHub username")

    return {
        "screening_url": f"{settings.FRONTEND_URL}/chat/{candidate.github_username}",
        "status": candidate.screening_status,
        "link_sent_at": candidate.screening_link_sent_at
    }


@router.post("/candidates/{candidate_id}/start-screening", tags=["candidates", "screening"])
def start_screening_call(
    candidate_id: UUID,
    phone_number: str,
    db: Session = Depends(get_db)
):
    """
    Initiate VAPI screening call with candidate.
    Called from the screening page when candidate clicks "Start Call".
    """
    from app.services.vapi_screening import create_screening_call
    from app.schemas.candidate import CandidateUpdate

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not candidate.archetype:
        raise HTTPException(status_code=400, detail="Candidate must be analyzed first")

    try:
        # Create VAPI call
        call_response = create_screening_call(candidate, phone_number)

        # Update candidate with call ID and status
        update_data = CandidateUpdate(
            screening_call_id=call_response.get("id"),
            screening_status="in_progress",
            screening_scheduled_at=datetime.utcnow().isoformat()
        )
        crud.update_candidate(db, candidate_id, update_data)

        return {
            "success": True,
            "message": "Screening call initiated",
            "call_id": call_response.get("id"),
            "status": "in_progress"
        }

    except Exception as e:
        logger.error("Failed to start screening call: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start screening call: {str(e)}"
        )


@router.post("/public/screening/{username}/opened", tags=["public", "screening"])
def track_screening_link_click(username: str, db: Session = Depends(get_db)):
    """
    Track when a candidate opens the screening page (clicked the link).
    Called from the frontend ScreeningPage on load.
    """
    try:
        candidate = crud.get_candidate_by_github_username(db, username)
        if not candidate:
            return {"status": "ignored"}

        # Only record first click
        if not candidate.screening_link_clicked_at:
            from app.schemas.candidate import CandidateUpdate
            update_data = CandidateUpdate(
                screening_link_clicked_at=datetime.utcnow().isoformat()
            )
            crud.update_candidate(db, candidate.id, update_data)
            logger.info("Screening link clicked by %s", candidate.github_username)

        return {"status": "tracked"}

    except Exception as e:
        logger.error("Error tracking screening click for %s: %s", username, e)
        return {"status": "error"}


@router.post("/public/screening/{username}/upload-resume", tags=["public", "screening"])
async def public_upload_resume(
    username: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Public resume upload for screening page.
    Candidates upload their resume PDF before starting the screening call.
    """
    from app.schemas.candidate import CandidateUpdate
    from PyPDF2 import PdfReader

    candidate = crud.get_candidate_by_github_username(db, username)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Validate file type
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Validate file size (max 10MB)
    file_content = await file.read()
    if len(file_content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")

    try:
        # Extract text from PDF
        pdf_file = io.BytesIO(file_content)
        pdf_reader = PdfReader(pdf_file)
        resume_text = ""
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text:
                resume_text += text + "\n"

        if not resume_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from PDF. The file may be empty or contain only images."
            )

        # Parse structured fields from resume
        from app.services.resume_parser import parse_resume_fields
        parsed_fields = parse_resume_fields(resume_text.strip())

        # Build update with resume text + any parsed fields
        update_dict = {"resume_text": resume_text.strip()}
        if parsed_fields.get('yoe') is not None:
            update_dict['yoe'] = parsed_fields['yoe']
        if parsed_fields.get('current_company'):
            update_dict['current_company'] = parsed_fields['current_company']
        if parsed_fields.get('current_role'):
            update_dict['current_role'] = parsed_fields['current_role']

        # Extract email from resume if candidate doesn't have one
        if not candidate.email:
            import re
            email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', resume_text)
            if email_match:
                update_dict['email'] = email_match.group(0)
                logger.info("Extracted email from resume for %s: %s", username, email_match.group(0))

        update_data = CandidateUpdate(**update_dict)
        crud.update_candidate(db, candidate.id, update_data)

        # Store raw PDF bytes directly (bypasses Pydantic schema)
        candidate.resume_pdf = file_content
        db.commit()

        logger.info("Resume uploaded for %s (%d pages)", username, len(pdf_reader.pages))

        return {
            "success": True,
            "pages": len(pdf_reader.pages),
            "resume_length": len(resume_text.strip()),
            "email_found": bool(update_dict.get('email')),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process resume for %s: %s", username, e)
        raise HTTPException(status_code=500, detail="Failed to process resume")


@router.get("/public/candidates/{username}/resume.pdf", tags=["public"])
def serve_candidate_resume(username: str, db: Session = Depends(get_db)):
    """
    Serve the candidate's uploaded resume PDF.
    """
    from fastapi.responses import Response

    candidate = crud.get_candidate_by_github_username(db, username)
    if not candidate or not candidate.resume_pdf:
        raise HTTPException(status_code=404, detail="Resume not found")

    return Response(
        content=candidate.resume_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename={username}-resume.pdf",
        }
    )


@router.get("/public/candidates/{username}/voice-audio/{index}", tags=["public"])
def serve_voice_audio(username: str, index: int, db: Session = Depends(get_db)):
    """
    Serve a candidate's voice answer audio by question index.
    Decodes base64 audio stored in voice_answers JSON.
    """
    from fastapi.responses import Response

    candidate = crud.get_candidate_by_github_username(db, username)
    if not candidate or not candidate.voice_answers:
        raise HTTPException(status_code=404, detail="Voice answers not found")

    if index < 0 or index >= len(candidate.voice_answers):
        raise HTTPException(status_code=404, detail="Answer index out of range")

    answer = candidate.voice_answers[index]
    if not answer or not answer.get("audio_base64"):
        raise HTTPException(status_code=404, detail="No audio for this answer")

    audio_bytes = base64.b64decode(answer["audio_base64"])
    content_type = answer.get("audio_content_type", "audio/webm")

    return Response(
        content=audio_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": f"inline; filename={username}-q{index}.webm",
            "Cache-Control": "public, max-age=86400",
        }
    )


@router.post("/public/screening/{username}/upload-voice", tags=["public", "screening"])
async def upload_voice_answer(
    username: str,
    question_index: int = Query(..., ge=0, le=4, description="Question index (0-4)"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload a single voice answer recording. Stores audio bytes as base64 in
    voice_answers JSON. Transcription happens server-side on submit via Deepgram.
    """
    import base64
    from app.schemas.candidate import CandidateUpdate

    candidate = crud.get_candidate_by_github_username(db, username)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Audio file too large. Maximum 5MB per answer.")
    if len(file_content) < 1000:
        raise HTTPException(status_code=400, detail="Audio file too small. Please record a longer answer.")

    VOICE_QUESTIONS = [
        "What kind of role are you looking for?",
        "What's your ideal company stage and size?",
        "What's your salary expectation and equity preference?",
        "Are you open to relocation or remote only?",
        "How soon are you looking to make a move?",
    ]

    try:
        voice_answers = candidate.voice_answers or []
        while len(voice_answers) < 5:
            voice_answers.append(None)

        voice_answers[question_index] = {
            "question": VOICE_QUESTIONS[question_index],
            "audio_base64": base64.b64encode(file_content).decode("utf-8"),
            "audio_content_type": file.content_type or "audio/webm",
            "recorded_at": datetime.utcnow().isoformat(),
        }

        update_data = CandidateUpdate(voice_answers=voice_answers)
        crud.update_candidate(db, candidate.id, update_data)

        logger.info("Voice answer %d uploaded for %s (%d bytes)", question_index, username, len(file_content))

        return {"success": True, "question_index": question_index}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process voice answer for %s: %s", username, e)
        raise HTTPException(status_code=500, detail="Failed to process voice recording")


@router.post("/public/screening/{username}/upload-text-answer", tags=["public", "screening"])
async def upload_text_answer(
    username: str,
    question_index: int = Query(..., ge=0, le=4, description="Question index (0-4)"),
    text_answer: str = Query(..., min_length=10, description="Typed answer text"),
    db: Session = Depends(get_db),
):
    """
    Upload a typed text answer for candidates who can't record voice.
    Stores text directly in voice_answers JSON (no audio_base64).
    """
    from app.schemas.candidate import CandidateUpdate

    candidate = crud.get_candidate_by_github_username(db, username)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    VOICE_QUESTIONS = [
        "What kind of role are you looking for?",
        "What's your ideal company stage and size?",
        "What's your salary expectation and equity preference?",
        "Are you open to relocation or remote only?",
        "How soon are you looking to make a move?",
    ]

    try:
        voice_answers = candidate.voice_answers or []
        while len(voice_answers) < 5:
            voice_answers.append(None)

        voice_answers[question_index] = {
            "question": VOICE_QUESTIONS[question_index],
            "text_answer": text_answer.strip(),
            "recorded_at": datetime.utcnow().isoformat(),
        }

        update_data = CandidateUpdate(voice_answers=voice_answers)
        crud.update_candidate(db, candidate.id, update_data)

        logger.info("Text answer %d uploaded for %s (%d chars)", question_index, username, len(text_answer))

        return {"success": True, "question_index": question_index}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process text answer for %s: %s", username, e)
        raise HTTPException(status_code=500, detail="Failed to process text answer")


@router.post("/public/screening/{username}/submit-screening", tags=["public", "screening"])
async def submit_voice_screening(
    username: str,
    work_auth: Optional[str] = Query(None, description="Work authorization status"),
    db: Session = Depends(get_db),
):
    """
    Finalize voice form screening:
    1. Transcribe each stored audio answer via Deepgram
    2. Build pseudo-transcript from Q&A pairs
    3. Run DeepSeek extraction for screening_data + summary
    4. Mark screening as completed, send follow-up email
    """
    import base64
    import httpx
    from app.schemas.candidate import CandidateUpdate
    from app.services.vapi_screening import extract_screening_data, generate_screening_summary
    from app.core.config import settings

    candidate = crud.get_candidate_by_github_username(db, username)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    voice_answers = candidate.voice_answers or []
    filled = [a for a in voice_answers if a and (a.get("audio_base64") or a.get("text_answer"))]

    if len(filled) < 5:
        raise HTTPException(status_code=400, detail="Please answer all 5 questions before submitting.")

    VOICE_QUESTIONS = [
        "What kind of role are you looking for?",
        "What's your ideal company stage and size?",
        "What's your salary expectation and equity preference?",
        "Are you open to relocation or remote only?",
        "How soon are you looking to make a move?",
    ]

    # Transcribe audio via Deepgram; for text answers, use text directly as transcript
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, answer in enumerate(voice_answers):
            if not answer:
                continue
            # Text answer — use directly as transcript, no Deepgram needed
            if answer.get("text_answer") and not answer.get("audio_base64"):
                voice_answers[i]["transcript"] = answer["text_answer"]
                logger.info("Text answer used as transcript for Q%d for %s", i, username)
                continue
            # Audio answer — transcribe via Deepgram
            if not answer.get("audio_base64"):
                continue
            try:
                audio_bytes = base64.b64decode(answer["audio_base64"])
                content_type = answer.get("audio_content_type", "audio/webm")
                resp = await client.post(
                    "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true",
                    headers={
                        "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                        "Content-Type": content_type,
                    },
                    content=audio_bytes,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    transcript = (
                        data.get("results", {})
                        .get("channels", [{}])[0]
                        .get("alternatives", [{}])[0]
                        .get("transcript", "")
                    )
                    voice_answers[i]["transcript"] = transcript
                    logger.info("Deepgram transcribed Q%d for %s: %d chars", i, username, len(transcript))
                else:
                    logger.warning("Deepgram failed for Q%d (%d): %s", i, resp.status_code, resp.text[:200])
                    voice_answers[i]["transcript"] = ""
            except Exception as e:
                logger.warning("Deepgram error for Q%d: %s", i, e)
                voice_answers[i]["transcript"] = ""

    # Keep audio_base64 + audio_content_type in voice_answers so hirers
    # can replay the original recordings alongside reading transcripts.

    # Persist transcripts (and audio/text)
    update_transcripts = CandidateUpdate(voice_answers=voice_answers)
    crud.update_candidate(db, candidate.id, update_transcripts)

    filled_transcripts = [a for a in voice_answers if a and a.get("transcript")]
    if len(filled_transcripts) < 3:
        raise HTTPException(status_code=500, detail="Transcription failed for too many answers. Please try again.")

    # Build pseudo-transcript for DeepSeek extraction
    transcript_parts = []
    for i, answer in enumerate(voice_answers):
        if answer and answer.get("transcript"):
            q = VOICE_QUESTIONS[i] if i < len(VOICE_QUESTIONS) else f"Question {i+1}"
            transcript_parts.append(f"Interviewer: {q}")
            transcript_parts.append(f"Candidate: {answer['transcript']}")

    combined_transcript = "\n".join(transcript_parts)

    try:
        screening_data = extract_screening_data(combined_transcript, candidate)
        # Inject work authorization from form dropdown
        if work_auth:
            screening_data["work_authorization"] = work_auth
        summary = generate_screening_summary(combined_transcript, screening_data)

        update_data = CandidateUpdate(
            screening_status="completed",
            screening_transcript=combined_transcript,
            screening_summary=summary,
            screening_data=screening_data,
            screening_completed_at=datetime.utcnow().isoformat(),
        )
        crud.update_candidate(db, candidate.id, update_data)

        logger.info("Voice form screening completed for %s", username)

        # Send thank-you follow-up email
        try:
            from app.services.email_sender import send_outreach_email

            original_subject = candidate.outreach_subject or "your background"
            subject = f"Re: {original_subject}"

            first_name = candidate.name.split()[0] if candidate.name else 'there'
            email_body = f"""Hey {first_name}, thanks for taking the time to answer those questions! Really appreciate it.

I'll review everything and be in touch soon."""

            send_outreach_email(
                to_email=candidate.email,
                subject=subject,
                body=email_body,
                candidate_name=candidate.name,
            )
            logger.info("Thank-you email sent to %s after voice form", candidate.email)
        except Exception as e:
            logger.error("Failed to send thank-you email after voice form: %s", e)

        return {
            "success": True,
            "message": "Screening completed",
            "screening_data": screening_data,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process voice form screening for %s: %s", username, e)
        import traceback
        logger.error("Traceback: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to process screening responses")


@router.post("/webhooks/vapi", tags=["webhooks"])
async def vapi_webhook(request: dict):
    """
    VAPI webhook endpoint for call status updates.
    Receives end-of-call-report with transcript, recording, and analysis.

    VAPI payload structure:
    {
      "message": {
        "type": "end-of-call-report",
        "call": { "id": "...", "metadata": {...} },
        "artifact": { "transcript": "...", "recordingUrl": "...", "messages": [...] },
        "analysis": { "summary": "..." }
      }
    }
    """
    from app.services.vapi_screening import extract_screening_data, generate_screening_summary
    from app.schemas.candidate import CandidateUpdate
    from app.db.base import SessionLocal

    logger.info("VAPI webhook received: %s", json.dumps(request, default=str)[:2000])

    # VAPI wraps everything inside "message"
    message = request.get("message", {})
    event_type = message.get("type")

    # Also handle legacy top-level "type" just in case
    if not event_type:
        event_type = request.get("type")
        message = request  # fallback: treat entire request as message

    call_data = message.get("call", {})
    call_id = call_data.get("id")
    artifact = message.get("artifact", {})
    analysis = message.get("analysis", {})

    if event_type == "end-of-call-report":
        # Call completed - process transcript and extract data
        transcript = artifact.get("transcript", "")
        # Try multiple recording URL locations
        recording_url = (
            artifact.get("recordingUrl")
            or artifact.get("recording", {}).get("mono", {}).get("combinedUrl")
            or artifact.get("stereoRecordingUrl")
        )
        metadata = call_data.get("metadata", {})

        # Find candidate by call_id
        db = SessionLocal()
        try:
            candidate = db.query(Candidate).filter(
                Candidate.screening_call_id == call_id
            ).first()

            # Fallback: match by metadata.candidateId (for browser-based calls)
            if not candidate and metadata.get("candidateId") and metadata.get("type") == "screening":
                candidate_id_from_meta = metadata["candidateId"]
                logger.info("No screening_call_id match, trying metadata candidateId: %s", candidate_id_from_meta)
                candidate = db.query(Candidate).filter(
                    Candidate.id == candidate_id_from_meta
                ).first()
                if candidate:
                    # Save the call_id for future reference
                    candidate.screening_call_id = call_id
                    db.commit()
                    logger.info("Matched candidate %s via metadata", candidate.github_username)

            if not candidate:
                # Check if it's a reference call
                from app.models.reference import Reference, ReferenceStatus
                from app.services.vapi_reference import extract_reference_data

                ref = db.query(Reference).filter(Reference.call_id == call_id).first()

                # Fallback: match by metadata.referenceId (for browser-based reference calls)
                if not ref and metadata.get("referenceId") and metadata.get("type") == "reference":
                    ref_id_from_meta = metadata["referenceId"]
                    logger.info("No reference call_id match, trying metadata referenceId: %s", ref_id_from_meta)
                    ref = db.query(Reference).filter(Reference.id == ref_id_from_meta).first()
                    if ref:
                        ref.call_id = call_id
                        db.commit()
                        logger.info("Matched reference %s via metadata", ref.reference_name)

                if not ref:
                    logger.warning("No candidate or reference found for call_id: %s, metadata: %s", call_id, metadata)
                    return {"status": "ignored"}

                # Process reference call
                candidate_for_ref = db.query(Candidate).filter(
                    Candidate.id == ref.candidate_id
                ).first()

                ref_data = extract_reference_data(transcript, candidate_for_ref.name)

                # Update reference
                ref.call_transcript = transcript
                ref.call_summary = ref_data.get("summary")
                ref.call_audio_url = recording_url
                ref.would_work_again = ref_data.get("would_work_again")
                ref.strengths = ref_data.get("strengths")
                ref.areas_to_grow = ref_data.get("areas_to_grow")
                ref.overall_sentiment = ref_data.get("overall_sentiment")
                ref.status = ReferenceStatus.completed
                ref.completed_at = datetime.utcnow()
                db.commit()

                logger.info("Reference call completed for %s", ref.reference_name)

                return {"status": "processed", "type": "reference"}


            # Extract structured data from transcript
            screening_data = extract_screening_data(transcript, candidate)

            # Generate summary
            summary = generate_screening_summary(transcript, screening_data)

            # Update candidate
            update_data = CandidateUpdate(
                screening_status="completed",
                screening_transcript=transcript,
                screening_summary=summary,
                screening_data=screening_data,
                screening_audio_url=recording_url,
                screening_completed_at=datetime.utcnow().isoformat()
            )
            crud.update_candidate(db, candidate.id, update_data)

            logger.info("Screening completed for %s", candidate.github_username)

            # Send thank you email — thread into the same conversation
            from app.services.email_sender import send_outreach_email

            original_subject = candidate.outreach_subject or "your background"
            subject = f"Re: {original_subject}"

            from app.core.config import settings
            first_name = candidate.name.split()[0] if candidate.name else 'there'
            reference_url = f"{settings.FRONTEND_URL}/references/{candidate.github_username}/submit"
            body = f"""Hey {first_name}, thanks for taking the time to chat! Really appreciate it.

I'll review everything and be in touch soon with next steps.

One optional thing that can help you stand out — if you have anyone who can vouch for your work (former manager, teammate, etc.), you can add them here: {reference_url}

We'll reach out to them for a quick 5-min call. Totally optional, but it goes a long way with hiring managers.

If you have any questions feel free to reply here."""

            try:
                send_outreach_email(
                    to_email=candidate.email,
                    subject=subject,
                    body=body,
                    candidate_name=candidate.name
                )
                logger.info("Reference collection email sent to %s", candidate.email)
            except Exception as e:
                logger.error("Failed to send reference email: %s", e)

            return {"status": "processed"}

        finally:
            db.close()

    # Log other event types for debugging (status-update, speech-update, etc.)
    logger.info("VAPI webhook event type '%s' - no action taken", event_type)
    return {"status": "ok"}


@router.post("/webhooks/resend", tags=["webhooks"])
async def resend_webhook(request: dict):
    """
    Resend webhook for email events:
    - email.opened: Tracks when candidates open warm-up or screening emails
    - email.received: Tracks inbound replies from candidates (auto-triggers screening link)
    - email.delivered, email.bounced, etc.
    """
    from app.db.base import SessionLocal

    logger.debug("Resend webhook received: %s", request)

    event_type = request.get("type")

    if event_type == "email.opened":
        # Email was opened - track for warm-up, screening, follow-up, and role-pitch emails
        email_id = request.get("data", {}).get("email_id")

        # Use Resend's event timestamp (when the open was detected) instead of utcnow()
        from dateutil.parser import isoparse
        event_created_at = request.get("created_at")
        if event_created_at:
            try:
                open_timestamp = isoparse(event_created_at).replace(tzinfo=None)
            except Exception:
                open_timestamp = datetime.utcnow()
        else:
            open_timestamp = datetime.utcnow()

        db = SessionLocal()
        try:
            from app.api import crud
            from app.schemas.candidate import CandidateUpdate
            from app.models.email_event import EmailEvent

            # Dedup: skip if we already recorded an email_opened event for this resend_email_id
            existing_open = db.query(EmailEvent).filter(
                EmailEvent.resend_email_id == email_id,
                EmailEvent.event_type == EmailEventType.email_opened,
            ).first()
            if existing_open:
                logger.debug("Skipping duplicate email_opened for email_id=%s", email_id)
                return {"status": "duplicate_skipped"}

            # Check if it's a warm-up email open
            candidate = db.query(Candidate).filter(
                Candidate.warmup_email_id == email_id
            ).first()

            if candidate:
                if not candidate.warmup_email_opened_at:
                    update_data = CandidateUpdate(
                        warmup_email_opened_at=open_timestamp.isoformat()
                    )
                    crud.update_candidate(db, candidate.id, update_data)
                append_email_event(db, candidate.id, EmailEventType.email_opened,
                                  occurred_at=open_timestamp,
                                  resend_email_id=email_id,
                                  metadata={"email_type": "warmup"})
                db.commit()
                logger.info("Warm-up email opened by %s at %s", candidate.email, open_timestamp)
                return {"status": "processed", "email_type": "warmup"}

            # Check if it's a screening email open
            candidate = db.query(Candidate).filter(
                Candidate.screening_email_id == email_id
            ).first()

            if candidate:
                if not candidate.screening_email_opened_at:
                    update_data = CandidateUpdate(
                        screening_email_opened_at=open_timestamp.isoformat()
                    )
                    crud.update_candidate(db, candidate.id, update_data)
                append_email_event(db, candidate.id, EmailEventType.email_opened,
                                  occurred_at=open_timestamp,
                                  resend_email_id=email_id,
                                  metadata={"email_type": "screening"})
                db.commit()
                logger.info("Screening email opened by %s at %s", candidate.email, open_timestamp)
                return {"status": "processed", "email_type": "screening"}

            # Check if it's a follow-up email open
            candidate = db.query(Candidate).filter(
                Candidate.followup_email_id == email_id
            ).first()

            if candidate:
                append_email_event(db, candidate.id, EmailEventType.email_opened,
                                  occurred_at=open_timestamp,
                                  resend_email_id=email_id,
                                  metadata={"email_type": "followup"})
                db.commit()
                logger.info("Follow-up email opened by %s at %s", candidate.email, open_timestamp)
                return {"status": "processed", "email_type": "followup"}

            # Fallback: check email_events table for any sent email with this resend_email_id
            # (catches role pitches, older follow-ups, etc.)
            sent_event = db.query(EmailEvent).filter(
                EmailEvent.resend_email_id == email_id,
                EmailEvent.event_type.in_([
                    EmailEventType.outreach_sent,
                    EmailEventType.followup_sent,
                    EmailEventType.role_pitch_sent,
                    EmailEventType.screening_sent,
                ]),
            ).first()

            if sent_event:
                email_type = sent_event.event_type.value.replace("_sent", "")
                append_email_event(db, sent_event.candidate_id, EmailEventType.email_opened,
                                  occurred_at=open_timestamp,
                                  resend_email_id=email_id,
                                  metadata={"email_type": email_type})
                db.commit()
                logger.info("Email (%s) opened for candidate %s at %s", email_type, sent_event.candidate_id, open_timestamp)
                return {"status": "processed", "email_type": email_type}

            logger.warning("No candidate found for email_id: %s", email_id)
            return {"status": "ignored"}

        finally:
            db.close()

    elif event_type == "email.received":
        # Inbound email received (candidate replied!)
        data = request.get("data", {})
        from_email = data.get("from")
        to_email = data.get("to")
        subject = data.get("subject", "")
        text_body = data.get("text", "")
        html_body = data.get("html", "")
        attachments = data.get("attachments", [])

        logger.info("Email received from %s to %s", from_email, to_email)
        logger.info("Subject: %s", subject)

        # Find candidate by email
        db = SessionLocal()
        try:
            from app.api import crud
            from app.schemas.candidate import CandidateUpdate
            from app.services.screening_automation import trigger_screening_link_email

            candidate = db.query(Candidate).filter(
                Candidate.email == from_email
            ).first()

            if not candidate:
                logger.warning("No candidate found for email: %s", from_email)
                return {"status": "ignored", "reason": "Unknown sender"}

            # Store reply text from webhook payload
            reply_text = text_body.strip() if text_body else (html_body.strip() if html_body else None)

            # Fallback: if webhook didn't include text, fetch from Resend receiving API
            if not reply_text:
                logger.warning("Webhook had no reply text for %s, fetching from Resend receiving API...", candidate.github_username)
                try:
                    import requests as http_requests
                    from app.core.config import settings
                    import time
                    # Small delay to let Resend process the inbound email
                    time.sleep(2)
                    recv_resp = http_requests.get(
                        "https://api.resend.com/emails/receiving",
                        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                        timeout=10
                    )
                    if recv_resp.status_code == 200:
                        for recv_email in recv_resp.json().get("data", []):
                            if recv_email.get("from") == from_email:
                                detail_resp = http_requests.get(
                                    f"https://api.resend.com/emails/receiving/{recv_email['id']}",
                                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                                    timeout=10
                                )
                                if detail_resp.status_code == 200:
                                    email_detail = detail_resp.json()
                                    reply_text = (email_detail.get("text") or email_detail.get("html") or "").strip()
                                    # Strip quoted original email
                                    if reply_text:
                                        import re
                                        reply_text = re.split(r'\nOn .+? wrote:\n', reply_text, maxsplit=1)[0].strip()
                                    if reply_text:
                                        logger.info("Recovered reply text from Resend API for %s", candidate.github_username)
                                break
                except Exception as fetch_err:
                    logger.warning("Failed to fetch reply text from Resend API: %s", fetch_err)

            # Extract resume from PDF attachments (if any)
            # The webhook payload may or may not include attachments metadata.
            # Always check the Resend receiving API for the email to get attachment info.
            resume_extracted = False
            try:
                import requests as http_requests
                from app.core.config import settings
                import time as _time

                inbound_email_id = data.get("email_id") or data.get("id")

                # If webhook didn't include attachments or email ID, search Resend receiving API
                if not attachments or not inbound_email_id:
                    if settings.RESEND_API_KEY:
                        _time.sleep(2)  # Let Resend process the inbound email
                        recv_resp = http_requests.get(
                            "https://api.resend.com/emails/receiving",
                            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                            timeout=10
                        )
                        if recv_resp.status_code == 200:
                            for recv_email in recv_resp.json().get("data", []):
                                if recv_email.get("from") == from_email:
                                    inbound_email_id = recv_email["id"]
                                    # Fetch email details to get attachments
                                    detail_resp = http_requests.get(
                                        f"https://api.resend.com/emails/receiving/{inbound_email_id}",
                                        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                                        timeout=10
                                    )
                                    if detail_resp.status_code == 200:
                                        attachments = detail_resp.json().get("attachments", [])
                                    break

                if attachments and inbound_email_id:
                    from PyPDF2 import PdfReader
                    pdf_attachments = [a for a in attachments if a.get("content_type", "").lower() == "application/pdf"
                                       or (a.get("filename") or "").lower().endswith(".pdf")]
                    if pdf_attachments:
                        logger.info("Found %d PDF attachment(s) from %s, extracting resume...", len(pdf_attachments), candidate.github_username)
                        for pdf_att in pdf_attachments:
                            att_id = pdf_att.get("id")
                            if not att_id:
                                continue
                            att_resp = http_requests.get(
                                f"https://api.resend.com/emails/receiving/{inbound_email_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                                timeout=15
                            )
                            if att_resp.status_code != 200:
                                logger.warning("Failed to get attachment info: %s %s", att_resp.status_code, att_resp.text[:200])
                                continue
                            att_data = att_resp.json()
                            download_url = att_data.get("download_url")
                            if not download_url:
                                logger.warning("No download_url in attachment response for %s", att_id)
                                continue
                            pdf_resp = http_requests.get(download_url, timeout=30)
                            if pdf_resp.status_code != 200:
                                logger.warning("Failed to download PDF: %s", pdf_resp.status_code)
                                continue
                            pdf_bytes = pdf_resp.content
                            if len(pdf_bytes) > 10 * 1024 * 1024:
                                logger.warning("PDF too large (%d bytes), skipping", len(pdf_bytes))
                                continue
                            pdf_file = io.BytesIO(pdf_bytes)
                            pdf_reader = PdfReader(pdf_file)
                            resume_text_extracted = ""
                            for page in pdf_reader.pages:
                                text = page.extract_text()
                                if text:
                                    resume_text_extracted += text + "\n"
                            if not resume_text_extracted.strip():
                                logger.warning("Could not extract text from PDF attachment for %s", candidate.github_username)
                                continue
                            from app.services.resume_parser import parse_resume_fields
                            parsed_fields = parse_resume_fields(resume_text_extracted.strip())
                            resume_update = {"resume_text": resume_text_extracted.strip()}
                            if parsed_fields.get('yoe') is not None:
                                resume_update['yoe'] = parsed_fields['yoe']
                            if parsed_fields.get('current_company'):
                                resume_update['current_company'] = parsed_fields['current_company']
                            if parsed_fields.get('current_role'):
                                resume_update['current_role'] = parsed_fields['current_role']
                            resume_update_data = CandidateUpdate(**resume_update)
                            crud.update_candidate(db, candidate.id, resume_update_data)
                            candidate.resume_pdf = pdf_bytes
                            db.commit()
                            resume_extracted = True
                            logger.info("Resume extracted and stored for %s (%d chars, %d pages)",
                                        candidate.github_username, len(resume_text_extracted.strip()), len(pdf_reader.pages))
                            break  # Only process the first valid PDF
            except Exception as att_err:
                logger.error("Error extracting resume attachment for %s: %s", candidate.github_username, att_err)
                import traceback
                traceback.print_exc()

            # Determine if this is a first reply or a screening answer reply
            if candidate.warmup_replied_at and candidate.screening_link_sent_at:
                # REPLY AFTER SCREENING QUESTIONS SENT
                from app.services.screening_automation import trigger_screening_answer_processing
                import re as _re

                # ── Guard 1: check both candidate field AND email_events for prior screening answer ──
                already_answered = candidate.screening_status in ('answered', 'processing')
                if not already_answered:
                    from app.models.email_event import EmailEvent as _EE
                    existing_answered = db.query(_EE).filter(
                        _EE.candidate_id == candidate.id,
                        _EE.event_type == EmailEventType.screening_answered,
                    ).first()
                    if existing_answered:
                        already_answered = True
                        logger.info(
                            "%s: screening_status was '%s' but screening_answered event exists — treating as follow-up",
                            candidate.github_username, candidate.screening_status,
                        )

                # ── Guard 2: strip quoted text and check if reply is too short to be screening answers ──
                # Screening questions ask 3 substantive questions — real answers are typically 100+ chars.
                clean_reply = reply_text or ""
                # Strip "On <date> <person> wrote:" quoted blocks (Apple Mail, Gmail, etc.)
                clean_reply = _re.split(r'\n\s*>?\s*On .+? wrote:\s*\n', clean_reply, maxsplit=1)[0].strip()
                # Also strip lines starting with ">" (quoted text)
                clean_reply = "\n".join(
                    line for line in clean_reply.split("\n")
                    if not line.strip().startswith(">")
                ).strip()

                is_short_reply = len(clean_reply) < 80  # e.g. "Sounds good, thank you" = ~24 chars

                if already_answered:
                    # Already processed screening — this is a post-screening reply.
                    # Append to transcript but NEVER auto-reply.  After the screening
                    # confirmation email, all further replies are handled manually.
                    existing_transcript = candidate.screening_transcript or ""
                    combined = f"{existing_transcript}\n\n---\n\n{reply_text}" if existing_transcript else reply_text
                    logger.info("%s sent post-screening reply (appending to transcript, NO auto-reply)", candidate.github_username)

                    update_data = CandidateUpdate(screening_transcript=combined, has_unread_reply=True)
                    crud.update_candidate(db, candidate.id, update_data)
                    append_email_event(db, candidate.id, EmailEventType.candidate_replied,
                                      subject=subject, body=reply_text)
                    db.commit()

                    # Re-parse screening data silently if reply is substantive
                    if not is_short_reply:
                        logger.info("%s: post-screening reply is substantive (%d chars) — re-parsing silently (no email)", candidate.github_username, len(clean_reply))
                        from app.services.screening_automation import parse_screening_answers
                        try:
                            parsed = parse_screening_answers(combined, candidate.name)
                            db2 = None
                            try:
                                from app.db.base import SessionLocal
                                db2 = SessionLocal()
                                silent_update = CandidateUpdate(
                                    screening_data=parsed,
                                    screening_summary=parsed.get("summary", ""),
                                )
                                crud.update_candidate(db2, candidate.id, silent_update)
                                db2.commit()
                                logger.info("Re-parsed screening data for %s (no email sent)", candidate.github_username)
                            finally:
                                if db2:
                                    db2.close()
                        except Exception as parse_err:
                            logger.error("Failed to re-parse screening for %s: %s", candidate.github_username, parse_err)

                    return {
                        "status": "processed",
                        "candidate": candidate.github_username,
                        "action": "post_screening_reply_logged",
                        "resume_extracted": resume_extracted
                    }

                if is_short_reply:
                    # Reply is too short to be screening answers — likely a quick acknowledgement
                    # ("Sounds good", "Thanks", "Will do", etc.) or reply to a follow-up.
                    # Log as candidate_replied instead of screening_answered.
                    logger.info(
                        "%s: reply after screening is very short (%d chars: '%s') — logging as candidate_replied, not screening_answered",
                        candidate.github_username, len(clean_reply), clean_reply[:100],
                    )
                    append_email_event(db, candidate.id, EmailEventType.candidate_replied,
                                      subject=subject, body=reply_text)
                    crud.update_candidate(db, candidate.id, CandidateUpdate(has_unread_reply=True))
                    db.commit()
                    return {
                        "status": "processed",
                        "candidate": candidate.github_username,
                        "action": "short_reply_logged",
                        "resume_extracted": resume_extracted
                    }

                logger.info("%s sent screening answers! Processing...", candidate.github_username)

                # Store the screening reply text
                update_data = CandidateUpdate(
                    screening_transcript=reply_text,
                    screening_status="processing",
                    has_unread_reply=True,
                )
                updated_candidate = crud.update_candidate(db, candidate.id, update_data)
                append_email_event(db, candidate.id, EmailEventType.screening_answered,
                                  subject=subject, body=reply_text)
                db.commit()

                # Trigger background parsing of screening answers
                role_specific = (candidate.outreach_type == "role_specific")
                trigger_screening_answer_processing(updated_candidate, reply_text, role_specific=role_specific)

                return {
                    "status": "processed",
                    "candidate": candidate.github_username,
                    "action": "screening_answers_processing",
                    "resume_extracted": resume_extracted
                }

            elif candidate.warmup_replied_at:
                # Already replied but screening questions not sent yet (edge case — append)
                logger.info("%s sent another reply before screening questions were sent", candidate.github_username)
                if reply_text:
                    existing = candidate.warmup_reply_text or ""
                    combined = f"{existing}\n\n---\n\n{reply_text}" if existing else reply_text
                    update_data = CandidateUpdate(warmup_reply_text=combined, has_unread_reply=True)
                    crud.update_candidate(db, candidate.id, update_data)
                    append_email_event(db, candidate.id, EmailEventType.candidate_replied,
                                      subject=subject, body=reply_text)
                    db.commit()
                return {"status": "processed", "action": "reply_appended", "resume_extracted": resume_extracted}

            # FIRST REPLY: Mark as replied and trigger screening questions
            update_data = CandidateUpdate(
                warmup_replied_at=datetime.utcnow().isoformat(),
                warmup_reply_text=reply_text,
                status="warm",
                has_unread_reply=True,
            )
            updated_candidate = crud.update_candidate(db, candidate.id, update_data)
            append_email_event(db, candidate.id, EmailEventType.candidate_replied,
                              subject=subject, body=reply_text)
            db.commit()

            logger.info("%s replied! Reply text: %s. Scheduling screening questions...", candidate.github_username, reply_text[:200] if reply_text else "(empty)")

            # Trigger delayed screening questions email (3 minutes)
            trigger_screening_link_email(updated_candidate, db)

            logger.info("Screening questions scheduled for %s", candidate.github_username)

            return {
                "status": "processed",
                "candidate": candidate.github_username,
                "action": "screening_questions_scheduled",
                "resume_extracted": resume_extracted
            }

        except Exception as e:
            logger.error("Error processing reply: %s", e)
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

        finally:
            db.close()

    return {"status": "ok"}


@router.post("/webhooks/inbound-email", tags=["webhooks"])
async def inbound_email_webhook(request: dict):
    """
    Webhook for inbound emails (replies from candidates).
    Supports Mailgun, CloudMailin, and generic formats.

    Setup: Configure your email forwarding service to POST to this endpoint
    """
    from app.db.base import SessionLocal
    from app.api import crud
    from app.schemas.candidate import CandidateUpdate
    from app.services.screening_automation import trigger_screening_link_email

    logger.debug("Inbound email webhook received: %s", request)

    # Parse email based on provider format
    sender_email = None
    reply_body = None
    subject = None

    # Try Mailgun format
    if "sender" in request:
        sender_email = request.get("sender")
        reply_body = request.get("stripped-text") or request.get("body-plain", "")
        subject = request.get("subject", "")
        logger.debug("Mailgun format detected")

    # Try CloudMailin format
    elif "envelope" in request:
        sender_email = request.get("envelope", {}).get("from")
        reply_body = request.get("plain") or request.get("html", "")
        subject = request.get("headers", {}).get("Subject", "")
        logger.debug("CloudMailin format detected")

    # Try generic format
    elif "from" in request:
        sender_email = request.get("from")
        reply_body = request.get("body") or request.get("text", "")
        subject = request.get("subject", "")
        logger.debug("Generic format detected")

    if not sender_email:
        logger.error("Could not parse sender email")
        return {"status": "error", "message": "Could not parse email"}

    logger.info("From: %s, Subject: %s", sender_email, subject)

    # Find candidate by email
    db = SessionLocal()
    try:
        candidate = db.query(Candidate).filter(
            Candidate.email == sender_email
        ).first()

        if not candidate:
            logger.warning("No candidate found for %s", sender_email)
            return {"status": "ignored", "reason": "Unknown sender"}

        # Check if already marked as replied
        if candidate.warmup_replied_at:
            logger.info("%s already replied", candidate.github_username)
            return {"status": "ignored", "reason": "Already replied"}

        # Mark as replied and store reply content
        update_data = CandidateUpdate(
            warmup_replied_at=datetime.utcnow().isoformat(),
            warmup_reply_text=reply_body.strip() if reply_body else None,
            status="warm"
        )
        updated_candidate = crud.update_candidate(db, candidate.id, update_data)

        logger.info("%s replied! Scheduling screening link...", candidate.github_username)

        # Trigger delayed screening link (3 minutes)
        trigger_screening_link_email(updated_candidate, db)

        logger.info("Screening link scheduled")

        return {
            "status": "processed",
            "candidate": candidate.github_username,
            "action": "screening_link_scheduled"
        }

    except Exception as e:
        logger.error("Inbound email error: %s", e)
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

    finally:
        db.close()


# ===========================
# REFERENCE ENDPOINTS
# ===========================

@router.post("/candidates/{candidate_id}/submit-references", tags=["references"])
def submit_references(
    candidate_id: UUID,
    references: list[dict],
    db: Session = Depends(get_db)
):
    """
    Submit references after screening completion.
    Triggers automated reference check emails.
    
    Expected format:
    [
        {
            "name": "Jane Doe",
            "email": "jane@stripe.com",
            "title": "Engineering Manager",
            "relationship": "former manager at Stripe"
        }
    ]
    """
    from app.models.reference import Reference, ReferenceStatus
    from app.services.email_sender import send_outreach_email
    from app.core.config import settings

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    created_refs = []

    for ref_data in references:
        # Create reference record
        ref = Reference(
            candidate_id=candidate_id,
            reference_name=ref_data.get("name"),
            reference_email=ref_data.get("email"),
            reference_title=ref_data.get("title"),
            relationship=ref_data.get("relationship"),
            status=ReferenceStatus.requested
        )
        db.add(ref)
        db.commit()
        db.refresh(ref)

        # Send reference check email
        reference_url = f"{settings.FRONTEND_URL}/reference/{ref.id}"

        first_name = candidate.name.split()[0] if candidate.name else candidate.github_username
        subject = f"Quick reference for {first_name}"
        body = f"""Hi {ref.reference_name.split()[0]},

{first_name} listed you as a reference for engineering roles they're exploring.

Would you mind hopping on a quick 5-min audio call to share your experience working with them? It's browser-based (no app needed) and takes about 5 minutes.

Start the call here: {reference_url}

Totally optional — but it really helps them stand out to hiring managers."""

        try:
            send_outreach_email(
                to_email=ref.reference_email,
                subject=subject,
                body=body,
                candidate_name=ref.reference_name
            )
            logger.info("Reference request sent to %s", ref.reference_email)
        except Exception as e:
            logger.error("Failed to send reference request to %s: %s", ref.reference_email, e)

        created_refs.append({
            "id": str(ref.id),
            "name": ref.reference_name,
            "status": ref.status
        })

    return {
        "success": True,
        "message": f"{len(created_refs)} reference(s) submitted and emails sent",
        "references": created_refs
    }


@router.get("/references/{reference_id}", tags=["references"])
def get_reference(
    reference_id: UUID,
    db: Session = Depends(get_db)
):
    """Get reference details by ID."""
    from app.models.reference import Reference

    ref = db.query(Reference).filter(Reference.id == reference_id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")

    candidate = crud.get_candidate(db, ref.candidate_id)

    return {
        "reference": {
            "id": str(ref.id),
            "name": ref.reference_name,
            "relationship": ref.relationship,
            "status": ref.status
        },
        "candidate": {
            "name": candidate.name,
            "github_username": candidate.github_username,
            "archetype": candidate.archetype,
            "tier": candidate.tier
        }
    }


@router.post("/references/{reference_id}/start-call", tags=["references"])
def start_reference_call(
    reference_id: UUID,
    phone_number: str,
    db: Session = Depends(get_db)
):
    """Initiate VAPI reference check call."""
    from app.models.reference import Reference, ReferenceStatus
    from app.services.vapi_reference import create_reference_call

    ref = db.query(Reference).filter(Reference.id == reference_id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")

    candidate = crud.get_candidate(db, ref.candidate_id)

    try:
        # Create VAPI call
        call_response = create_reference_call(ref, candidate.name, phone_number)

        # Update reference with call ID
        ref.call_id = call_response.get("id")
        ref.status = ReferenceStatus.requested
        db.commit()

        return {
            "success": True,
            "message": "Reference call initiated",
            "call_id": call_response.get("id")
        }

    except Exception as e:
        logger.error("Failed to start reference call: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start reference call: {str(e)}"
        )


@router.get("/candidates/{candidate_id}/references", tags=["references"])
def get_candidate_references(
    candidate_id: UUID,
    db: Session = Depends(get_db)
):
    """Get all references for a candidate."""
    from app.models.reference import Reference

    refs = db.query(Reference).filter(Reference.candidate_id == candidate_id).all()

    return {
        "references": [
            {
                "id": str(ref.id),
                "name": ref.reference_name,
                "title": ref.reference_title,
                "relationship": ref.relationship,
                "status": ref.status,
                "would_work_again": ref.would_work_again,
                "summary": ref.call_summary,
                "transcript": ref.call_transcript,
                "audio_url": ref.call_audio_url,
                "strengths": ref.strengths,
                "areas_to_grow": ref.areas_to_grow,
                "overall_sentiment": ref.overall_sentiment,
                "completed_at": ref.completed_at
            }
            for ref in refs
        ]
    }


@router.get("/debug/ingestion-jobs-schema", tags=["debug"])
def debug_ingestion_jobs_schema(db: Session = Depends(get_db)):
    """Debug endpoint to check ingestion_jobs table schema."""
    from sqlalchemy import text, inspect
    
    try:
        # Check if table exists
        result = db.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'ingestion_jobs'
            ORDER BY ordinal_position
        """)).fetchall()
        
        if not result:
            return {
                "table_exists": False,
                "message": "ingestion_jobs table does not exist"
            }
        
        columns = [{"name": r[0], "type": r[1], "nullable": r[2]} for r in result]
        
        # Check alembic version
        version_result = db.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        
        return {
            "table_exists": True,
            "columns": columns,
            "alembic_version": version_result[0] if version_result else None
        }
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__
        }


@router.get("/debug/ingestion-jobs-data", tags=["debug"])
def debug_ingestion_jobs_data(db: Session = Depends(get_db)):
    """Debug endpoint to check ingestion_jobs table data."""
    from sqlalchemy import text
    
    try:
        # Get job data
        result = db.execute(text("""
            SELECT id, status, created_at, current_search, total_candidates
            FROM ingestion_jobs
            ORDER BY created_at DESC
            LIMIT 5
        """)).fetchall()
        
        jobs = []
        for r in result:
            jobs.append({
                "id": str(r[0]),
                "status": r[1],
                "created_at": str(r[2]) if r[2] else None,
                "current_search": r[3],
                "total_candidates": r[4]
            })
        
        return {
            "count": len(jobs),
            "jobs": jobs
        }
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__
        }


@router.post("/ingestion/job/{job_id}/stop", tags=["ingestion"])
def stop_job(job_id: UUID, db: Session = Depends(get_db)):
    """
    Stop a running or pending ingestion job.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    
    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status in [JobStatus.completed, JobStatus.failed, JobStatus.stopped]:
        return {
            "success": False,
            "message": f"Job is already {job.status.value}",
            "status": job.status.value
        }
    
    # Mark as stopped
    job.status = JobStatus.stopped
    job.completed_at = datetime.utcnow()

    # Cascade stop to sub-jobs (e.g., bulk_targeted_sourcing → individual targeted_sourcing sub-jobs)
    stopped_sub_jobs = 0
    if job.job_type == 'bulk_targeted_sourcing' and job.checkpoint_data:
        sub_jobs_data = job.checkpoint_data.get('sub_jobs', [])
        for sub in sub_jobs_data:
            sub_job_id = sub.get('job_id')
            if sub_job_id:
                sub_job = db.query(IngestionJob).filter(IngestionJob.id == UUID(sub_job_id)).first()
                if sub_job and sub_job.status in [JobStatus.pending, JobStatus.running]:
                    sub_job.status = JobStatus.stopped
                    sub_job.completed_at = datetime.utcnow()
                    stopped_sub_jobs += 1

    db.commit()

    return {
        "success": True,
        "message": f"Job stopped successfully" + (f" ({stopped_sub_jobs} sub-jobs also stopped)" if stopped_sub_jobs else ""),
        "status": job.status.value
    }


@router.patch("/ingestion/job/{job_id}/threshold", tags=["ingestion"])
def update_job_threshold(job_id: UUID, min_behavior_score: int, db: Session = Depends(get_db)):
    """
    Update the min_behavior_score threshold for a running ingestion job.
    This takes effect immediately for candidates not yet processed.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus

    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in [JobStatus.completed, JobStatus.failed, JobStatus.stopped]:
        return {
            "success": False,
            "message": f"Cannot update threshold for {job.status.value} job",
            "current_threshold": job.min_behavior_score
        }

    old_threshold = job.min_behavior_score
    job.min_behavior_score = min_behavior_score
    job.updated_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "message": f"Threshold updated from {old_threshold} to {min_behavior_score}",
        "old_threshold": old_threshold,
        "new_threshold": min_behavior_score,
        "status": job.status.value
    }


@router.post("/ingestion/jobs/update-threshold", tags=["ingestion"])
def update_all_active_jobs_threshold(min_behavior_score: int = 30, db: Session = Depends(get_db)):
    """
    Update the min_behavior_score threshold for ALL active (running/pending) ingestion jobs.
    Useful for applying threshold changes to currently running jobs.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus

    active_jobs = db.query(IngestionJob).filter(
        IngestionJob.status.in_([JobStatus.pending, JobStatus.running])
    ).all()

    if not active_jobs:
        return {
            "success": True,
            "message": "No active jobs to update",
            "updated_count": 0
        }

    updated_jobs = []
    for job in active_jobs:
        old_threshold = job.min_behavior_score
        job.min_behavior_score = min_behavior_score
        job.updated_at = datetime.utcnow()
        updated_jobs.append({
            "job_id": str(job.id),
            "old_threshold": old_threshold,
            "new_threshold": min_behavior_score,
            "status": job.status.value
        })

    db.commit()

    return {
        "success": True,
        "message": f"Updated {len(updated_jobs)} active jobs to threshold {min_behavior_score}",
        "updated_count": len(updated_jobs),
        "jobs": updated_jobs
    }


@router.post("/admin/fix-threshold-database", tags=["admin"])
def fix_threshold_database_default(db: Session = Depends(get_db)):
    """
    ADMIN: Fix the database default for min_behavior_score from 40 to 30.
    Updates the column default AND all existing records.
    """
    from sqlalchemy import text
    from app.models.ingestion_job import IngestionJob

    try:
        # Update database default
        db.execute(text("ALTER TABLE ingestion_jobs ALTER COLUMN min_behavior_score SET DEFAULT 30"))

        # Update all existing records with 40 or NULL to 30
        result = db.execute(text("UPDATE ingestion_jobs SET min_behavior_score = 30 WHERE min_behavior_score = 40 OR min_behavior_score IS NULL"))
        updated_count = result.rowcount

        db.commit()

        # Get current jobs to verify
        jobs = db.query(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(5).all()
        job_info = [{
            "id": str(j.id)[:8] + "...",
            "threshold": j.min_behavior_score,
            "status": j.status.value
        } for j in jobs]

        return {
            "success": True,
            "message": f"✅ Fixed database default and updated {updated_count} existing jobs",
            "updated_count": updated_count,
            "recent_jobs": job_info
        }

    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "error": str(e)
        }


@router.delete("/ingestion/job/{job_id}", tags=["ingestion"])
def delete_job(job_id: UUID, db: Session = Depends(get_db)):
    """
    Delete an ingestion job (only if not running).
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    
    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status == JobStatus.running:
        return {
            "success": False,
            "message": "Cannot delete a running job. Stop it first.",
            "status": job.status.value
        }
    
    db.delete(job)
    db.commit()

    return {
        "success": True,
        "message": "Job deleted successfully"
    }


@router.get("/debug/token-config", tags=["debug"])
def check_token_configuration():
    """
    Verify how many GitHub tokens are loaded and working.
    Returns token count, rate limits, and expected performance.
    """
    from app.services.github_ingestion import token_rotator

    tokens_count = len(token_rotator.tokens)
    combined_rate = token_rotator.rate_per_token * tokens_count
    candidates_per_min = round((combined_rate / 8) * 60, 1)
    estimated_hours = round(20167 / (candidates_per_min * 60), 1)

    return {
        "tokens_loaded": tokens_count,
        "rate_per_token": token_rotator.rate_per_token,
        "combined_rate": combined_rate,
        "bucket_capacity": token_rotator.bucket_capacity,
        "expected_performance": {
            "candidates_per_minute": candidates_per_min,
            "estimated_hours_for_20k": estimated_hours
        },
        "status": "ok" if tokens_count >= 3 else "warning",
        "message": f"✅ {tokens_count} token(s) configured and ready" if tokens_count >= 3 else f"⚠️ Only {tokens_count} token(s) found, expected 3"
    }


@router.post("/debug/test-worker-logging", tags=["debug"])
def test_worker_logging(db: Session = Depends(get_db)):
    """
    Test worker-based logging with a small batch of known GitHub users.
    Returns logs to verify worker IDs, EST timestamps, and flag_modified.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    from app.services.parallel_processor import process_batch_parallel
    from datetime import datetime
    import uuid

    # Test with 5 well-known GitHub users
    test_usernames = ['torvalds', 'gaearon', 'tj', 'sindresorhus', 'addyosmani']

    # Create test job
    job = IngestionJob(
        id=str(uuid.uuid4()),
        status=JobStatus.running,
        searches_total=1,
        searches_completed=1,
        total_candidates=len(test_usernames),
        processed_count=0,
        candidates_saved=0,
        candidates_skipped=0,
        current_batch=1,
        recent_logs=[],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(job)
    db.commit()

    stats = {
        'saved': 0,
        'skipped_hard_filter': 0,
        'skipped_low_score': 0,
        'errors': 0,
        'hot': 0,
        'warm': 0,
        'cold': 0
    }

    # Process batch with parallel workers
    try:
        process_batch_parallel(
            db=db,
            job=job,
            batch_usernames=test_usernames,
            batch_start_index=0,
            current_threshold=30,
            stats=stats,
            max_workers=12
        )

        # Refresh to get latest logs
        db.refresh(job)

        logs = job.recent_logs or []
        worker_logs = [log for log in logs if 'Worker' in log.get('message', '')]

        result = {
            "test_status": "success",
            "candidates_tested": len(test_usernames),
            "stats": stats,
            "total_log_entries": len(logs),
            "worker_based_log_entries": len(worker_logs),
            "logs": logs,
            "verification": {
                "has_worker_format": len(worker_logs) > 0,
                "has_est_timezone": any('EST' in log.get('timestamp', '') for log in logs),
                "flag_modified_working": len(logs) > 0
            }
        }

        # Clean up test job
        db.delete(job)
        db.commit()

        return result

    except Exception as e:
        # Clean up on error
        db.delete(job)
        db.commit()
        raise


# ===========================
# CLI ANALYZE & CLAIM
# ===========================

class CLIMetricDetail(BaseModel):
    score: int
    details: dict

class CLIAnalyzeRequest(BaseModel):
    metrics: dict
    result: dict
    sessionStats: dict

class CLIClaimRequest(BaseModel):
    metrics: dict
    result: dict
    prose: Optional[dict] = None
    sessionStats: dict
    tools: Optional[list] = None
    claimedAt: Optional[str] = None


@router.post("/public/cli/analyze", tags=["public", "cli"])
def cli_analyze(request: CLIAnalyzeRequest):
    """
    Generate personalized prose descriptions from CLI-computed metrics.
    Uses DeepSeek to create unique, shareable descriptions.
    """
    from app.core.config import settings
    import requests as http_requests

    metrics = request.metrics
    result = request.result
    session_stats = request.sessionStats

    # Build the DeepSeek prompt
    prompt = f"""You are writing a personalized engineering profile. This will be displayed in a terminal CLI tool.
The data comes from analyzing the engineer's Claude Code / Cursor / Codex session history.

SCORES AND DATA:

THINKING ({metrics.get('decomposition', {}).get('score', 50)}/100):
{json.dumps(metrics.get('decomposition', {}).get('details', {}), indent=2)}

DEBUGGING ({metrics.get('debugCycles', {}).get('score', 50)}/100):
{json.dumps(metrics.get('debugCycles', {}).get('details', {}), indent=2)}

AI LEVERAGE ({metrics.get('aiLeverage', {}).get('score', 50)}/100):
{json.dumps(metrics.get('aiLeverage', {}).get('details', {}), indent=2)}

WORKFLOW ({metrics.get('sessionStructure', {}).get('score', 50)}/100):
{json.dumps(metrics.get('sessionStructure', {}).get('details', {}), indent=2)}

OVERALL: {result.get('overall', 50)}/100 — {result.get('archetype', {}).get('name', 'UNKNOWN')} — {result.get('tier', 'COMMON')}

STATS: {session_stats.get('totalSessions', 0)} sessions, {session_stats.get('totalExchanges', 0)} exchanges, {session_stats.get('projectCount', 0)} projects
Tools: {', '.join(session_stats.get('tools', []))}
Period: {session_stats.get('dateRange', 'unknown')}

Write a profile in this EXACT JSON format. Each section description should be 2-3 SHORT punchy lines separated by \\n.
Each line is a data point with a characterization — like terminal output, not paragraphs.

Example style for a section description:
"1.3 turns to resolve — surgical\\n100% specific error reports\\nZero extended debug loops detected"

{{
  "sections": [
    {{
      "emoji": "🧠",
      "title": "Thinking",
      "description": "<line1: key metric + characterization>\\n<line2: key metric + characterization>\\n<line3: pattern observation>"
    }},
    {{
      "emoji": "⚡",
      "title": "Debugging",
      "description": "<line1: turns to resolve + characterization>\\n<line2: specificity stat>\\n<line3: loop/spiral observation>"
    }},
    {{
      "emoji": "🔧",
      "title": "AI Leverage",
      "description": "<line1: architecture % + characterization>\\n<line2: coding vs research balance>\\n<line3: usage pattern>"
    }},
    {{
      "emoji": "📐",
      "title": "Workflow",
      "description": "<line1: context-setting rate + characterization>\\n<line2: review/refinement habit>\\n<line3: session structure observation>"
    }}
  ],
  "tagline": "<punchy 6-10 word identity statement, like 'Builds fast, debugs faster, never loops.'>"
}}

RULES:
- Each description line is a data bullet, NOT a paragraph. Reference real numbers.
- Be honest. Low scores get honest characterization, not sugarcoating.
- The tagline is the tweet. Under 60 chars. Memorable. Third person.
- No corporate language. Engineer to engineer.
- Return ONLY valid JSON, no markdown fences, no commentary."""

    # Try DeepSeek first, fall back to template prose
    if settings.DEEPSEEK_API_KEY:
        try:
            response = http_requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "You are a technical writer who creates sharp, personalized engineering profiles. You always return valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.8,
                },
                timeout=30,
            )

            if response.ok:
                content = response.json()["choices"][0]["message"]["content"]
                # Strip markdown fences if present
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content.rsplit("```", 1)[0]
                content = content.strip()

                prose = json.loads(content)
                return prose
            else:
                logger.error("DeepSeek API error for CLI analyze: %s", response.text)
        except Exception as e:
            logger.error("CLI analyze DeepSeek error: %s", e)

    # Fallback: template prose
    scores = result.get('scores', {})
    decomp = scores.get('decomposition', 50)
    debug = scores.get('debugCycles', 50)
    leverage = scores.get('aiLeverage', 50)
    workflow = scores.get('sessionStructure', 50)
    archetype_name = result.get('archetype', {}).get('name', 'ENGINEER')

    return {
        "sections": [
            {
                "emoji": "🧠",
                "title": "How You Think",
                "description": f"Your decomposition score is {decomp}. {'You break problems down methodically before diving in.' if decomp >= 70 else 'You tend to tackle problems in larger chunks — consider breaking tasks down more.' if decomp >= 50 else 'You tend to go big. Try decomposing complex tasks into smaller, focused prompts.'}"
            },
            {
                "emoji": "⚡",
                "title": "How You Debug",
                "description": f"Your debug efficiency is {debug}. {'You resolve issues quickly with targeted context.' if debug >= 70 else 'Your debugging is solid but has room for more precision.' if debug >= 50 else 'When debugging, try providing more specific error context — stack traces, line numbers, exact error messages.'}"
            },
            {
                "emoji": "🔧",
                "title": "How You Leverage AI",
                "description": f"Your AI leverage score is {leverage}. {'You use AI as a design partner, not just a code generator.' if leverage >= 70 else 'You use AI for a mix of tasks — try leaning more into architecture and design.' if leverage >= 50 else 'Most of your AI usage is for implementation. Try using it for design, review, and exploration too.'}"
            },
            {
                "emoji": "📐",
                "title": "Your Workflow",
                "description": f"Your workflow score is {workflow}. {'You set context, plan ahead, and review critically.' if workflow >= 70 else 'Your workflow has good habits — more context-setting at session start could help.' if workflow >= 50 else 'Try starting sessions with more context about what you are building and why.'}"
            },
        ],
        "tagline": f"A {archetype_name.lower().replace('the ', '')} at work.",
    }


@router.post("/public/cli/claim", tags=["public", "cli"])
def cli_claim(request: CLIClaimRequest, db: Session = Depends(get_db)):
    """
    Store CLI analysis results and return a claim URL.
    The user can later visit this URL to connect GitHub/LinkedIn.
    """
    import uuid as uuid_mod
    from app.core.config import settings

    claim_token = str(uuid_mod.uuid4())[:8]

    # Store as a lightweight record — for V1, just save to a JSON column on a new or existing candidate
    # For now, we'll return the claim URL and store the data in-memory
    # TODO: Create a cli_profiles table in V2 for persistent storage

    logger.info(
        "CLI claim: archetype=%s tier=%s overall=%s token=%s",
        request.result.get('archetype', {}).get('name'),
        request.result.get('tier'),
        request.result.get('overall'),
        claim_token,
    )

    return {
        "claimUrl": f"{settings.FRONTEND_URL}/claim/{claim_token}",
        "token": claim_token,
    }


# ---------------------------------------------------------------------------
# Backfill required_skills_priority for existing roles
# ---------------------------------------------------------------------------

@router.post("/roles/backfill-skill-priority", tags=["roles"])
def backfill_skill_priority(
    db: Session = Depends(get_db),
):
    """
    Backfill required_skills_priority for roles that have jd_text but no
    priority classification yet.  Uses DeepSeek to classify each tech_stack
    item as must_have or nice_to_have based on the full JD text.
    """
    import json
    import requests as http_requests
    from app.core.config import settings

    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY not configured")

    roles = db.query(Role).filter(
        Role.jd_text.isnot(None),
        Role.tech_stack.isnot(None),
        Role.required_skills_priority.is_(None),
    ).all()

    if not roles:
        return {"message": "No roles need backfill", "updated": 0}

    updated = 0
    errors = []

    for role in roles:
        try:
            tech_list = role.tech_stack or []
            if not tech_list:
                continue

            prompt = f"""Given this job description and tech stack, classify each technology as "must_have" or "nice_to_have".

Rules:
- Technologies from "Requirements", "Must have", "Qualifications", or core job description = "must_have"
- Technologies from "Nice to have", "Bonus", "Preferred", "Optional" sections = "nice_to_have"
- If unclear or the technology is central to the role title (e.g. "Python" for a "Python Engineer"), default to "must_have"

Job Title: {role.title}
Company: {role.company_name}

Tech Stack: {json.dumps(tech_list)}

Job Description:
{(role.jd_text or '')[:4000]}

Return ONLY a JSON object mapping each tech to its priority, e.g.:
{{"Python": "must_have", "Docker": "nice_to_have"}}
"""

            resp = http_requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            priority = json.loads(content)

            # Validate: only accept must_have/nice_to_have values
            cleaned = {}
            for k, v in priority.items():
                if v in ("must_have", "nice_to_have"):
                    cleaned[k] = v
                else:
                    cleaned[k] = "must_have"

            role.required_skills_priority = cleaned
            db.commit()
            updated += 1
            logger.info("Backfilled skill priority for %s - %s: %s", role.company_name, role.title, cleaned)

        except Exception as e:
            logger.error("Failed to backfill %s - %s: %s", role.company_name, role.title, e)
            errors.append(f"{role.company_name} - {role.title}: {e}")

    return {
        "message": f"Backfilled {updated} roles",
        "updated": updated,
        "errors": errors,
    }


@router.post("/candidates/{candidate_id}/ensure-role-matches", tags=["candidates", "starred", "analysis"])
def ensure_role_matches(candidate_id: UUID, db: Session = Depends(get_db)):
    """
    Ensure matches exist between a candidate and ALL active roles.
    Does NOT run analysis — just creates Match records if missing.
    Returns the list of match_id + role info for the frontend to analyze individually.
    """
    from app.models.fit_analysis import FitAnalysis
    from app.models.role import RoleStatus

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Get all active roles (not placed or lost)
    active_roles = (
        db.query(Role)
        .filter(Role.status.notin_([RoleStatus.placed, RoleStatus.lost]))
        .all()
    )

    matches = []
    for role in active_roles:
        match = (
            db.query(Match)
            .filter(Match.candidate_id == candidate_id, Match.role_id == role.id)
            .first()
        )

        if not match:
            match = Match(candidate_id=candidate_id, role_id=role.id)
            db.add(match)
            db.flush()

        # Check for existing fit analysis
        fit = db.query(FitAnalysis).filter(FitAnalysis.match_id == match.id).first()

        matches.append({
            "match_id": str(match.id),
            "role_id": str(role.id),
            "role_title": role.title,
            "company_name": role.company_name,
            "starred": match.starred,
            "existing_fit_score": fit.fit_score if fit else None,
            "existing_recommendation": fit.recommendation if fit else None,
        })

    db.commit()

    return {
        "candidate_id": str(candidate_id),
        "candidate_name": candidate.name,
        "matches": matches,
    }


class CrosschekkStartRequest(BaseModel):
    candidate_ids: List[str]


@router.post("/crosschekk/start", tags=["starred", "analysis"])
def start_crosschekk_job(
    body: CrosschekkStartRequest,
    db: Session = Depends(get_db),
):
    """
    Start a background CrossChekk job that analyzes candidates against ALL active roles.

    Returns immediately with a job_id. Poll /ingestion/job/status/{job_id} for progress.
    The checkpoint_data field contains per-candidate/per-role results as they complete.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    import threading

    candidate_ids = body.candidate_ids
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="No candidate_ids provided")

    # Check for existing running crosschekk job
    existing = db.query(IngestionJob).filter(
        IngestionJob.job_type == 'crosschekk',
        IngestionJob.status.in_([JobStatus.pending, JobStatus.running]),
    ).first()
    if existing:
        return {
            "success": False,
            "message": "A CrossChekk job is already running",
            "job_id": str(existing.id),
            "status": existing.status.value,
        }

    # Validate candidates exist and get names
    candidates_info = []
    for cid in candidate_ids:
        c = crud.get_candidate(db, cid)
        if c:
            candidates_info.append({
                "id": str(c.id),
                "name": c.name or c.github_username or "Unknown",
            })

    if not candidates_info:
        raise HTTPException(status_code=400, detail="No valid candidates found")

    # Get active roles
    from app.models.role import RoleStatus
    active_roles = db.query(Role).filter(
        Role.status.notin_([RoleStatus.placed, RoleStatus.lost])
    ).all()

    if not active_roles:
        raise HTTPException(status_code=400, detail="No active roles found")

    roles_info = [{"id": str(r.id), "title": r.title, "company": r.company_name} for r in active_roles]
    total_analyses = len(candidates_info) * len(roles_info)

    # Create job
    job = IngestionJob(
        status=JobStatus.running,
        job_type='crosschekk',
        total_candidates=len(candidates_info),
        total_batches=len(roles_info),
        processed_count=0,
        candidates_saved=0,
        error_count=0,
        recent_logs=[],
        checkpoint_data={
            "candidates": candidates_info,
            "roles": roles_info,
            "total_analyses": total_analyses,
            "results": {},  # { candidateId: { roleId: { fit_score, recommendation, ... } } }
            "current_candidate": None,
            "current_role": None,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_id = str(job.id)
    cids_copy = [c["id"] for c in candidates_info]

    def run_crosschekk_background():
        from app.db.base import SessionLocal
        from app.models.ingestion_job import IngestionJob as IJModel, JobStatus as JS
        from app.models.fit_analysis import FitAnalysis
        from app.core.config import settings
        from app.services.fit_score_calculator import calculate_fit_score, parse_jd
        from sqlalchemy.orm.attributes import flag_modified
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading as _threading

        PARALLEL_WORKERS = 10

        # Lock for writing to the shared job record (checkpoint_data, logs, counts)
        job_lock = _threading.Lock()
        # Shared mutable counters
        counters = {"done": 0, "errors": 0, "skipped": 0}
        # Flag to signal workers to abort
        stop_flag = _threading.Event()

        coord_db = SessionLocal()   # coordinator session — only for job record

        def coord_add_log(coord_job, message):
            timestamp = datetime.utcnow().strftime('%H:%M:%S')
            logs = coord_job.recent_logs or []
            logs.append({'timestamp': timestamp, 'message': message})
            coord_job.recent_logs = logs[-500:]
            flag_modified(coord_job, 'recent_logs')

        def coord_flush(coord_job):
            """Write current counters to job record and commit."""
            coord_job.processed_count = counters["done"] + counters["errors"] + counters["skipped"]
            coord_job.candidates_saved = counters["done"]
            coord_job.error_count = counters["errors"]
            flag_modified(coord_job, 'checkpoint_data')
            coord_db.commit()

        def check_stopped(coord_job) -> bool:
            """Refresh and check if user stopped the job."""
            coord_db.refresh(coord_job)
            if coord_job.status == JS.stopped:
                stop_flag.set()
                return True
            return False

        def analyze_one(cid: str, cname: str, candidate_data: dict, role_info: dict):
            """
            Worker function — runs in its own thread with its own DB session.
            Returns a result dict to be stored in checkpoint_data.
            """
            if stop_flag.is_set():
                return None

            w_db = SessionLocal()
            try:
                role = w_db.query(Role).filter(Role.id == role_info["id"]).first()
                if not role:
                    return None

                # Ensure match exists
                match = w_db.query(Match).filter(
                    Match.candidate_id == cid, Match.role_id == role.id
                ).first()
                if not match:
                    match = Match(candidate_id=cid, role_id=role.id)
                    w_db.add(match)
                    w_db.flush()

                # --- Skip if FitAnalysis already exists ---
                existing_fa = w_db.query(FitAnalysis).filter(FitAnalysis.match_id == match.id).first()
                if existing_fa and existing_fa.fit_score is not None:
                    return {
                        "match_id": str(match.id),
                        "role_id": role_info["id"],
                        "role_title": role.title,
                        "company_name": role.company_name,
                        "fit_score": existing_fa.fit_score,
                        "recommendation": existing_fa.recommendation or "SKIP",
                        "ai_summary_short": existing_fa.ai_summary_short or "",
                        "ai_summary": existing_fa.ai_summary or "",
                        "skills_matched": existing_fa.skills_matched or [],
                        "skills_missing": existing_fa.skills_missing or [],
                        "starred": match.starred,
                        "status": "done",
                        "_skipped": True,
                    }

                # --- Run DeepSeek analysis ---
                parsed_jd = parse_jd(role.jd_text or "", role.title, getattr(role, 'seniority_level', None))
                fit_result = calculate_fit_score(settings.DEEPSEEK_API_KEY, candidate_data, parsed_jd)

                # Save FitAnalysis (replace if exists)
                w_db.query(FitAnalysis).filter(FitAnalysis.match_id == match.id).delete()
                w_db.flush()

                fit_analysis = FitAnalysis(
                    candidate_id=cid,
                    role_id=role.id,
                    match_id=match.id,
                    fit_score=int(fit_result.get('fitScore', 0)),
                    recommendation=fit_result.get('recommendation', 'SKIP'),
                    skills_matched=fit_result.get('skillsMatch', {}).get('matched', []),
                    skills_missing=fit_result.get('skillsMatch', {}).get('missing', []),
                    skills_extra=fit_result.get('skillsMatch', {}).get('extra', []),
                    candidate_level=('Mid-Level' if fit_result.get('experienceMatch', {}).get('candidateLevel') == 'Mid' else fit_result.get('experienceMatch', {}).get('candidateLevel')),
                    required_level=parsed_jd.get('seniority', fit_result.get('experienceMatch', {}).get('requiredLevel')),
                    experience_meets=1 if parsed_jd.get('seniority') == 'Flexible' else (1 if fit_result.get('experienceMatch', {}).get('meets') else 0),
                    strengths=fit_result.get('strengthsForRole', []),
                    concerns=fit_result.get('concernsForRole', []),
                    ai_summary=fit_result.get('aiSummary'),
                    ai_summary_short=fit_result.get('aiSummaryShort'),
                    full_analysis=fit_result,
                )
                w_db.add(fit_analysis)

                # Update match score
                match.match_score = int(fit_result.get('fitScore', 0))
                w_db.commit()

                return {
                    "match_id": str(match.id),
                    "role_id": role_info["id"],
                    "role_title": role.title,
                    "company_name": role.company_name,
                    "fit_score": int(fit_result.get('fitScore', 0)),
                    "recommendation": fit_result.get('recommendation', 'SKIP'),
                    "ai_summary_short": fit_result.get('aiSummaryShort', ''),
                    "ai_summary": fit_result.get('aiSummary', ''),
                    "skills_matched": fit_result.get('skillsMatch', {}).get('matched', []),
                    "skills_missing": fit_result.get('skillsMatch', {}).get('missing', []),
                    "starred": match.starred,
                    "status": "done",
                    "_skipped": False,
                }

            except Exception as e:
                # Try to get match id for error reporting
                try:
                    match_ref = w_db.query(Match).filter(
                        Match.candidate_id == cid, Match.role_id == role_info["id"]
                    ).first()
                    match_id_str = str(match_ref.id) if match_ref else ""
                except Exception:
                    match_id_str = ""

                return {
                    "match_id": match_id_str,
                    "role_id": role_info["id"],
                    "role_title": role_info.get("title", ""),
                    "company_name": role_info.get("company", ""),
                    "status": "error",
                    "error": str(e)[:200],
                    "_skipped": False,
                }
            finally:
                w_db.close()

        try:
            coord_job = coord_db.query(IJModel).filter(IJModel.id == job_id).first()

            # --- Pre-scan: count existing analyses to show accurate skipped count ---
            coord_add_log(coord_job, f"Starting CrossChekk for {len(cids_copy)} candidates x {len(roles_info)} roles ({PARALLEL_WORKERS} workers)")
            coord_db.commit()

            # Build flat list of (cid, cname, candidate_data, role_info) work items
            work_items = []
            # Use a temporary session to preload candidate data (read-only)
            prep_db = SessionLocal()
            try:
                for ci, cid in enumerate(cids_copy):
                    candidate = prep_db.query(Candidate).filter(Candidate.id == cid).first()
                    if not candidate:
                        continue
                    cname = candidate.name or candidate.github_username or "Unknown"
                    candidate_data = {
                        'github_username': candidate.github_username,
                        'name': candidate.name,
                        'archetype': candidate.archetype,
                        'tier': candidate.tier,
                        'tech_stack': candidate.tech_stack or [],
                        'vibe_report': candidate.vibe_report or {},
                        'github_metrics': candidate.github_metrics if hasattr(candidate, 'github_metrics') and candidate.github_metrics else {},
                        'yoe': getattr(candidate, 'yoe', 0) or 0,
                        'current_role': getattr(candidate, 'current_role', None),
                        'current_company': getattr(candidate, 'current_company', None),
                        'location': candidate.location_raw,
                        'notes': getattr(candidate, 'notes', ''),
                        'resume_text': getattr(candidate, 'resume_text', '') or '',
                        'linkedin_text': getattr(candidate, 'linkedin_text', '') or '',
                    }
                    for role_info_item in roles_info:
                        work_items.append((cid, cname, candidate_data, role_info_item))
            finally:
                prep_db.close()

            total_work = len(work_items)

            # Count how many already have cached FitAnalysis results (single query)
            cached_count = 0
            count_db = SessionLocal()
            try:
                cid_rid_pairs = [(cid_w, rinfo_w["id"]) for cid_w, _cname_w, _cdata_w, rinfo_w in work_items]
                # Get all candidate_ids and role_ids involved
                wi_cids = list({p[0] for p in cid_rid_pairs})
                wi_rids = list({p[1] for p in cid_rid_pairs})
                # Bulk-load existing matches for these candidates × roles
                existing_matches = count_db.query(Match.candidate_id, Match.role_id, Match.id).filter(
                    Match.candidate_id.in_(wi_cids),
                    Match.role_id.in_(wi_rids),
                ).all()
                match_lookup = {(str(m[0]), str(m[1])): m[2] for m in existing_matches}
                # Get match_ids that have a FitAnalysis with a score
                match_ids_with_fa = set()
                if match_lookup:
                    fa_results = count_db.query(FitAnalysis.match_id).filter(
                        FitAnalysis.match_id.in_(list(match_lookup.values())),
                        FitAnalysis.fit_score.isnot(None),
                    ).all()
                    match_ids_with_fa = {str(r[0]) for r in fa_results}
                # Count pairs that already have cached results
                for cid_w, rinfo_w_id in cid_rid_pairs:
                    mid = match_lookup.get((cid_w, rinfo_w_id))
                    if mid and str(mid) in match_ids_with_fa:
                        cached_count += 1
            finally:
                count_db.close()

            new_analyses = total_work - cached_count

            cp = coord_job.checkpoint_data or {}
            cp["total_analyses"] = total_work
            cp["new_analyses"] = new_analyses
            cp["cached_count"] = cached_count
            coord_job.checkpoint_data = cp
            flag_modified(coord_job, 'checkpoint_data')
            coord_add_log(coord_job, f"  {cached_count} already cached, {new_analyses} new to analyze")
            coord_db.commit()

            # --- Submit all work items to thread pool ---
            with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
                future_to_info = {}
                for cid, cname, cdata, rinfo in work_items:
                    fut = pool.submit(analyze_one, cid, cname, cdata, rinfo)
                    future_to_info[fut] = (cid, cname, rinfo)

                for future in as_completed(future_to_info):
                    if stop_flag.is_set():
                        break

                    cid, cname, rinfo = future_to_info[future]
                    result = future.result()
                    if result is None:
                        continue

                    with job_lock:
                        # Check for stop periodically
                        if counters["done"] + counters["errors"] + counters["skipped"] > 0 and \
                           (counters["done"] + counters["errors"] + counters["skipped"]) % 10 == 0:
                            if check_stopped(coord_job):
                                break

                        # Update checkpoint_data with result
                        cp = coord_job.checkpoint_data or {}
                        results_map = cp.get("results", {})
                        if cid not in results_map:
                            results_map[cid] = {}
                        # Strip internal _skipped flag before storing
                        was_skipped = result.pop("_skipped", False)
                        results_map[cid][rinfo["id"]] = result

                        cp["results"] = results_map
                        cp["current_candidate"] = cname
                        cp["current_role"] = f"{rinfo['company']} — {rinfo['title']}"
                        coord_job.checkpoint_data = cp

                        if result["status"] == "error":
                            counters["errors"] += 1
                            coord_add_log(coord_job, f"  {rinfo['company']} — {rinfo['title']}: ERROR - {result.get('error', '')[:80]}")
                        elif was_skipped:
                            counters["skipped"] += 1
                            coord_add_log(coord_job, f"  {cname} x {rinfo['company']} — {rinfo['title']}: {result.get('fit_score', 0)} (cached)")
                        else:
                            counters["done"] += 1
                            coord_add_log(coord_job, f"  {cname} x {rinfo['company']} — {rinfo['title']}: {result.get('fit_score', 0)} ({result.get('recommendation', 'SKIP')})")

                        coord_job.current_search = f"{cname}: {rinfo['company']} — {rinfo['title']}"
                        coord_flush(coord_job)

            # Complete
            coord_db.refresh(coord_job)
            if coord_job.status != JS.stopped:
                coord_job.status = JS.completed
                coord_job.completed_at = datetime.utcnow()
                coord_add_log(coord_job, f"CrossChekk complete: {counters['done']} analyzed, {counters['skipped']} cached, {counters['errors']} errors")
                coord_db.commit()

        except Exception as e:
            try:
                coord_job.status = JS.failed
                coord_job.completed_at = datetime.utcnow()
                coord_job.error_message = str(e)[:500]
                coord_db.commit()
            except Exception:
                pass
            logger.error("CrossChekk job %s failed: %s", job_id, e)
        finally:
            coord_db.close()

    thread = threading.Thread(target=run_crosschekk_background, daemon=True)
    thread.start()

    return {
        "success": True,
        "job_id": job_id,
        "total_candidates": len(candidates_info),
        "total_roles": len(roles_info),
        "total_analyses": total_analyses,
        "status": "running",
    }


# ────────────────────────────────────────────────────────────
# Outreach All Matched: preview + generation
# ────────────────────────────────────────────────────────────

# Keywords that indicate a candidate is not interested
_NOT_INTERESTED_KEYWORDS = [
    "not interested",
    "not looking",
    "no thanks",
    "no thank you",
    "please remove",
    "unsubscribe",
    "opt out",
    "opt-out",
    "stop emailing",
    "don't contact",
    "do not contact",
    "not a good fit",
    "pass on this",
    "decline",
    "not open to",
    "happy where i am",
    "not considering",
]


def _is_not_interested(reply_text: str) -> bool:
    """Check if a candidate's reply indicates they are not interested."""
    if not reply_text:
        return False
    lower = reply_text.lower()
    return any(kw in lower for kw in _NOT_INTERESTED_KEYWORDS)


@router.get("/outreach/matched-preview", tags=["outreach"])
def preview_matched_outreach(db: Session = Depends(get_db)):
    """
    Return a preview of all matched candidates eligible for outreach generation.

    Excludes:
    - outreach_status = 'scheduled' (already queued for delivery)
    - status = 'rejected' (dismissed/not interested)
    - warmup_reply_text contains not-interested keywords
    - email is NULL (can't send)

    Includes:
    - Never-contacted candidates (cold outreach)
    - Already-sent candidates without negative reply (follow-up)

    For each candidate, picks the highest fit_score match as the role context.
    Deduplicates across roles (each candidate appears once).
    """
    from app.models.match import Match
    from app.models.fit_analysis import FitAnalysis
    from app.models.candidate import OutreachStatus
    from sqlalchemy import func, case, literal_column

    # Get all unique matched candidate IDs
    matched_ids_q = db.query(func.distinct(Match.candidate_id)).all()
    matched_ids = [str(row[0]) for row in matched_ids_q]

    if not matched_ids:
        return {"candidates": [], "excluded": {"scheduled": 0, "rejected": 0, "not_interested": 0, "no_email": 0}, "total_matched": 0}

    # Load candidates
    candidates = db.query(Candidate).filter(Candidate.id.in_(matched_ids)).all()

    eligible = []
    excluded = {"scheduled": 0, "rejected": 0, "not_interested": 0, "no_email": 0}

    for c in candidates:
        # Exclusion checks
        if not c.email:
            excluded["no_email"] += 1
            continue
        if c.outreach_status == OutreachStatus.scheduled:
            excluded["scheduled"] += 1
            continue
        if c.status and c.status.value == 'rejected':
            excluded["rejected"] += 1
            continue
        if c.warmup_reply_text and _is_not_interested(c.warmup_reply_text):
            excluded["not_interested"] += 1
            continue

        # Find best match (highest fit_score) for this candidate
        best_fit = (
            db.query(FitAnalysis)
            .filter(FitAnalysis.candidate_id == c.id)
            .order_by(FitAnalysis.fit_score.desc().nullslast())
            .first()
        )

        # Fall back to any match if no fit analysis exists
        best_match = (
            db.query(Match)
            .filter(Match.candidate_id == c.id)
            .order_by(Match.match_score.desc().nullslast())
            .first()
        )

        role_id = None
        role_title = "General"
        company_name = ""
        fit_score = 0

        if best_fit and best_fit.role_id:
            role_id = str(best_fit.role_id)
            fit_score = best_fit.fit_score or 0
            role = db.query(Role).filter(Role.id == best_fit.role_id).first()
            if role:
                role_title = role.title
                company_name = role.company_name or ""
        elif best_match and best_match.role_id:
            role_id = str(best_match.role_id)
            fit_score = best_match.match_score or 0
            role = db.query(Role).filter(Role.id == best_match.role_id).first()
            if role:
                role_title = role.title
                company_name = role.company_name or ""

        already_sent = (
            (c.outreach_status and c.outreach_status.value == 'sent')
            or c.warmup_email_sent_at is not None
        )

        eligible.append({
            "id": str(c.id),
            "name": c.name or c.github_username or "Unknown",
            "email": c.email,
            "archetype": c.archetype,
            "tier": c.tier,
            "role_id": role_id,
            "role_title": role_title,
            "company_name": company_name,
            "fit_score": fit_score,
            "is_followup": already_sent,
            "prev_outreach_subject": c.sent_outreach_subject or c.outreach_subject if already_sent else None,
            "warmup_replied": c.warmup_replied_at is not None,
            "warmup_opened": c.warmup_email_opened_at is not None,
        })

    # Sort by fit_score descending
    eligible.sort(key=lambda x: x["fit_score"], reverse=True)

    return {
        "candidates": eligible,
        "excluded": excluded,
        "total_matched": len(matched_ids),
    }


# ────────────────────────────────────────────────────────────
# Starred page: bulk outreach generation (background job)
# ────────────────────────────────────────────────────────────

class StarredOutreachRequest(BaseModel):
    candidate_ids: List[str]
    role_map: Dict[str, str] = {}  # { candidateId: roleId } — best role for each candidate


@router.get("/outreach/bulk-generate/active", tags=["outreach"])
def get_active_outreach_generation_job(db: Session = Depends(get_db)):
    """Check for any active starred outreach generation job."""
    from app.models.ingestion_job import IngestionJob, JobStatus
    job = db.query(IngestionJob).filter(
        IngestionJob.job_type == 'starred_outreach',
        IngestionJob.status.in_([JobStatus.pending, JobStatus.running]),
    ).order_by(IngestionJob.created_at.desc()).first()
    if job:
        return {"active": True, "job_id": str(job.id), "status": job.status.value}
    return {"active": False, "job_id": None}


@router.post("/outreach/bulk-generate/start", tags=["outreach"])
def start_starred_outreach_job(
    body: StarredOutreachRequest,
    db: Session = Depends(get_db),
):
    """
    Start a background job to generate outreach emails for starred candidates.

    Follows the same pattern as CrossChekk: parallel workers, IngestionJob for
    progress tracking, results stored in checkpoint_data.

    The backend handles follow-up vs cold routing automatically based on each
    candidate's outreach_status, warmup_email_sent_at, opened, replied, etc.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    import threading

    candidate_ids = body.candidate_ids
    role_map = body.role_map
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="No candidate_ids provided")

    # Check for existing running job
    existing = db.query(IngestionJob).filter(
        IngestionJob.job_type == 'starred_outreach',
        IngestionJob.status.in_([JobStatus.pending, JobStatus.running]),
    ).first()
    if existing:
        return {
            "success": False,
            "message": "An outreach generation job is already running",
            "job_id": str(existing.id),
            "status": existing.status.value,
        }

    # Validate candidates and gather info
    candidates_info = []
    for cid in candidate_ids:
        c = crud.get_candidate(db, cid)
        if c and c.email:
            candidates_info.append({
                "id": str(c.id),
                "name": c.name or c.github_username or "Unknown",
                "email": c.email,
                "role_id": role_map.get(cid),
            })

    if not candidates_info:
        raise HTTPException(status_code=400, detail="No valid candidates with email found")

    # Create job
    job = IngestionJob(
        status=JobStatus.running,
        job_type='starred_outreach',
        total_candidates=len(candidates_info),
        processed_count=0,
        candidates_saved=0,
        error_count=0,
        recent_logs=[],
        checkpoint_data={
            "candidates": candidates_info,
            "emails": {},  # { candidateId: BulkEmail-compatible object }
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_id = str(job.id)
    cinfo_copy = list(candidates_info)

    def run_outreach_background():
        from app.db.base import SessionLocal
        from app.models.ingestion_job import IngestionJob as IJModel, JobStatus as JS
        from app.core.config import settings
        from app.services.outreach_generator import generate_outreach_template, generate_role_pitch
        from app.services.github_ingestion import token_rotator
        from app.models.fit_analysis import FitAnalysis
        from sqlalchemy.orm.attributes import flag_modified
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading as _threading

        PARALLEL_WORKERS = 4

        job_lock = _threading.Lock()
        counters = {"done": 0, "errors": 0}
        stop_flag = _threading.Event()

        coord_db = SessionLocal()

        def coord_add_log(coord_job, message):
            timestamp = datetime.utcnow().strftime('%H:%M:%S')
            logs = coord_job.recent_logs or []
            logs.append({'timestamp': timestamp, 'message': message})
            coord_job.recent_logs = logs[-200:]
            flag_modified(coord_job, 'recent_logs')

        def coord_flush(coord_job):
            coord_job.processed_count = counters["done"] + counters["errors"]
            coord_job.candidates_saved = counters["done"]
            coord_job.error_count = counters["errors"]
            flag_modified(coord_job, 'checkpoint_data')
            coord_db.commit()

        def check_stopped(coord_job) -> bool:
            coord_db.refresh(coord_job)
            if coord_job.status == JS.stopped:
                stop_flag.set()
                return True
            return False

        def generate_one(cinfo: dict):
            """Worker: generate outreach for one candidate. Own DB session."""
            if stop_flag.is_set():
                return None

            cid = cinfo["id"]
            role_id = cinfo.get("role_id")
            w_db = SessionLocal()
            try:
                candidate = w_db.query(Candidate).filter(Candidate.id == cid).first()
                if not candidate:
                    return {"candidate_id": cid, "error": "Not found"}

                if not candidate.vibe_report:
                    # Auto-analyze: run VibeChekk inline before generating outreach
                    try:
                        from app.services.candidate_analysis import run_candidate_analysis as _run_analysis
                        _run_analysis(candidate.id, w_db)
                        w_db.refresh(candidate)
                    except Exception as e:
                        logger.error("Auto-analyze failed for %s: %s", cid, e)
                        return {"candidate_id": cid, "error": f"Auto-analyze failed: {str(e)[:100]}"}

                # Determine follow-up vs cold
                already_sent = (
                    (candidate.outreach_status and candidate.outreach_status.value == 'sent')
                    or candidate.warmup_email_sent_at is not None
                )
                is_followup = already_sent

                # Build candidate data for outreach generator
                candidate_data = {
                    'id': str(candidate.id),
                    'name': candidate.name,
                    'github_username': candidate.github_username,
                    'email': candidate.email,
                    'archetype': candidate.archetype,
                    'tier': candidate.tier,
                    'vibe_report': candidate.vibe_report or {},
                    'github_languages': candidate.github_languages or [],
                }

                # Get role context if role_id provided
                role_context = None
                fit_analysis_data = None
                role_obj = None
                if role_id:
                    role_obj = w_db.query(Role).filter(Role.id == role_id).first()
                    if role_obj:
                        comp_str = ''
                        if role_obj.comp_max:
                            comp_str = f"up to ${role_obj.comp_max // 1000}K"
                        elif role_obj.comp_min:
                            comp_str = f"${role_obj.comp_min // 1000}K+"
                        loc_req = role_obj.location_requirement.value if role_obj.location_requirement else ''
                        loc_cities = ', '.join(role_obj.location_cities) if role_obj.location_cities else ''
                        if loc_req == 'remote':
                            location_str = 'Remote'
                        elif loc_cities:
                            location_str = f"{loc_cities} ({loc_req})" if loc_req else loc_cities
                        else:
                            location_str = loc_req.capitalize() if loc_req else 'Flexible'
                        role_context = {
                            'company': role_obj.company_name,
                            'title': role_obj.title,
                            'description': role_obj.jd_text or '',
                            'tech_stack': role_obj.tech_stack or [],
                            'comp': comp_str,
                            'equity': 'significant equity' if comp_str else '',
                            'location': location_str,
                            'stage': role_obj.company_stage.value.replace('_', ' ') if role_obj.company_stage else '',
                            'investors': role_obj.notable_investors or [],
                        }
                        # Get fit analysis
                        fit = w_db.query(FitAnalysis).filter(
                            FitAnalysis.candidate_id == cid,
                            FitAnalysis.role_id == role_id,
                        ).order_by(FitAnalysis.created_at.desc()).first()
                        if fit:
                            fit_analysis_data = {
                                'fit_score': fit.fit_score,
                                'recommendation': fit.recommendation,
                                'strengths': fit.strengths or [],
                                'concerns': fit.concerns or [],
                                'ai_summary': fit.ai_summary,
                            }

                # Route: follow-up vs cold
                result = None
                if already_sent and role_id and role_context:
                    # Follow-up / role pitch
                    candidate_opened = (
                        candidate.warmup_email_opened_at is not None
                        or candidate.warmup_replied_at is not None
                    )
                    email_history = {
                        'outreach_subject': candidate.sent_outreach_subject or candidate.outreach_subject or '',
                        'outreach_body': candidate.sent_outreach_body or candidate.outreach_body or '',
                        'reply_text': candidate.warmup_reply_text or '',
                        'followup_body': candidate.followup_body or '',
                    }
                    role_data = {
                        'title': role_context.get('title', 'Software Engineer'),
                        'company': role_context.get('company', 'a startup'),
                        'jd_text': role_context.get('description', ''),
                        'tech_stack': role_context.get('tech_stack', []),
                        'comp': role_context.get('comp', ''),
                        'equity': role_context.get('equity', ''),
                        'location': role_context.get('location', 'Flexible'),
                        'stage': role_context.get('stage', ''),
                        'investors': role_context.get('investors', []),
                    }
                    candidate_for_pitch = {
                        'name': candidate.name,
                        'github_username': candidate.github_username,
                        'archetype': candidate.archetype,
                        'tier': candidate.tier,
                        'tech_stack': candidate.tech_stack or candidate.github_languages or [],
                        'linkedin_text': candidate.linkedin_text or '',
                        'resume_text': candidate.resume_text or '',
                    }
                    try:
                        result = generate_role_pitch(
                            api_key=settings.DEEPSEEK_API_KEY,
                            candidate=candidate_for_pitch,
                            role=role_data,
                            email_history=email_history,
                            fit_analysis=fit_analysis_data,
                            candidate_opened=candidate_opened,
                        )
                    except Exception as e:
                        logger.error("Role pitch failed for %s, falling back to cold: %s", cid, e)
                        # Fall through to cold outreach

                if not result or not result.get('success'):
                    # Cold outreach
                    github_token = token_rotator.get_token()
                    result = generate_outreach_template(
                        api_key=settings.DEEPSEEK_API_KEY,
                        candidate=candidate_data,
                        github_token=github_token,
                        role_context=role_context,
                        fit_analysis=fit_analysis_data,
                    )

                if result.get('success') and result.get('subject') and result.get('body'):
                    # Persist draft
                    from app.models.candidate import OutreachStatus as OS
                    if already_sent and role_id:
                        # Save to match draft only
                        match = w_db.query(Match).filter(
                            Match.candidate_id == cid, Match.role_id == role_id
                        ).first()
                        if match:
                            match.draft_subject = result['subject']
                            match.draft_body = result['body']
                    else:
                        candidate.outreach_subject = result['subject']
                        candidate.outreach_body = result['body']
                        candidate.outreach_status = OS.drafted
                        candidate.outreach_type = "role_specific" if role_id else "generic"
                        # Store denormalized role label for outreach queue display
                        if role_id and role_obj:
                            candidate.outreach_role_title = f"{role_obj.title} @ {role_obj.company_name}" if role_obj.title and role_obj.company_name else (role_obj.title or role_obj.company_name or None)
                        elif not role_id:
                            candidate.outreach_role_title = None
                        if role_id:
                            match = w_db.query(Match).filter(
                                Match.candidate_id == cid, Match.role_id == role_id
                            ).first()
                            if match:
                                match.draft_subject = result['subject']
                                match.draft_body = result['body']
                    w_db.commit()

                    return {
                        "candidate_id": cid,
                        "name": cinfo["name"],
                        "email": cinfo["email"],
                        "role_title": role_obj.title if role_obj else "General",
                        "company_name": role_obj.company_name if role_obj else "",
                        "fit_score": fit_analysis_data.get('fit_score', 0) if fit_analysis_data else 0,
                        "subject": result['subject'],
                        "body": result['body'],
                        "is_followup": is_followup,
                    }
                else:
                    return {"candidate_id": cid, "error": "Generation returned no content"}

            except Exception as e:
                try:
                    w_db.rollback()
                except Exception:
                    pass
                logger.error("Outreach generation failed for %s: %s", cid, e)
                return {"candidate_id": cid, "error": str(e)[:200]}
            finally:
                w_db.close()

        try:
            coord_job = coord_db.query(IJModel).filter(IJModel.id == job_id).first()
            coord_add_log(coord_job, f"Starting outreach generation for {len(cinfo_copy)} candidates ({PARALLEL_WORKERS} workers)")
            coord_db.commit()

            with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
                future_to_cinfo = {
                    pool.submit(generate_one, ci): ci for ci in cinfo_copy
                }

                for future in as_completed(future_to_cinfo):
                    if stop_flag.is_set():
                        break

                    ci = future_to_cinfo[future]
                    result = future.result()
                    if result is None:
                        continue

                    with job_lock:
                        if (counters["done"] + counters["errors"]) % 5 == 0:
                            if check_stopped(coord_job):
                                break

                        cp = coord_job.checkpoint_data or {}
                        emails_map = cp.get("emails", {})
                        cid = result.get("candidate_id", ci["id"])

                        if result.get("error"):
                            counters["errors"] += 1
                            emails_map[cid] = {
                                "candidate_id": cid,
                                "name": ci["name"],
                                "email": ci["email"],
                                "role_title": "",
                                "company_name": "",
                                "fit_score": 0,
                                "subject": "",
                                "body": "",
                                "is_followup": False,
                                "error": result["error"],
                            }
                            coord_add_log(coord_job, f"  {ci['name']}: ERROR - {result['error'][:80]}")
                        else:
                            counters["done"] += 1
                            emails_map[cid] = result
                            label = "follow-up" if result.get("is_followup") else "cold"
                            coord_add_log(coord_job, f"  {ci['name']} -> {result.get('company_name', '')} ({label})")

                        cp["emails"] = emails_map
                        coord_job.checkpoint_data = cp
                        coord_job.current_search = ci["name"]
                        coord_flush(coord_job)

            # Complete
            coord_db.refresh(coord_job)
            if coord_job.status != JS.stopped:
                coord_job.status = JS.completed
                coord_job.completed_at = datetime.utcnow()
                coord_add_log(coord_job, f"Outreach generation complete: {counters['done']} generated, {counters['errors']} errors")
                coord_db.commit()

        except Exception as e:
            try:
                coord_job.status = JS.failed
                coord_job.completed_at = datetime.utcnow()
                coord_job.error_message = str(e)[:500]
                coord_db.commit()
            except Exception:
                pass
            logger.error("Starred outreach job %s failed: %s", job_id, e)
        finally:
            coord_db.close()

    thread = threading.Thread(target=run_outreach_background, daemon=True)
    thread.start()

    return {
        "success": True,
        "job_id": job_id,
        "total_candidates": len(candidates_info),
        "status": "running",
    }


# ---------------------------------------------------------------------------
# Admin: Resend Inbox Browser
# ---------------------------------------------------------------------------
@router.get("/admin/resend-inbox", tags=["admin"])
def list_resend_inbox(email_id: str = None):
    """List received emails from Resend, or fetch a specific one by ID."""
    import requests as http_requests
    api_key = settings.RESEND_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY not configured")

    headers = {"Authorization": f"Bearer {api_key}"}

    if email_id:
        # Fetch specific email detail
        resp = http_requests.get(
            f"https://api.resend.com/emails/receiving/{email_id}",
            headers=headers, timeout=30,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()

    # List all received emails
    resp = http_requests.get(
        "https://api.resend.com/emails/receiving",
        headers=headers, timeout=30,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()

# ---------------------------------------------------------------------------
# MCP: Agent Registration and Discovery
# ---------------------------------------------------------------------------
@router.post("/mcp", tags=["mcp"])
def handle_mcp_post(request: dict = Body(...)):
    """Handle MCP protocol requests for agent registration and tool discovery"""

    method = request.get("method")
    params = request.get("params", {})
    request_id = request.get("id", "")

    # Handle tools/list request
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {"name": "discover_server", "description": "Discover the Chekk MCP server and available tools"},
                    {"name": "register_agent", "description": "Register a new agent and get a registration token"},
                    {"name": "redeem_token", "description": "Redeem a registration token for an API key"},
                ]
            },
        }

    # Handle tools/call request
    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        if tool_name == "discover_server":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "status": "success",
                    "server": {
                        "name": "chekk-gateway",
                        "type": "http",
                        "url": "https://chekk-deploy-production.up.railway.app/api/v1/mcp",
                        "description": "Chekk Gateway MCP Server",
                    },
                    "tools": [
                        {"name": "discover_server", "description": "Discover the Chekk MCP server"},
                        {"name": "register_agent", "description": "Register a new agent"},
                        {"name": "redeem_token", "description": "Redeem registration token"},
                    ],
                },
            }

        if tool_name == "register_agent":
            handle = tool_args.get("handle")
            name = tool_args.get("name")

            if not handle or not name:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": "Missing handle or name"},
                }

            import secrets
            token = f"chekk_reg_{secrets.token_urlsafe(24)}"

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "status": "success",
                    "handle": handle,
                    "name": name,
                    "token": token,
                    "expires_in": 3600,
                },
            }

        if tool_name == "redeem_token":
            handle = tool_args.get("handle")
            token = tool_args.get("token")

            if not handle or not token:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": "Missing handle or token"},
                }

            import secrets
            from uuid import uuid4

            api_key = f"sk_{secrets.token_urlsafe(24)}"
            agent_id = str(uuid4())

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "status": "success",
                    "handle": handle,
                    "agent_id": agent_id,
                    "api_key": api_key,
                    "credentials_location": f"~/.hermes/credentials/{handle}.json",
                },
            }

        # Unknown tool
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
        }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }
