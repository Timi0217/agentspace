"""
DeepSeek Analysis Module

Purpose: Classify developers into 15 archetypes and generate recruiter-ready assessments.

The 15 Archetypes (by market rarity):

🌟🌟🌟 LEGENDARY (Top 1%) - Industry-defining talent
  - THE 10X ENGINEER: Builds tools/frameworks used by thousands

🌟🌟 ULTRA RARE (Top 5%) - Senior+ leadership material
  - THE ARCHITECT: Designs systems at scale
  - THE PROFESSOR: Exceptional at teaching

⭐ RARE (Top 15%) - Strong senior engineers
  - THE SPECIALIST: Deep expertise in a niche
  - THE SYSTEMS THINKER: Distributed systems, infrastructure

◆ UNCOMMON (Top 30%) - Solid mid-senior engineers
  - THE MAINTAINER: Keeps OSS projects alive
  - THE BUILDER: Ships products
  - THE CONTRIBUTOR: Active in OSS
  - THE CRAFTSPERSON: High code quality focus
  - THE HIDDEN GEM: Skilled but low visibility

● COMMON (Top 50%) - Early-mid career
  - THE TINKERER: Practical problem solver
  - THE GRINDER: High activity
  - THE HOBBYIST: Codes for passion
  - THE EXPLORER: Trying many languages
  - THE APPRENTICE: Early career
"""

import requests
import json
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from app.core.logging import get_logger

logger = get_logger(__name__)


def call_deepseek(prompt: str, temperature: float = 0.3) -> str:
    """
    Generic DeepSeek API call — sends a prompt and returns the raw text response.

    Used by screening/reference analysis to extract structured data from transcripts.

    Args:
        prompt: The prompt to send
        temperature: Sampling temperature (0.0 for deterministic)

    Returns:
        Raw text response from DeepSeek
    """
    from app.core.config import settings

    api_key = settings.DEEPSEEK_API_KEY
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY not configured")

    response = requests.post(
        'https://api.deepseek.com/v1/chat/completions',
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        },
        json={
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'system', 'content': 'You are an expert recruiter assistant. Return ONLY valid JSON when asked for JSON.'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': temperature
        },
        timeout=60
    )
    response.raise_for_status()
    data = response.json()
    return data['choices'][0]['message']['content']


def calculate_composite_score(
    github_data: Dict,
    top_repos: List[Dict],
    quality_signals: List[Dict]
) -> Tuple[int, Dict]:
    """
    Calculate composite score (0-100) based on:
    - Visibility (0-25): Stars and reach
    - Quality (0-30): Code craftsmanship
    - Activity (0-25): Engagement and consistency
    - Expertise (0-20): Tenure and depth
    """

    highest_stars = max([r.get('stars', 0) for r in top_repos], default=0)
    total_stars = sum([r.get('stars', 0) for r in top_repos]) if top_repos else 0
    total_commits = github_data.get('github_commits_90d', 0)
    total_repos = len(top_repos)

    # Account age calculation
    created_at = github_data.get('created_at')
    if created_at:
        account_age_years = (datetime.utcnow() - datetime.fromisoformat(created_at.replace('Z', ''))).days / 365.25
    else:
        account_age_years = 1

    # 1. VISIBILITY SCORE (0-25 points)
    visibility_points = 0
    if highest_stars >= 100000:
        visibility_points = 25
    elif highest_stars >= 50000:
        visibility_points = 23
    elif highest_stars >= 10000:
        visibility_points = 20
    elif highest_stars >= 5000:
        visibility_points = 18
    elif highest_stars >= 1000:
        visibility_points = 15
    elif highest_stars >= 500:
        visibility_points = 12
    elif highest_stars >= 100:
        visibility_points = 8
    elif highest_stars >= 10:
        visibility_points = 4

    # 2. QUALITY SCORE (0-30 points)
    quality_points = 0
    has_tests = any(q.get('hasTests') for q in quality_signals if q)
    has_ci = any(q.get('hasCI') for q in quality_signals if q)
    has_typescript = any(q.get('hasTypeScript') for q in quality_signals if q)
    has_linting = any(q.get('hasLinting') for q in quality_signals if q)
    has_docs = any(q.get('hasDocs') for q in quality_signals if q)

    if has_tests:
        quality_points += 8
    if has_ci:
        quality_points += 8
    if has_typescript:
        quality_points += 4
    if has_linting:
        quality_points += 3
    if has_docs:
        quality_points += 3

    avg_file_count = sum([q.get('fileCount', 0) for q in quality_signals if q]) / max(len(quality_signals), 1)
    if avg_file_count > 100:
        quality_points += 4
    elif avg_file_count > 30:
        quality_points += 2

    # 3. ACTIVITY SCORE (0-25 points)
    activity_points = 0
    commits_90d = github_data.get('github_commits_90d', 0)

    if commits_90d >= 100:
        activity_points += 10
    elif commits_90d >= 50:
        activity_points += 8
    elif commits_90d >= 20:
        activity_points += 5
    elif commits_90d >= 5:
        activity_points += 2

    if total_commits >= 1000:
        activity_points += 8
    elif total_commits >= 500:
        activity_points += 6
    elif total_commits >= 100:
        activity_points += 3

    external_contribs = github_data.get('external_contributions', 0)
    if external_contribs >= 50:
        activity_points += 7
    elif external_contribs >= 20:
        activity_points += 4
    elif external_contribs >= 5:
        activity_points += 2

    # 4. EXPERTISE SCORE (0-20 points)
    expertise_points = 0

    if account_age_years >= 10:
        expertise_points += 6
    elif account_age_years >= 7:
        expertise_points += 5
    elif account_age_years >= 5:
        expertise_points += 4
    elif account_age_years >= 3:
        expertise_points += 2

    # Language diversity
    languages = github_data.get('github_languages', [])
    if isinstance(languages, list):
        lang_count = len(languages)
        if lang_count >= 10:
            expertise_points += 8
        elif lang_count >= 7:
            expertise_points += 5
        elif lang_count >= 5:
            expertise_points += 3
        elif lang_count >= 3:
            expertise_points += 2

    composite_score = visibility_points + quality_points + activity_points + expertise_points

    breakdown = {
        'visibility': visibility_points,
        'quality': quality_points,
        'activity': activity_points,
        'expertise': expertise_points,
        'total': composite_score
    }

    return composite_score, breakdown


