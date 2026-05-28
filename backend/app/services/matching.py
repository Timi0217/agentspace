from sqlalchemy.orm import Session
from typing import List, Dict, Optional
from app.models.candidate import Candidate
from app.models.role import Role
from app.models.match import Match
from app.services.scoring import calculate_match_score, check_city_match
from app.core.logging import get_logger

logger = get_logger(__name__)


def _get_warmth(candidate: Candidate) -> str:
    """Determine warmth level: cold, sent, opened, or warm."""
    # Warm: replied, completed screening, or clicked screening link
    if candidate.screening_status == 'completed':
        return 'warm'
    if candidate.warmup_replied_at:
        return 'warm'
    os = candidate.outreach_status
    if os == 'replied':
        return 'warm'
    if candidate.screening_link_clicked_at:
        return 'warm'
    # Opened: email opened but no reply
    if candidate.warmup_email_opened_at:
        return 'opened'
    if os in ('opened', 'clicked'):
        return 'opened'
    # Sent: email sent but not opened
    if os in ('sent', 'screening_sent'):
        return 'sent'
    if candidate.warmup_email_sent_at:
        return 'sent'
    return 'cold'


def filter_candidates_for_role(
    db: Session,
    role: Role,
    filters: Optional[Dict] = None,
) -> List[Candidate]:
    """
    Filter candidates that are eligible for a specific role.

    Filters by:
    - Must have been analyzed (has archetype)
    - Location: must fit (if not remote)
      - If role has specific cities, include candidates from those cities
        even if their country-tier fit is 'weak'
    - Must-have skill gate: candidate must cover at least 1 must-have
      skill cluster (if the role has required_skills_priority defined)
    - Optional extra filters: tier, archetype, warmth, exclusive
    """
    from app.services.skill_clusters import (
        get_candidate_clusters, get_clusters_for_skill, get_role_clusters,
    )

    filters = filters or {}
    query = db.query(Candidate)

    # Restrict to specific candidate IDs (e.g., from targeted sourcing)
    # When candidate_ids is provided, skip archetype/location/skill filters
    # since these candidates were explicitly selected and may not have been
    # through VibeChekk analysis yet.
    if filters.get('candidate_ids'):
        candidates = db.query(Candidate).filter(
            Candidate.id.in_(filters['candidate_ids'])
        ).all()
        return candidates

    # Must have been analyzed (has archetype from VibeChekk)
    query = query.filter(Candidate.archetype.isnot(None))

    # Exclude dormant candidates unless explicitly including them
    if not filters.get('include_dormant'):
        query = query.filter(
            (Candidate.dormant == False) | (Candidate.dormant.is_(None))
        )

    # Tier filter
    if filters.get('tier'):
        query = query.filter(Candidate.tier == filters['tier'])

    # Archetype filter
    if filters.get('archetype'):
        query = query.filter(Candidate.archetype == filters['archetype'])

    # Previously starred filter (candidates who've been starred on any role)
    if filters.get('previously_starred'):
        query = query.filter(Candidate.star_count > 0)

    # Location fit filter (override the automatic location logic)
    if filters.get('location_fit'):
        loc_val = filters['location_fit']
        if loc_val == 'strong_medium':
            query = query.filter(Candidate.location_fit.in_(['strong', 'medium']))
        else:
            query = query.filter(Candidate.location_fit == loc_val)

    # Location: must fit (if not remote)
    if role.location_requirement and role.location_requirement.value != 'remote':
        if role.location_cities and len(role.location_cities) > 0:
            # Role has specific cities - get all strong/medium candidates first,
            # then also include any candidate who matches the role's cities
            # (even if their country tier is 'weak' - e.g. Belgrade, Serbia)
            tier_candidates = query.filter(
                Candidate.location_fit.in_(['strong', 'medium'])
            ).all()

            # Also get candidates with 'weak' fit who might be in the right city
            weak_candidates = query.filter(
                Candidate.location_fit == 'weak'
            ).all()

            # Check weak-fit candidates against role cities
            city_matched = [
                c for c in weak_candidates
                if check_city_match(c.location_raw, role.location_cities)
            ]

            if city_matched:
                logger.info(
                    "City-match rescued %d candidates for role %s (%s): %s",
                    len(city_matched), role.title, ', '.join(role.location_cities),
                    ', '.join(c.location_raw or '?' for c in city_matched[:5])
                )

            candidates = tier_candidates + city_matched
        else:
            query = query.filter(Candidate.location_fit.in_(['strong', 'medium']))
            candidates = query.all()
    else:
        candidates = query.all()

    # --- Must-have skill gate ---
    # If the role has required_skills_priority with must-have items,
    # exclude candidates who don't cover ANY must-have skill cluster.
    priority = role.required_skills_priority or {}
    must_have_clusters = set()
    for skill, prio in priority.items():
        if prio == 'must_have':
            must_have_clusters.update(get_clusters_for_skill(skill))

    if must_have_clusters:
        before_count = len(candidates)
        filtered = []
        for c in candidates:
            c_clusters = get_candidate_clusters(
                tech_stack=c.tech_stack,
                vibe_report=c.vibe_report,
                github_languages=c.github_languages,
            )
            if c_clusters & must_have_clusters:
                filtered.append(c)
        candidates = filtered
        logger.info(
            "Must-have gate for %s: %d → %d candidates (must-have clusters: %s)",
            role.title, before_count, len(candidates),
            ', '.join(sorted(must_have_clusters)),
        )

    # Warmth filter (applied in-memory since it's computed from multiple fields)
    warmth_filter = filters.get('warmth')
    if warmth_filter:
        candidates = [c for c in candidates if _get_warmth(c) == warmth_filter]

    # Exclusive filter: only candidates not matched to any other role
    if filters.get('exclusive'):
        exclude_role_id = filters.get('exclude_role_id')
        candidate_ids = [c.id for c in candidates]
        if candidate_ids:
            matched_elsewhere_q = db.query(Match.candidate_id).filter(
                Match.candidate_id.in_(candidate_ids)
            )
            if exclude_role_id:
                matched_elsewhere_q = matched_elsewhere_q.filter(Match.role_id != exclude_role_id)
            matched_elsewhere = {row[0] for row in matched_elsewhere_q.distinct().all()}
            candidates = [c for c in candidates if c.id not in matched_elsewhere]

    return candidates


