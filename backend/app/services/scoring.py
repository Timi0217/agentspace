import re
from typing import Dict, List, Optional, Tuple
from app.models.candidate import Candidate
from app.models.role import Role


# City aliases: map common abbreviations/nicknames to canonical names
_CITY_ALIASES = {
    'sf': 'san francisco', 'sf bay area': 'san francisco', 'bay area': 'san francisco',
    'silicon valley': 'san francisco', 'nyc': 'new york', 'new york city': 'new york',
    'la': 'los angeles', 'philly': 'philadelphia', 'atl': 'atlanta',
    'dc': 'washington dc', 'dfw': 'dallas', 'chicagoland': 'chicago',
    'socal': 'los angeles', 'norcal': 'san francisco',
    'cambridge': 'boston',  # Close enough for matching purposes
    'bellevue': 'seattle', 'redmond': 'seattle', 'kirkland': 'seattle',
    'palo alto': 'san francisco', 'santa clara': 'san francisco',
    'sunnyvale': 'san francisco', 'mountain view': 'san francisco',
    'cupertino': 'san francisco', 'menlo park': 'san francisco',
    'redwood city': 'san francisco', 'berkeley': 'san francisco',
    'oakland': 'san francisco',
    'brooklyn': 'new york', 'manhattan': 'new york', 'queens': 'new york',
    'fort worth': 'dallas', 'plano': 'dallas',
    'fort lauderdale': 'miami', 'st petersburg': 'tampa',
    'bethesda': 'washington dc', 'arlington': 'washington dc', 'reston': 'washington dc',
    'kitchener': 'waterloo', 'kitchener-waterloo': 'waterloo',
    'scottsdale': 'phoenix', 'tempe': 'phoenix', 'mesa': 'phoenix',
    'durham': 'raleigh', 'chapel hill': 'raleigh', 'research triangle': 'raleigh',
}

# State abbreviation to full name
_STATE_ABBR = {
    'ca': 'california', 'ny': 'new york', 'tx': 'texas', 'fl': 'florida',
    'il': 'illinois', 'pa': 'pennsylvania', 'oh': 'ohio', 'ga': 'georgia',
    'nc': 'north carolina', 'mi': 'michigan', 'nj': 'new jersey',
    'va': 'virginia', 'wa': 'washington', 'az': 'arizona', 'ma': 'massachusetts',
    'tn': 'tennessee', 'in': 'indiana', 'mo': 'missouri', 'md': 'maryland',
    'wi': 'wisconsin', 'co': 'colorado', 'mn': 'minnesota', 'sc': 'south carolina',
    'al': 'alabama', 'la': 'louisiana', 'ky': 'kentucky', 'or': 'oregon',
    'ok': 'oklahoma', 'ct': 'connecticut', 'ut': 'utah', 'nv': 'nevada',
    'ar': 'arkansas', 'ms': 'mississippi', 'ks': 'kansas', 'nm': 'new mexico',
    'ne': 'nebraska', 'id': 'idaho', 'hi': 'hawaii', 'me': 'maine',
    'nh': 'new hampshire', 'ri': 'rhode island', 'mt': 'montana',
    'de': 'delaware', 'sd': 'south dakota', 'nd': 'north dakota',
    'vt': 'vermont', 'wy': 'wyoming',
}