def determine_archetype_and_tier(composite_score: int, github_data: Dict, top_repos: List[Dict]) -> Dict:
    """
    Determine archetype and tier based on composite score and signals.
    """

    total_repos = len(top_repos)
    commits_90d = github_data.get('github_commits_90d', 0)
    external_contribs = github_data.get('external_contributions', 0)

    # Check for maintainer status
    is_maintainer = any(r.get('is_maintainer') and r.get('stars', 0) >= 100 for r in top_repos)

    # Classify based on composite score
    if composite_score >= 90:
        tier = 'LEGENDARY'
        tier_badge = '🌟🌟🌟'
        percentile = 'Top 1%'
        archetype = 'THE 10X ENGINEER'
        reason = 'Exceptional across visibility, quality, and depth'

    elif composite_score >= 70:
        tier = 'ULTRA RARE'
        tier_badge = '🌟🌟'
        percentile = 'Top 5%'
        archetype = 'THE ARCHITECT'
        reason = 'Strong on multiple dimensions of engineering excellence'

    elif composite_score >= 50:
        tier = 'RARE'
        tier_badge = '⭐'
        percentile = 'Top 15%'

        if is_maintainer:
            archetype = 'THE MAINTAINER'
            reason = 'Actively maintains production repositories'
        else:
            archetype = 'THE SPECIALIST'
            reason = 'Strong technical focus with proven impact'

    elif composite_score >= 30:
        tier = 'UNCOMMON'
        tier_badge = '◆'
        percentile = 'Top 30%'

        if is_maintainer:
            archetype = 'THE MAINTAINER'
            reason = 'Actively maintains open-source projects with community adoption'
        elif external_contribs >= 15:
            archetype = 'THE CONTRIBUTOR'
            reason = 'Active open-source collaborator with meaningful contributions'
        elif commits_90d >= 30 and total_repos >= 5:
            archetype = 'THE BUILDER'
            reason = 'Ships consistently with strong development momentum'
        else:
            archetype = 'THE BUILDER'
            reason = 'Solid developer with growing portfolio'

    else:
        tier = 'COMMON'
        tier_badge = '●'
        percentile = 'Top 50%'

        if commits_90d >= 20:
            archetype = 'THE GRINDER'
            reason = 'High commit activity and sustained development effort'
        elif total_repos >= 5:
            archetype = 'THE TINKERER'
            reason = 'Practical problem solver building real applications'
        else:
            archetype = 'THE APPRENTICE'
            reason = 'Building foundational skills and early-career portfolio'

    return {
        'archetype': archetype,
        'tier': tier,
        'tier_badge': tier_badge,
        'tier_percentile': percentile,
        'classification_reason': reason
    }


