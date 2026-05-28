"""
Candidate Analysis Service

Runs VibeChekk analysis on a candidate: fetches GitHub data, calculates
tier/classification, and generates archetype via DeepSeek.
"""

import re
import time
import requests
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api import crud
from app.core.config import settings
from app.core.logging import get_logger
from app.services.github_ingestion import token_rotator

logger = get_logger(__name__)


def run_candidate_analysis(candidate_id: UUID, db: Session):
    """
    Run VibeChekk analysis on a candidate.

    Fetches GitHub data (user info + repos), calculates composite score and tier,
    then calls DeepSeek for archetype classification and narrative generation.

    Returns dict with analysis results.
    """
    from app.services.deepseek_full_prompt import calculate_classification, analyze_with_full_vibechekk_prompt

    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="DeepSeek API key not configured")

    github_data = {
        'github_username': candidate.github_username,
        'github_commits_90d': candidate.github_commits_90d or 0,
        'github_commits_30d': candidate.github_commits_30d or 0,
        'github_followers': candidate.github_followers or 0,
        'github_public_repos': candidate.github_public_repos or 0,
        'github_languages': candidate.github_languages or [],
        'created_at': None
    }

    top_repos = []
    is_reclassification = candidate.archetype is not None

    # --- Fetch user info ---
    top_repos = _fetch_github_data(candidate, github_data, is_reclassification, db)

    # --- Build quality signals and code samples ---
    if not top_repos:
        top_repos = _build_fallback_repos(candidate)
        quality_signals = [{
            'hasTests': False,
            'hasCI': False,
            'hasTypeScript': 'TypeScript' in (candidate.github_languages or []),
            'hasLinting': False,
            'hasDocs': candidate.github_has_readme or False,
            'fileCount': max((candidate.github_public_repos or 1) * 50, 10)
        }]
        code_samples = (
            f'Code samples unavailable due to API rate limits. Analysis based on profile metadata: '
            f'{candidate.github_public_repos} repositories, {candidate.github_total_stars} total stars, '
            f'{len(candidate.github_languages or [])} languages.'
        )
    else:
        quality_signals, code_samples = _fetch_quality_signals(candidate, top_repos)

    logger.info("Fetched %d quality signals and %d chars of code", len(quality_signals), len(code_samples))

    # --- Classification and archetype ---
    classification_token = token_rotator.get_token()
    classification = calculate_classification(
        username=candidate.github_username,
        github_token=classification_token,
        top_repos=top_repos,
        quality_signals=quality_signals,
        github_data=github_data
    )

    logger.info("%s -> %s tier | Score: %d/100", candidate.github_username, classification['tier'], classification['composite_score'])

    vibe_report = analyze_with_full_vibechekk_prompt(
        api_key=settings.DEEPSEEK_API_KEY,
        username=candidate.github_username,
        classification=classification,
        top_repos=top_repos,
        quality_signals=quality_signals,
        code_samples=code_samples,
        resume_text=candidate.resume_text
    )

    logger.info("%s -> %s archetype (%s tier)", candidate.github_username, vibe_report.get('label'), vibe_report.get('rarity'))

    # Persist top repos in vibe_report so they're available in API responses
    vibe_report['top_repos'] = [
        {
            'name': r.get('name'),
            'language': r.get('language'),
            'stars': r.get('stars', 0),
            'forks': r.get('forks', 0),
            'description': r.get('description', ''),
            'is_fork': r.get('is_fork', False),
        }
        for r in top_repos[:5]
    ]

    # Update candidate
    from app.schemas.candidate import CandidateUpdate
    update_data = CandidateUpdate(
        archetype=vibe_report.get('label'),
        tier=vibe_report.get('rarity'),
        tier_badge=vibe_report.get('rarity_badge'),
        tier_percentile=vibe_report.get('rarity_percentile'),
        vibe_report=vibe_report
    )

    crud.update_candidate(db, candidate_id, update_data)

    return {
        "message": "Analysis complete",
        "candidate_id": candidate_id,
        "archetype": vibe_report.get('label'),
        "tier": vibe_report.get('rarity'),
        "composite_score": vibe_report.get('composite_score'),
        "vibe_report": vibe_report
    }


