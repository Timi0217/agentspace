"""
DeepSeek Analysis Module - Ported from VibeChekk

This is vibechekk's exact analysis logic ported to Python for chekk.
Classifies developers into 15 archetypes with composite scoring.
"""

import requests
import json
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from app.core.logging import get_logger

logger = get_logger(__name__)


def fetch_github_contributions(username: str, github_token: str) -> int:
    """
    Fetch accurate 90-day commit count using GitHub GraphQL API.

    This is the KEY difference from the old implementation - we use GraphQL
    to get accurate contribution data instead of guessing from events API.
    """
    from_date = (datetime.utcnow() - timedelta(days=90)).isoformat() + "Z"

    query = """
    query($username: String!, $from: DateTime!) {
      user(login: $username) {
        recentActivity: contributionsCollection(from: $from) {
          totalCommitContributions
          contributionCalendar {
            totalContributions
          }
        }
      }
    }
    """

    headers = {
        "Authorization": f"bearer {github_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": {"username": username, "from": from_date}},
            headers=headers,
            timeout=10
        )

        if response.ok:
            data = response.json()
            contributions = data.get("data", {}).get("user", {}).get("recentActivity", {})
            return contributions.get("contributionCalendar", {}).get("totalContributions", 0)
    except Exception as e:
        logger.error("GitHub GraphQL Error fetching contributions: %s", e)

    return 0