# Map cities to the state they're in for cross-referencing
_CITY_TO_STATE = {
    'san francisco': 'california', 'los angeles': 'california', 'san diego': 'california',
    'san jose': 'california', 'sacramento': 'california',
    'new york': 'new york', 'buffalo': 'new york',
    'chicago': 'illinois',
    'houston': 'texas', 'dallas': 'texas', 'austin': 'texas', 'san antonio': 'texas',
    'miami': 'florida', 'orlando': 'florida', 'tampa': 'florida', 'jacksonville': 'florida',
    'atlanta': 'georgia', 'savannah': 'georgia',
    'seattle': 'washington', 'tacoma': 'washington',
    'boston': 'massachusetts',
    'portland': 'oregon',
    'denver': 'colorado', 'boulder': 'colorado',
    'phoenix': 'arizona', 'tucson': 'arizona',
    'detroit': 'michigan', 'ann arbor': 'michigan',
    'minneapolis': 'minnesota',
    'charlotte': 'north carolina', 'raleigh': 'north carolina',
    'philadelphia': 'pennsylvania', 'pittsburgh': 'pennsylvania',
    'columbus': 'ohio', 'cleveland': 'ohio', 'cincinnati': 'ohio',
    'nashville': 'tennessee', 'memphis': 'tennessee',
    'baltimore': 'maryland',
    'washington dc': 'washington dc',
    'las vegas': 'nevada',
    'indianapolis': 'indiana',
    'salt lake city': 'utah',
    'belgrade': 'serbia',
    'london': 'united kingdom', 'berlin': 'germany', 'munich': 'germany',
    'paris': 'france', 'amsterdam': 'netherlands', 'dublin': 'ireland',
    'toronto': 'canada', 'vancouver': 'canada', 'montreal': 'canada',
    'sydney': 'australia', 'melbourne': 'australia',
    'tel aviv': 'israel', 'singapore': 'singapore', 'tokyo': 'japan',
    'bangalore': 'india', 'mumbai': 'india', 'hyderabad': 'india',
    'são paulo': 'brazil', 'sao paulo': 'brazil',
}

# Country aliases
_COUNTRY_ALIASES = {
    'usa': 'united states', 'us': 'united states', 'u.s.': 'united states',
    'u.s.a.': 'united states', 'uk': 'united kingdom', 'england': 'united kingdom',
    'scotland': 'united kingdom', 'wales': 'united kingdom',
    'deutschland': 'germany', 'brasil': 'brazil',
}


def _normalize_for_matching(text: str) -> str:
    """Lowercase, strip, remove emojis and punctuation noise for matching."""
    if not text:
        return ''
    text = text.lower().strip()
    # Strip emojis
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    text = re.sub(r'[\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f\u200d]', '', text)
    # Strip "remote" prefix
    text = re.sub(r'\bremote\b[,\s\-]*', '', text, flags=re.IGNORECASE).strip()
    # Strip trailing country noise
    for suffix in [', planet earth', ', earth', ', usa', ', us', ', u.s.a.', ', u.s.',
                   ', united states of america', ', united states']:
        if text.endswith(suffix):
            text = text[:len(text) - len(suffix)].strip().rstrip(',')
    return text.strip()


def _extract_city_tokens(location: str) -> List[str]:
    """Extract potential city/region tokens from a location string.

    Returns a list of normalized tokens (individual city names, aliases resolved).
    e.g. "SF Bay Area, CA" -> ["san francisco", "california"]
    e.g. "Belgrade, Serbia" -> ["belgrade", "serbia"]
    """
    if not location:
        return []

    text = _normalize_for_matching(location)
    if not text:
        return []

    tokens = []
    # Split by common separators
    parts = re.split(r'[,/|&+]', text)

    for part in parts:
        part = part.strip().rstrip('.')
        if not part:
            continue

        # Remove parenthetical content
        part = re.sub(r'\([^)]*\)', '', part).strip()
        # Remove noise words
        part = re.sub(r'\b(greater|sometimes|area|region|metro|metropolitan)\b', '', part, flags=re.IGNORECASE).strip()

        if not part:
            continue

        # Check if it's a state abbreviation (2 letters)
        if len(part) == 2 and part in _STATE_ABBR:
            tokens.append(_STATE_ABBR[part])
            continue

        # Resolve aliases
        if part in _CITY_ALIASES:
            tokens.append(_CITY_ALIASES[part])
        else:
            tokens.append(part)

        # Also resolve country aliases
        if part in _COUNTRY_ALIASES:
            tokens.append(_COUNTRY_ALIASES[part])

    return tokens


