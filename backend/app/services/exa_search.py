"""
Exa AI Integration

Semantic search for LinkedIn profiles when PDL fails.

Uses Exa's AI-powered search to find LinkedIn profiles based on name + context.
"""

import requests
from typing import Optional, Dict, List
from app.core.logging import get_logger

logger = get_logger(__name__)


def find_linkedin_profile(
    api_key: str,
    name: str,
    company: Optional[str] = None,
    title: Optional[str] = None,
    location: Optional[str] = None
) -> Optional[str]:
    """
    Find LinkedIn profile URL using Exa AI semantic search.

    Args:
        api_key: Exa API key
        name: Person's full name
        company: Current company (optional)
        title: Job title (optional)
        location: Location (optional)

    Returns:
        LinkedIn URL if found, None otherwise
    """

    if not name or len(name.strip()) < 2:
        logger.warning("Name too short for search")
        return None

    try:
        # Build search query with context (simple space-separated format like vibechekk)
        context_parts = []

        if location:
            context_parts.append(location)
        if company:
            context_parts.append(company)

        # Simple format: "Name Location Company" (no "at", "in", etc.)
        context = " ".join(context_parts)
        query = f"{name} {context}".strip() if context else name

        logger.info("Searching for LinkedIn profile: %s", query)

        # Exa API endpoint
        url = "https://api.exa.ai/search"

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key
        }

        # Minimal payload like vibechekk (no type, no useAutoprompt)
        payload = {
            "query": query,
            "numResults": 5,
            "includeDomains": ["linkedin.com"]
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if not response.ok:
            logger.error("API error: %d", response.status_code)
            return None

        data = response.json()
        results = data.get('results', [])

        if not results:
            logger.info("No results found for %s", name)
            return None

        # Filter and rank results
        valid_linkedin_urls = []

        for result in results:
            url = result.get('url', '')

            # Validate LinkedIn profile URL (more permissive like vibechekk)
            # Accept URLs with query params, but exclude directories/posts
            url_lower = url.lower()
            if (url and
                'linkedin.com' in url_lower and
                '/in/' in url_lower and
                '/pub/dir/' not in url_lower and
                '/directory/' not in url_lower and
                '/posts/' not in url_lower and
                '/pulse/' not in url_lower):
                score = result.get('score', 0)
                valid_linkedin_urls.append({
                    'url': url,
                    'score': score,
                    'title': result.get('title', '')
                })

        if not valid_linkedin_urls:
            logger.info("No valid LinkedIn /in/ URLs found for %s", name)
            return None

        # Sort by score (highest first)
        valid_linkedin_urls.sort(key=lambda x: x['score'], reverse=True)

        best_match = valid_linkedin_urls[0]
        linkedin_url = best_match['url']

        logger.info("Found LinkedIn profile: %s", linkedin_url)
        logger.debug("Match score: %s", best_match['score'])

        return linkedin_url

    except requests.exceptions.Timeout:
        logger.warning("Timeout searching for %s", name)
        return None

    except Exception as e:
        logger.error("Error searching for %s: %s", name, e)
        return None


def enrich_with_linkedin_fallback(
    exa_api_key: str,
    name: str,
    email: str,
    company: Optional[str] = None,
    title: Optional[str] = None,
    location: Optional[str] = None
) -> Dict:
    """
    Fallback enrichment using Exa AI when PDL fails.

    Returns basic enrichment with LinkedIn URL found via semantic search.
    """

    linkedin_url = find_linkedin_profile(
        exa_api_key,
        name,
        company,
        title,
        location
    )

    if linkedin_url:
        return {
            'success': True,
            'linkedin_url': linkedin_url,
            'name': name,
            'method': 'exa_search'
        }
    else:
        return {
            'success': False,
            'error': 'No LinkedIn profile found via Exa search'
        }
