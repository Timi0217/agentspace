"""
Diaspora Name-Based Sourcing (Nigerian Tech Community)

Separate sourcing module for targeting Nigerian diaspora engineers via name prefixes.
Run this as a standalone job to supplement standard location-based sourcing.

Strategy:
- Search for common Nigerian name prefixes (olu, ola, ade)
- Cover US, Canada + top 10 tech hubs for better coverage
- Apply same filters and scoring as standard sourcing
- Additive strategy (no preferential treatment)

Usage:
    Can be run as a separate ingestion job or added to main search flow.
"""

from typing import Set
from sqlalchemy.orm import Session
from app.models.ingestion_job import IngestionJob
from app.services.github_ingestion import search_github_users
from app.core.logging import get_logger

logger = get_logger(__name__)


# Nigerian diaspora name patterns
DIASPORA_PREFIXES = ['olu', 'ola', 'ade']

# Search locations: US, Canada + top tech hubs
DIASPORA_LOCATIONS = [
    'United States OR USA OR US',
    'Canada',
    '"San Francisco" OR SF',
    '"New York" OR NYC',
    'Seattle',
    'Austin',
    'Boston',
    '"Bay Area"',
    'Chicago',
    'Toronto',
    'Vancouver',
    'Waterloo'
]

# Languages to search
LANGUAGES = [
    'typescript', 'python', 'go', 'rust', 'javascript',
    'cpp', 'swift', 'kotlin', 'java', 'ruby'
]


def run_diaspora_search(db: Session, job: IngestionJob = None) -> Set[str]:
    """
    Run GitHub search with Nigerian diaspora name prefixes.

    This generates 360 searches:
    - 3 prefixes × 10 languages × 12 locations = 360 searches
    - Runtime: ~6 minutes (at 1 req/sec with GitHub rate limit)

    Args:
        db: Database session
        job: Optional IngestionJob for logging

    Returns:
        Set of unique GitHub usernames found
    """
    # Build search queries
    searches = [
        {'languages': [lang], 'location': location, 'min_repos': 5, 'fullname_prefix': prefix}
        for lang in LANGUAGES
        for prefix in DIASPORA_PREFIXES
        for location in DIASPORA_LOCATIONS
    ]

    all_usernames = set()

    logger.info("Running %d searches (3 prefixes × 10 languages × 12 locations)...", len(searches))

    for i, search in enumerate(searches, 1):
        lang = search['languages'][0]
        location = search['location']
        prefix = search['fullname_prefix']

        logger.info("[%d/%d] Searching %s + name:%s in %s...", i, len(searches), lang, prefix, location.split(' OR ')[0])

        usernames = search_github_users(**search)
        all_usernames.update(usernames)

        logger.info("Found %d candidates (%d total unique)", len(usernames), len(all_usernames))

    logger.info("Complete: %d unique candidates found", len(all_usernames))

    return all_usernames


def get_diaspora_search_config() -> dict:
    """
    Get configuration for diaspora name-based search.

    Returns:
        Dict with search configuration details
    """
    return {
        "prefixes": DIASPORA_PREFIXES,
        "locations": DIASPORA_LOCATIONS,
        "languages": LANGUAGES,
        "total_searches": len(DIASPORA_PREFIXES) * len(LANGUAGES) * len(DIASPORA_LOCATIONS),
        "estimated_runtime_minutes": 6,
        "description": "Nigerian diaspora name-based sourcing (olu, ola, ade prefixes)"
    }