def check_city_match(candidate_location: Optional[str], role_cities: Optional[List[str]]) -> bool:
    """Check if a candidate's location matches any of the role's required cities.

    Uses fuzzy matching:
    - Direct city name match (e.g. "San Francisco" matches "San Francisco, CA")
    - Alias resolution (e.g. "SF" matches "San Francisco")
    - Same-metro matching (e.g. "Oakland" matches "San Francisco")
    - State/country matching (e.g. candidate in "Austin, TX" state=Texas, role city "Dallas, TX" state=Texas -> same state)
    """
    if not candidate_location or not role_cities:
        return False

    candidate_tokens = _extract_city_tokens(candidate_location)
    if not candidate_tokens:
        return False

    for role_city in role_cities:
        role_tokens = _extract_city_tokens(role_city)
        if not role_tokens:
            continue

        # Direct token overlap
        if set(candidate_tokens) & set(role_tokens):
            return True

        # Check if any candidate city and role city map to the same canonical city via aliases
        candidate_canonical = set()
        for t in candidate_tokens:
            candidate_canonical.add(_CITY_ALIASES.get(t, t))
        role_canonical = set()
        for t in role_tokens:
            role_canonical.add(_CITY_ALIASES.get(t, t))

        if candidate_canonical & role_canonical:
            return True

        # Check substring match (e.g. "san francisco" in "san francisco bay area")
        candidate_joined = ' '.join(candidate_tokens)
        for rt in role_canonical:
            if rt in candidate_joined or candidate_joined in rt:
                return True
        role_joined = ' '.join(role_tokens)
        for ct in candidate_canonical:
            if ct in role_joined or role_joined in ct:
                return True

    return False


def check_country_match(candidate_location: Optional[str], role_cities: Optional[List[str]]) -> bool:
    """Check if a candidate is at least in the same country as one of the role cities."""
    if not candidate_location or not role_cities:
        return False

    candidate_tokens = _extract_city_tokens(candidate_location)

    # Determine candidate's country/state
    candidate_regions = set()
    for t in candidate_tokens:
        canonical = _CITY_ALIASES.get(t, t)
        if canonical in _CITY_TO_STATE:
            candidate_regions.add(_CITY_TO_STATE[canonical])
        candidate_regions.add(canonical)
        if canonical in _COUNTRY_ALIASES:
            candidate_regions.add(_COUNTRY_ALIASES[canonical])

    for role_city in role_cities:
        role_tokens = _extract_city_tokens(role_city)
        role_regions = set()
        for t in role_tokens:
            canonical = _CITY_ALIASES.get(t, t)
            if canonical in _CITY_TO_STATE:
                role_regions.add(_CITY_TO_STATE[canonical])
            role_regions.add(canonical)
            if canonical in _COUNTRY_ALIASES:
                role_regions.add(_COUNTRY_ALIASES[canonical])

        if candidate_regions & role_regions:
            return True

    return False