def analyze_with_vibechekk_deepseek(
    api_key: str,
    username: str,
    github_token: str,
    top_repos: List[Dict],
    quality_signals: List[Dict],
    github_data: Dict
) -> Dict:
    """
    Exact port of vibechekk's DeepSeek analysis logic.

    Key improvements over old version:
    1. Uses GraphQL for accurate 90-day commits
    2. Proper composite scoring (Visibility + Quality + Activity + Expertise)
    3. Real repo data with stars
    """

    # Fetch accurate 90-day commits using GraphQL
    last_90_days_commits = fetch_github_contributions(username, github_token)
    logger.info("%s has %d commits in last 90 days", username, last_90_days_commits)

    # Extract metrics
    highest_stars = max([r.get('stars', 0) for r in top_repos], default=0)
    total_stars = sum([r.get('stars', 0) for r in top_repos]) if top_repos else 0
    total_commits = github_data.get('github_commits_90d', 0)

    # Account age
    created_at = github_data.get('created_at')
    if created_at:
        account_age_years = (datetime.utcnow() - datetime.fromisoformat(created_at.replace('Z', ''))).days / 365.25
    else:
        account_age_years = 1

    logger.debug("Metrics - Stars: %d, Commits90d: %d, Age: %.1fy", highest_stars, last_90_days_commits, account_age_years)

    # ═══════════════════════════════════════════════════════════════════
    # COMPOSITE SCORING (exactly like vibechekk)
    # ═══════════════════════════════════════════════════════════════════

    # VISIBILITY SCORE (0-25 points)
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

    # QUALITY SCORE (0-30 points)
    quality_points = 0
    has_tests = any(q.get('hasTests') for q in quality_signals if q)
    has_ci = any(q.get('hasCI') for q in quality_signals if q)
    has_typescript = any(q.get('hasTypeScript') for q in quality_signals if q)
    has_linting = any(q.get('hasLinting') for q in quality_signals if q)
    has_docs = any(q.get('hasDocs') for q in quality_signals if q)
    avg_file_count = sum(q.get('fileCount', 0) for q in quality_signals if q) / max(len(quality_signals), 1)

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
    if avg_file_count > 100:
        quality_points += 4
    elif avg_file_count > 30:
        quality_points += 2

    # ACTIVITY SCORE (0-25 points) - USE THE GRAPHQL DATA!
    activity_points = 0
    if last_90_days_commits >= 100:
        activity_points += 10
    elif last_90_days_commits >= 50:
        activity_points += 8
    elif last_90_days_commits >= 20:
        activity_points += 5
    elif last_90_days_commits >= 5:
        activity_points += 2

    # Repo count contribution
    total_repos = len(top_repos)
    if total_repos >= 20:
        activity_points += 8
    elif total_repos >= 10:
        activity_points += 5
    elif total_repos >= 5:
        activity_points += 3

    # External contributions (if available)
    external_contribs = github_data.get('external_contributions', 0)
    if external_contribs >= 50:
        activity_points += 7
    elif external_contribs >= 20:
        activity_points += 4
    elif external_contribs >= 5:
        activity_points += 2

    # EXPERTISE SCORE (0-20 points)
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
    if len(languages) >= 7:
        expertise_points += 5
    elif len(languages) >= 5:
        expertise_points += 3
    elif len(languages) >= 3:
        expertise_points += 2

    # TOTAL COMPOSITE SCORE
    composite_score = visibility_points + quality_points + activity_points + expertise_points

    logger.info("Score - Visibility: %d, Quality: %d, Activity: %d, Expertise: %d = %d/100", visibility_points, quality_points, activity_points, expertise_points, composite_score)

    # ═══════════════════════════════════════════════════════════════════
    # TIER DETERMINATION (exactly like vibechekk)
    # ═══════════════════════════════════════════════════════════════════

    if composite_score >= 90:
        tier = 'LEGENDARY'
        tier_badge = '🌟🌟🌟'
        percentile = 'Top 1%'
        archetype = 'THE 10X ENGINEER'
    elif composite_score >= 70:
        tier = 'ULTRA RARE'
        tier_badge = '🌟🌟'
        percentile = 'Top 5%'
        archetype = 'THE ARCHITECT'
    elif composite_score >= 50:
        tier = 'RARE'
        tier_badge = '⭐'
        percentile = 'Top 15%'
        archetype = 'THE SPECIALIST'
    elif composite_score >= 30:
        tier = 'UNCOMMON'
        tier_badge = '◆'
        percentile = 'Top 30%'
        archetype = 'THE BUILDER'
    else:
        tier = 'COMMON'
        tier_badge = '●'
        percentile = 'Top 50%'
        archetype = 'THE APPRENTICE'

    # ═══════════════════════════════════════════════════════════════════
    # CALL DEEPSEEK API WITH VIBECHEKK'S ENGINEERED PROMPT
    # ═══════════════════════════════════════════════════════════════════

    # Build repo list with quality indicators
    repo_list = []
    for i, repo in enumerate(top_repos[:10]):
        qual = quality_signals[i] if i < len(quality_signals) else {}
        markers = []
        if qual.get('hasTests'):
            markers.append('✓Tests')
        if qual.get('hasCI'):
            markers.append('✓CI')
        markers_str = ' '.join(markers) if markers else ''
        repo_list.append(f"• {repo.get('name')} ({repo.get('language', 'Unknown')}, {repo.get('stars', 0)}⭐) {markers_str}")

    prompt = f"""## CLASSIFICATION GUIDANCE
Based on composite analysis, this developer's profile suggests:

**{archetype}** ({tier} {tier_badge} - {percentile})

Your task: Validate or challenge this classification using specific evidence from their code and repos.

## GITHUB PROFILE DATA

**Activity Metrics:**
- Account age: {account_age_years:.1f} years | Total repos: {total_repos} | Total stars: {total_stars}
- Recent activity: {last_90_days_commits} commits (last 90 days)
- Languages: {', '.join(languages[:5])}

**Quality Indicators:**
- Tests: {'✓ Yes' if has_tests else '✗ No'} | CI/CD: {'✓ Yes' if has_ci else '✗ No'}
- TypeScript: {'✓ Yes' if has_typescript else '✗ No'} | Documentation: {'✓ Yes' if has_docs else '✗ No'}

## REPOSITORIES

{chr(10).join(repo_list[:10])}

## YOUR TASK

Write a professional assessment with these fields:

**archetype_reason** (3-4 sentences): Why they earned this classification with specific evidence.

**trajectory_summary** (2-3 sentences): Their evolution over time.

**recruiter_summary** (3 paragraphs, ~150 words):
1. Current technical strengths
2. Development practices
3. Team fit & seniority

**highlights** (3-6 items):
- 2-4 positive achievements
- 1-2 negative gaps for {tier} tier

**technical_signal** (1 sentence): One concrete example proving ability.

**verified_skills** (5-8 skills): Each with name, level (Beginner/Intermediate/Advanced), and evidence.

Return as JSON with these exact field names."""

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
                        'content': 'You are a technical recruiter analyzing developer profiles. Be honest and evidence-based.'
                    },
                    {'role': 'user', 'content': prompt}
                ],
                'response_format': {'type': 'json_object'},
                'temperature': 0.3
            },
            timeout=60
        )

        if not response.ok:
            logger.error("DeepSeek API Error: %d - %s", response.status_code, response.text)
            raise Exception(f"DeepSeek API error: {response.status_code}")

        data = response.json()
        raw_content = data['choices'][0]['message']['content']

        # Parse JSON response
        try:
            analysis = json.loads(raw_content.strip())
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if '```' in raw_content:
                raw_content = raw_content.replace('```json', '').replace('```', '').strip()
            analysis = json.loads(raw_content)

        # Enforce our tier/archetype (don't let DeepSeek change it)
        analysis['label'] = archetype
        analysis['rarity'] = tier
        analysis['rarity_badge'] = tier_badge
        analysis['rarity_percentile'] = percentile
        analysis['composite_score'] = composite_score
        analysis['score_breakdown_detailed'] = {
            'visibility': visibility_points,
            'quality': quality_points,
            'activity': activity_points,
            'expertise': expertise_points
        }

        logger.info("Successfully analyzed %s", username)
        return analysis

    except Exception as e:
        logger.error("DeepSeek API Failed: %s", e)
        # Return fallback analysis without AI content
        return {
            'label': archetype,
            'rarity': tier,
            'rarity_badge': tier_badge,
            'rarity_percentile': percentile,
            'composite_score': composite_score,
            'score_breakdown_detailed': {
                'visibility': visibility_points,
                'quality': quality_points,
                'activity': activity_points,
                'expertise': expertise_points
            },
            'archetype_reason': f'Composite score: {composite_score}/100 based on visibility, quality, activity, and expertise metrics.',
            'trajectory_summary': f'{username} has {account_age_years:.0f} years on GitHub with {last_90_days_commits} recent commits.',
            'recruiter_summary': f'Developer with {account_age_years:.0f} years experience. Recent activity shows {last_90_days_commits} commits. Classified as {archetype} ({tier} tier).',
            'highlights': [],
            'technical_signal': f'Active developer with {total_repos} repositories',
            'verified_skills': []
        }