def generate_matches_for_role(
    db: Session,
    role_id: str,
    limit: int = 20,
    filters: Optional[Dict] = None,
) -> List[Dict]:
    """
    Generate and score matches for a specific role.

    Process:
    1. Filter candidates that match basic criteria
    2. Score each candidate against the role
    3. Sort by score descending
    4. Return top N matches

    Returns: List of dicts with candidate, score, and breakdown
    """
    from app.api.crud import get_role

    role = get_role(db, role_id)
    if not role:
        return []

    # Filter candidates
    candidates = filter_candidates_for_role(db, role, filters=filters)

    # Score each candidate
    scored = []
    for candidate in candidates:
        score, breakdown = calculate_match_score(candidate, role)
        scored.append({
            'candidate': candidate,
            'candidate_id': candidate.id,
            'score': score,
            'breakdown': breakdown
        })

    # Sort by score descending
    scored.sort(key=lambda x: x['score'], reverse=True)

    # Return top N
    return scored[:limit]


def create_matches_for_role(
    db: Session,
    role_id: str,
    limit: int = 20,
    filters: Optional[Dict] = None,
    progress_callback: Optional[callable] = None,
) -> List[Match]:
    """
    Create Match records in the database for a specific role.

    This runs CrossChekk analysis on each candidate to get AI-powered
    candidate-role fit scoring with SEND/SKIP recommendations.

    progress_callback(candidate_index, total_candidates, candidate_name, score, status)
    is called after each candidate is processed.
    """
    from app.api.crud import create_match, get_role, get_candidate
    from app.schemas.match import MatchCreate
    from app.services.fit_score_calculator import calculate_fit_score, parse_jd
    from app.models.fit_analysis import FitAnalysis
    from app.core.config import settings

    role = get_role(db, role_id)
    if not role:
        return []

    matches_data = generate_matches_for_role(db, role_id, limit, filters=filters)

    total_candidates = len(matches_data)
    if progress_callback:
        progress_callback(0, total_candidates, '', None, 'started')

    # Parse JD once for all candidates
    parsed_jd = parse_jd(role.jd_text or "", role.title)

    created_matches = []
    for ci, match_data in enumerate(matches_data):
        candidate = get_candidate(db, match_data['candidate_id'])
        if not candidate:
            continue

        # Check if match already exists
        existing = db.query(Match).filter(
            Match.candidate_id == match_data['candidate_id'],
            Match.role_id == role_id
        ).first()

        if existing:
            match = existing
        else:
            # Create new match
            match_create = MatchCreate(
                candidate_id=match_data['candidate_id'],
                role_id=role_id,
                match_score=match_data['score'],
                score_breakdown=match_data['breakdown']
            )
            match = create_match(db, match_create)

        # Run CrossChekk analysis if DeepSeek is configured
        if settings.DEEPSEEK_API_KEY:
            try:
                logger.info("Analyzing %s for %s - %s", candidate.github_username or candidate.name, role.company_name, role.title)

                # Get vibe_report - fetch from public profile if missing
                vibe_report = candidate.vibe_report or {}

                # If vibe_report is empty but candidate has archetype, try fetching from public profile
                if (not vibe_report or not vibe_report.get('trajectory_summary')) and candidate.github_username:
                    logger.debug("vibe_report missing, trying to fetch from public API")
                    try:
                        import requests
                        import os
                        # Use RAILWAY_PUBLIC_DOMAIN if available, otherwise fall back to localhost
                        api_host = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost:8000")
                        api_scheme = "https" if "railway" in api_host else "http"
                        response = requests.get(
                            f"{api_scheme}://{api_host}/api/v1/public/candidates/{candidate.github_username}",
                            timeout=10
                        )
                        if response.ok:
                            profile_data = response.json()
                            if profile_data.get('success') and profile_data.get('candidate', {}).get('vibe_report'):
                                vibe_report = profile_data['candidate']['vibe_report']
                                logger.info("Fetched vibe_report from public profile")
                    except Exception as e:
                        logger.error("Failed to fetch public profile: %s", e)

                if (not vibe_report or not vibe_report.get('trajectory_summary')) and candidate.github_username:
                    logger.warning("No vibe_report available for %s", candidate.github_username)

                # Build tech_stack from multiple sources
                tech_stack = candidate.tech_stack or []

                if not tech_stack and vibe_report.get('verified_skills'):
                    tech_stack = [skill.get('name') for skill in vibe_report.get('verified_skills', []) if skill.get('name')]

                if not tech_stack and candidate.github_languages:
                    tech_stack = candidate.github_languages

                # Prepare comprehensive candidate data for CrossChekk
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
                        "languages": candidate.github_languages or []
                    },
                    "vibe_report": vibe_report
                }

                # Calculate fit score using CrossChekk
                fit_result = calculate_fit_score(settings.DEEPSEEK_API_KEY, candidate_data, parsed_jd)

                # Delete old FitAnalysis records for this match to avoid duplicates
                db.query(FitAnalysis).filter(
                    FitAnalysis.match_id == match.id
                ).delete()
                db.commit()

                # Save fit analysis
                fit_analysis = FitAnalysis(
                    candidate_id=candidate.id,
                    role_id=role.id,
                    match_id=match.id,
                    fit_score=fit_result.get('fitScore', 0),
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
                    full_analysis=fit_result
                )

                db.add(fit_analysis)

                # Update match with CrossChekk score
                match.match_score = fit_result.get('fitScore', 0)
                match.score_breakdown = {
                    **match_data['breakdown'],
                    'crosschekk_score': fit_result.get('fitScore', 0),
                    'recommendation': fit_result.get('recommendation')
                }
                db.commit()
                db.refresh(match)

                logger.info("%s: %s - %s", candidate.github_username or candidate.name, fit_result.get('fitScore'), fit_result.get('recommendation'))
            except Exception as e:
                logger.error("Error analyzing %s: %s", candidate.github_username or candidate.name, e)
                # Continue with basic scoring if CrossChekk fails
                match.match_score = match_data['score']
                match.score_breakdown = match_data['breakdown']
                db.commit()
                db.refresh(match)
        else:
            # No CrossChekk, use basic scoring
            match.match_score = match_data['score']
            match.score_breakdown = match_data['breakdown']
            db.commit()
            db.refresh(match)

        created_matches.append(match)

        # Report per-candidate progress
        if progress_callback:
            cname = candidate.github_username or candidate.name or 'Unknown'
            cscore = match.match_score
            progress_callback(ci + 1, total_candidates, cname, cscore, 'analyzed')

    return created_matches


def regenerate_all_matches(db: Session, limit: int = 20) -> Dict[str, int]:
    """
    Regenerate matches for all active roles.

    Args:
        limit: Number of matches to generate per role.

    Returns: Dict with counts of matches created per role
    """
    from app.api.crud import get_roles

    # Get all active roles
    roles = get_roles(db, status='searching', limit=1000)

    results = {}
    for role in roles:
        matches = create_matches_for_role(db, role.id, limit=limit)
        results[str(role.id)] = len(matches)

    return results