def calculate_fit_score(candidate_data: Dict) -> Tuple[int, Dict]:
    """
    Calculate overall candidate fit score (0-100) before matching to specific roles.

    This score determines candidate quality based on:
    - Hireable flag (+20)
    - Public email (+15)
    - Recent activity (+15)
    - Original repos (+15)
    - Full-stack language mix (+15)
    - Profile README (+5)
    - Bio signals (+10)
    - Location fit (+5)

    Returns: (score, breakdown)
    """
    score = 0
    breakdown = {}

    # Hireable flag (+20)
    if candidate_data.get('github_hireable'):
        breakdown['hireable'] = 20
        score += 20
    else:
        breakdown['hireable'] = 0

    # Public email (+15)
    if candidate_data.get('email'):
        breakdown['email'] = 15
        score += 15
    else:
        breakdown['email'] = 0

    # Recent activity - commits in 30 days (+15)
    commits_30d = candidate_data.get('github_commits_30d', 0)
    if commits_30d and commits_30d > 10:
        breakdown['recent_commits'] = 15
        score += 15
    elif commits_30d and commits_30d > 0:
        breakdown['recent_commits'] = 8
        score += 8
    else:
        breakdown['recent_commits'] = 0

    # Original repos (+15)
    original_repos = candidate_data.get('github_original_repos', 0)
    if original_repos and original_repos >= 5:
        breakdown['original_repos'] = 15
        score += 15
    elif original_repos and original_repos >= 3:
        breakdown['original_repos'] = 8
        score += 8
    else:
        breakdown['original_repos'] = 0

    # Full-stack language mix (+15)
    frontend = {'javascript', 'typescript', 'react', 'vue', 'html', 'css'}
    backend = {'python', 'go', 'rust', 'java', 'ruby', 'node'}

    langs = set(l.lower() for l in (candidate_data.get('github_languages') or []))
    has_frontend = bool(langs & frontend)
    has_backend = bool(langs & backend)

    if has_frontend and has_backend:
        breakdown['fullstack'] = 15
        score += 15
    elif has_frontend or has_backend:
        breakdown['fullstack'] = 8
        score += 8
    else:
        breakdown['fullstack'] = 0

    # Profile README (+5)
    if candidate_data.get('github_has_readme'):
        breakdown['readme'] = 5
        score += 5
    else:
        breakdown['readme'] = 0

    # Bio signals (+10)
    bio_lower = (candidate_data.get('github_bio') or '').lower()
    if any(term in bio_lower for term in ['open to', 'exploring', 'available', 'looking for']):
        breakdown['bio_signals'] = 10
        score += 10
    else:
        breakdown['bio_signals'] = 0

    # Location fit (+5)
    if candidate_data.get('location_fit') == 'strong':
        breakdown['location'] = 5
        score += 5
    else:
        breakdown['location'] = 0

    return score, breakdown