def _fetch_github_data(candidate, github_data, is_reclassification, db):
    """Fetch user info and repos from GitHub API with ETag optimization and rate limit retry."""
    top_repos = []

    try:
        # Fetch user info
        user_token = token_rotator.get_token()
        user_headers = {'Authorization': f'token {user_token}'} if user_token else {}

        if candidate.user_etag and not is_reclassification:
            user_headers['If-None-Match'] = candidate.user_etag

        user_url = f"https://api.github.com/users/{candidate.github_username}"
        user_response = requests.get(user_url, headers=user_headers, timeout=10)

        if user_response.status_code == 304:
            pass  # Data unchanged
        elif user_response.ok:
            user_data = user_response.json()
            github_data['created_at'] = user_data.get('created_at')
            new_etag = user_response.headers.get('ETag')
            if new_etag:
                candidate.user_etag = new_etag
                db.flush()
        elif user_response.status_code == 403:
            user_response = _retry_rate_limit(user_url, user_response)
            if user_response.ok:
                user_data = user_response.json()
                github_data['created_at'] = user_data.get('created_at')
                new_etag = user_response.headers.get('ETag')
                if new_etag:
                    candidate.user_etag = new_etag
                    db.flush()

        # Fetch repos
        repos_token = token_rotator.get_token()
        repos_headers = {'Authorization': f'token {repos_token}'} if repos_token else {}

        if candidate.repos_etag and not is_reclassification:
            repos_headers['If-None-Match'] = candidate.repos_etag

        repos_url = f"https://api.github.com/users/{candidate.github_username}/repos?sort=updated&per_page=100"
        repos_response = requests.get(repos_url, headers=repos_headers, timeout=10)

        if repos_response.status_code == 304:
            top_repos = _extract_repos_from_vibe_report(candidate)
        elif repos_response.ok:
            top_repos = _parse_repos(repos_response.json(), candidate.github_username)
            new_etag = repos_response.headers.get('ETag')
            if new_etag:
                candidate.repos_etag = new_etag
                db.flush()
        elif repos_response.status_code == 403:
            repos_response = _retry_rate_limit(repos_url, repos_response)
            if repos_response.status_code == 304:
                top_repos = _extract_repos_from_vibe_report(candidate)
            elif repos_response.ok:
                top_repos = _parse_repos(repos_response.json(), candidate.github_username)
                new_etag = repos_response.headers.get('ETag')
                if new_etag:
                    candidate.repos_etag = new_etag
                    db.flush()
        else:
            logger.error("Failed to fetch repos for %s: %d", candidate.github_username, repos_response.status_code)

    except Exception as e:
        logger.error("Could not fetch repos: %s", e)

    return top_repos


def _retry_rate_limit(url, response, max_attempts=1000):
    """Retry a GitHub API request on 403 rate limit with token rotation."""
    attempt = 0
    while attempt < max_attempts and response.status_code == 403:
        attempt += 1
        if attempt % 50 == 1:
            logger.warning("Rate limit retry attempt %d/%d...", attempt, max_attempts)
        time.sleep(5)
        retry_token = token_rotator.get_token()
        retry_headers = {'Authorization': f'token {retry_token}'} if retry_token else {}
        response = requests.get(url, headers=retry_headers, timeout=10)
    return response


def _parse_repos(repos_data, github_username):
    """Parse GitHub API repos response into our format."""
    repos = []
    for repo in repos_data[:5]:
        repos.append({
            'name': repo.get('name'),
            'language': repo.get('language'),
            'stars': repo.get('stargazers_count', 0),
            'is_maintainer': repo.get('owner', {}).get('login') == github_username,
            'is_fork': repo.get('fork', False),
            'forks': repo.get('forks_count', 0),
            'description': repo.get('description', ''),
            'updated_at': repo.get('updated_at', '')
        })
    return repos