def analyze_with_deepseek(
    api_key: str,
    github_data: Dict,
    top_repos: List[Dict],
    quality_signals: List[Dict],
    code_samples: str
) -> Dict:
    """
    Main analysis function - calls DeepSeek API for detailed assessment.

    Args:
        api_key: DeepSeek API key
        github_data: Basic GitHub stats (commits, followers, etc.)
        top_repos: List of top repositories with metadata
        quality_signals: Code quality indicators (tests, CI, etc.)
        code_samples: Code snippets from repos

    Returns:
        Complete VibeReport with archetype, tier, and detailed analysis
    """

    # Calculate composite score
    composite_score, score_breakdown = calculate_composite_score(
        github_data, top_repos, quality_signals
    )

    # Determine archetype and tier
    classification = determine_archetype_and_tier(
        composite_score, github_data, top_repos
    )

    # Build simplified prompt (production version would use full vibechekk prompt)
    username = github_data.get('github_username', 'Unknown')
    total_repos = len(top_repos)
    total_stars = sum([r.get('stars', 0) for r in top_repos]) if top_repos else 0
    commits_90d = github_data.get('github_commits_90d', 0)
    languages = github_data.get('github_languages', [])

    # Format repo list
    repo_list = "\n".join([
        f"• {r.get('name', 'Unknown')} ({r.get('language', 'Unknown')}) - {r.get('stars', 0)}⭐"
        for r in top_repos[:10]
    ])

    prompt = f"""Analyze this GitHub developer profile and generate a recruiter-ready assessment.

DEVELOPER: @{username}
CLASSIFICATION: {classification['archetype']} ({classification['tier']} {classification['tier_badge']} - {classification['tier_percentile']})

STATS:
- Composite Score: {composite_score}/100
- Total Repos: {total_repos} | Total Stars: {total_stars}
- Recent Activity: {commits_90d} commits (last 90 days)
- Languages: {', '.join(languages[:5])}

TOP REPOSITORIES:
{repo_list}

CODE SAMPLES (showing recent work):
{code_samples[:3000]}

Generate a professional technical assessment with:
1. archetype_reason (3-4 sentences explaining classification)
2. trajectory_summary (2-3 sentences on career evolution)
3. recruiter_summary (3 paragraphs: strengths, practices, team fit)
4. highlights (2-4 positive achievements, 1-2 concerns)
5. technical_signal (1 sentence concrete example)
6. verified_skills (5-8 skills with evidence)

Return ONLY valid JSON matching this structure:
{{
  "archetype_reason": "...",
  "trajectory_summary": "...",
  "recruiter_summary": "...",
  "highlights": [
    {{"title": "...", "detail": "...", "type": "positive"}},
    {{"title": "...", "detail": "...", "type": "negative"}}
  ],
  "technical_signal": "...",
  "verified_skills": [
    {{"name": "React", "level": "Intermediate", "evidence": "..."}}
  ]
}}"""

    try:
        response = requests.post(
            'https://api.deepseek.com/v1/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            },
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You are a senior technical recruiter. Return ONLY valid JSON.'
                    },
                    {'role': 'user', 'content': prompt}
                ],
                'response_format': {'type': 'json_object'},
                'temperature': 0.3
            },
            timeout=60
        )

        response.raise_for_status()
        data = response.json()

        content = data['choices'][0]['message']['content']
        analysis = json.loads(content)

        # Merge with our classification
        analysis['label'] = classification['archetype']
        analysis['rarity'] = classification['tier']
        analysis['rarity_badge'] = classification['tier_badge']
        analysis['rarity_percentile'] = classification['tier_percentile']

        # Add composite score breakdown
        analysis['composite_score'] = composite_score
        analysis['score_breakdown_detailed'] = score_breakdown

        return analysis

    except Exception as e:
        logger.error("Analysis error: %s", e)

        # Return basic classification without AI enhancement
        return {
            'label': classification['archetype'],
            'rarity': classification['tier'],
            'rarity_badge': classification['tier_badge'],
            'rarity_percentile': classification['tier_percentile'],
            'archetype_reason': f"Classified as {classification['archetype'].replace('THE ', '')} because {classification['classification_reason'].lower()}.",
            'trajectory_summary': f"Profile shows {total_repos} repositories with {total_stars} total stars.",
            'recruiter_summary': "Analysis unavailable - DeepSeek API error.",
            'highlights': [],
            'technical_signal': f"Active developer with {commits_90d} commits in last 90 days.",
            'verified_skills': [],
            'composite_score': composite_score,
            'score_breakdown_detailed': score_breakdown,
            'error': str(e)
        }