def calculate_match_score(candidate: Candidate, role: Role) -> Tuple[int, Dict]:
    """
    Calculate match score (0-100) between a candidate and a role.

    Scoring breakdown (v3 — tier-aware):
    - Tech Stack / Skill Cluster Overlap (0-40 points)  — semantic matching
    - Candidate Signal Strength (0-25 points) — tier from VibeChekk
    - YOE Fit (0-15 points)
    - Location Fit (0-10 points)
    - Tier-Tech Bonus (0-10 points) — high-tier candidates get credit
      for partial tech overlap (they can learn the rest)

    Comp and Timeline are scored at 0 because the data is typically
    unavailable until screening (later in the pipeline).

    Returns: (score, breakdown)
    """
    from app.services.skill_clusters import (
        get_candidate_clusters, get_role_clusters, compute_cluster_overlap,
    )

    score = 0
    breakdown = {}

    # --- Tech Stack / Skill Cluster Overlap (0-40 points) ---
    # Semantic matching via skill clusters instead of exact string comparison
    candidate_clusters = get_candidate_clusters(
        tech_stack=candidate.tech_stack,
        vibe_report=candidate.vibe_report,
        github_languages=candidate.github_languages,
    )
    role_clusters = get_role_clusters(
        tech_stack=role.tech_stack,
        required_skills=role.required_skills,
        jd_text=role.jd_text,
    )

    if role_clusters:
        matched, missing, extra = compute_cluster_overlap(candidate_clusters, role_clusters)
        overlap_ratio = len(matched) / len(role_clusters)

        # Must-have bonus: if role has required_skills_priority, weight must-haves more
        must_have_bonus = 0
        priority = role.required_skills_priority or {}
        if priority:
            from app.services.skill_clusters import get_clusters_for_skill
            must_have_clusters = set()
            for skill, prio in priority.items():
                if prio == 'must_have':
                    must_have_clusters.update(get_clusters_for_skill(skill))
            if must_have_clusters:
                mh_matched = candidate_clusters & must_have_clusters
                mh_ratio = len(mh_matched) / len(must_have_clusters)
                # Up to 8 bonus points for covering must-haves
                must_have_bonus = int(mh_ratio * 8)

        tech_score = min(40, int(overlap_ratio * 32) + must_have_bonus)
    else:
        tech_score = 20  # Neutral if role has no specified stack

    breakdown['tech_stack'] = tech_score
    breakdown['tech_clusters_matched'] = list(matched) if role_clusters else []
    breakdown['tech_clusters_missing'] = list(missing) if role_clusters else []
    score += tech_score

    # --- Candidate Signal Strength (0-25 points) ---
    tier_scores = {
        'LEGENDARY': 25,
        'ULTRA RARE': 20,
        'RARE': 15,
        'UNCOMMON': 7,
        'COMMON': 2,
    }
    tier = (candidate.tier or '').upper()
    signal_score = tier_scores.get(tier, 0)
    breakdown['candidate_signal'] = signal_score
    score += signal_score

    # --- Tier-Tech Bonus (0-10 points) ---
    # High-tier candidates get credit for partial tech overlap because
    # exceptional engineers can learn missing frameworks quickly.
    # Only kicks in for RARE+ with at least 40% tech overlap.
    tier_tech_bonus = 0
    if role_clusters:
        if tier in ('LEGENDARY', 'ULTRA RARE', 'RARE') and overlap_ratio >= 0.4:
            tier_multipliers = {'LEGENDARY': 1.0, 'ULTRA RARE': 0.8, 'RARE': 0.5}
            tier_tech_bonus = int(10 * tier_multipliers.get(tier, 0) * overlap_ratio)
    breakdown['tier_tech_bonus'] = tier_tech_bonus
    score += tier_tech_bonus

    # --- YOE Fit (0-15 points) ---
    if candidate.yoe is not None and role.yoe_min is not None and role.yoe_max is not None:
        if role.yoe_min <= candidate.yoe <= role.yoe_max:
            yoe_score = 15
        elif candidate.yoe < role.yoe_min:
            yoe_score = max(0, 15 - (role.yoe_min - candidate.yoe) * 4)
        else:
            yoe_score = max(0, 15 - (candidate.yoe - role.yoe_max) * 2)
    else:
        yoe_score = 8  # Neutral if unknown

    breakdown['yoe'] = yoe_score
    score += yoe_score

    # --- Location Fit (0-10 points) ---
    if role.location_cities and len(role.location_cities) > 0:
        if check_city_match(candidate.location_raw, role.location_cities):
            loc_score = 10
        elif check_country_match(candidate.location_raw, role.location_cities):
            loc_score = 6
        elif role.location_requirement and role.location_requirement.value == 'remote':
            loc_score = 8
        else:
            location_scores = {'strong': 4, 'medium': 2, 'weak': 0}
            loc_score = location_scores.get(candidate.location_fit, 2) if candidate.location_fit else 2
    else:
        location_scores = {'strong': 10, 'medium': 5, 'weak': 0}
        loc_score = location_scores.get(candidate.location_fit, 5) if candidate.location_fit else 5

    breakdown['location'] = loc_score
    score += loc_score

    # --- Comp (0 points — not available until screening) ---
    breakdown['comp'] = 0

    # --- Timeline (0 points — not available until screening) ---
    breakdown['timeline'] = 0

    return score, breakdown


def get_timeline_matches(urgency: str) -> list:
    """
    Get candidate timeline values that match a role's urgency.
    """
    timeline_mapping = {
        'asap': ['now', '1_month'],
        '1_month': ['now', '1_month'],
        '3_months': ['now', '1_month', '3_months'],
        'flexible': ['now', '1_month', '3_months', 'passive'],
    }
    return timeline_mapping.get(urgency, ['now', '1_month', '3_months'])