def _extract_repos_from_vibe_report(candidate):
    """Extract repo data from a previous vibe_report when GitHub returns 304."""
    repos = []
    if candidate.vibe_report and isinstance(candidate.vibe_report, dict):
        report_text = str(candidate.vibe_report)
        repo_pattern = r'• ([^\(]+) \((?:Original|Fork)\) \(([^,]+), (\d+)\u2b50\)'
        matches = re.findall(repo_pattern, report_text)
        for name, lang, stars in matches[:10]:
            repos.append({
                'name': name.strip(),
                'language': lang.strip(),
                'stars': int(stars),
                'is_maintainer': True,
                'is_fork': False,
                'forks': 0,
                'description': '',
                'updated_at': ''
            })
        if repos:
            logger.info("Restored %d repos from previous analysis", len(repos))
    return repos


def _build_fallback_repos(candidate):
    """Build synthetic repos from DB metadata when GitHub API is unavailable."""
    repos = []
    db_original_repos = candidate.github_original_repos or (candidate.github_public_repos or 1)
    db_stars_total = candidate.github_total_stars or 0
    languages = candidate.github_languages or ['Python']

    highest_stars = int(db_stars_total * 0.5) if db_stars_total > 0 else 0
    remaining_stars = db_stars_total - highest_stars

    repo_name_templates = {
        'Python': ['data-pipeline', 'ml-toolkit', 'api-service', 'automation-scripts', 'web-scraper'],
        'JavaScript': ['react-app', 'node-server', 'web-dashboard', 'frontend-toolkit', 'js-utils'],
        'TypeScript': ['ts-monorepo', 'backend-api', 'fullstack-app', 'ui-components', 'type-utils'],
        'Go': ['microservice', 'api-gateway', 'cli-tool', 'backend-service', 'go-utils'],
        'Rust': ['systems-tool', 'perf-optimizer', 'rust-lib', 'cli-utility', 'safe-wrapper'],
        'Java': ['spring-service', 'enterprise-app', 'java-lib', 'backend-server', 'maven-project'],
        'C++': ['cpp-lib', 'performance-tool', 'systems-app', 'algorithm-impl', 'native-module'],
        'default': ['project', 'library', 'tool', 'service', 'application']
    }

    for i in range(min(db_original_repos, 10)):
        lang = languages[i % len(languages)]
        templates = repo_name_templates.get(lang, repo_name_templates['default'])
        repo_name = f"{templates[i % len(templates)]}-{i+1}" if i > 0 else templates[0]
        is_original = i < db_original_repos
        stars = highest_stars if i == 0 else (remaining_stars // max(db_original_repos - 1, 1))

        repos.append({
            'name': repo_name,
            'language': lang,
            'stars': stars,
            'is_maintainer': is_original,
            'is_fork': not is_original,
            'description': f'Original {lang} project' if is_original else f'Forked {lang} repository'
        })

    return repos


def _fetch_quality_signals(candidate, top_repos):
    """Fetch code quality signals and code samples for real repos."""
    from app.services.github_analysis import fetch_code_quality_signals, fetch_smart_diffs

    quality_signals = []
    for repo in top_repos[:5]:
        quality_token = token_rotator.get_token()
        qual = fetch_code_quality_signals(quality_token, candidate.github_username, repo.get('name'))
        if qual:
            quality_signals.append(qual)
        else:
            quality_signals.append({
                'hasTests': False,
                'hasCI': False,
                'hasTypeScript': 'TypeScript' in (candidate.github_languages or []),
                'hasLinting': False,
                'hasDocs': False,
                'fileCount': 0
            })

    code_samples_token = token_rotator.get_token()
    code_samples = fetch_smart_diffs(code_samples_token, candidate.github_username, top_repos)

    return quality_signals, code_samples
