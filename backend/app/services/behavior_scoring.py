"""
Behavior Scoring for GitHub Candidates

Scores candidates based on GitHub activity signals to determine
if they're worth ingesting into the database.

Scoring Criteria (100 base + 15 bonus max):
- Activity signals (40 pts): Recent commits, last active date
- Intent signals (30 pts): Hireable flag, bio keywords, no company, email, README, links
- Quality signals (35 pts): Active maintenance, original repos, OSS contributions, languages, stars
- Company bonus (0-15 pts): YC companies (+15), Unicorns/Series A-B (+10), Big tech (+5)

Tiers:
- Hot (score >= 70): Active, high quality, reach out immediately
- Warm (score >= 30): Worth outreach (lowered to catch mid-career + hireable juniors)
- Cold (score < 30): Skip
"""

from typing import Dict, Tuple
from datetime import datetime, date


def calculate_behavior_score(candidate_data: Dict) -> Tuple[int, str, Dict]:
    """
    Calculate behavior score from GitHub signals.

    Args:
        candidate_data: Dict with GitHub metrics

    Returns:
        Tuple of (score, tier, breakdown)
        - score: 0-100 behavior score
        - tier: "hot" / "warm" / "cold"
        - breakdown: Dict with scoring details
    """
    score = 0
    breakdown = {
        "activity": 0,
        "intent": 0,
        "quality": 0,
        "company_bonus": 0,
        "details": []
    }

    # === ACTIVITY SIGNALS (40 points max) ===

    # Recent commits with recency weighting (30 points)
    # Weight recent activity more heavily than older activity
    commits_30d = candidate_data.get('github_commits_30d', 0)
    commits_90d = candidate_data.get('github_commits_90d', 0)
    current_year_commits = candidate_data.get('github_current_year_commits', 0)
    previous_year_commits = candidate_data.get('github_previous_year_commits', 0)

    # Calculate weighted activity score with recency decay
    # Current year = 100% weight, previous year = 50% weight
    weighted_recent_activity = current_year_commits + (previous_year_commits * 0.5)

    if commits_30d >= 20:
        activity_score = 30
        breakdown["details"].append("Very active: 20+ commits in 30 days")
    elif commits_30d >= 10:
        activity_score = 25
        breakdown["details"].append("Active: 10+ commits in 30 days")
    elif commits_30d >= 5:
        activity_score = 20
        breakdown["details"].append("Moderately active: 5+ commits in 30 days")
    elif weighted_recent_activity >= 100:
        # Bonus for sustained activity with recency preference
        activity_score = 18
        breakdown["details"].append(f"Sustained activity: {current_year_commits} current year, {previous_year_commits} previous year")
    elif commits_90d >= 20:
        activity_score = 15
        breakdown["details"].append("Active in last 90 days")
    elif commits_90d >= 10:
        activity_score = 10
        breakdown["details"].append("Some activity in last 90 days")
    else:
        activity_score = 0
        breakdown["details"].append("Low recent activity")

    score += activity_score
    breakdown["activity"] = activity_score

    # Last active date (10 points)
    last_active = candidate_data.get('github_last_active')
    if last_active:
        if isinstance(last_active, str):
            last_active = datetime.fromisoformat(last_active.replace('Z', '+00:00')).date()

        days_since_active = (date.today() - last_active).days

        if days_since_active <= 7:
            active_recency = 10
            breakdown["details"].append("Active within last week")
        elif days_since_active <= 30:
            active_recency = 7
            breakdown["details"].append("Active within last month")
        elif days_since_active <= 90:
            active_recency = 5
            breakdown["details"].append("Active within last 3 months")
        else:
            active_recency = 0
            breakdown["details"].append(f"Last active {days_since_active} days ago")

        score += active_recency
        breakdown["activity"] += active_recency

    # === INTENT SIGNALS (25 points max) ===

    # Availability/Hiring Signals
    availability_score = 0

    # Hireable flag with stale detection (5-10 points)
    # People sometimes set hireable=true and forget - cross-check with recent activity
    if candidate_data.get('github_hireable'):
        # Check if hireable flag might be stale (no activity in 180+ days)
        last_active = candidate_data.get('github_last_active')
        if last_active:
            if isinstance(last_active, str):
                last_active = datetime.fromisoformat(last_active.replace('Z', '+00:00')).date()
            days_since_active = (date.today() - last_active).days

            if days_since_active > 180:
                # Stale hireable flag - reduce boost
                availability_score += 5
                breakdown["details"].append("Marked as hireable but inactive 6+ months (stale flag? +5)")
            else:
                # Recent activity confirms they're actively looking
                availability_score += 10
                breakdown["details"].append("Marked as hireable (+10)")
        else:
            # No last_active date, give benefit of doubt
            availability_score += 10
            breakdown["details"].append("Marked as hireable (+10)")

    # Bio hiring keywords (10 points) - explicitly seeking opportunities
    bio = candidate_data.get('github_bio', '') or ''
    hiring_keywords = ['hire', 'hiring', 'available', 'looking', 'open to', 'seeking', 'open for', 'job', 'opportunities']
    if any(keyword in bio.lower() for keyword in hiring_keywords):
        availability_score += 10
        breakdown["details"].append("Bio mentions job seeking (+10)")

    # No current company (5 points) - might be between jobs
    current_company = candidate_data.get('current_company', '') or ''
    if not current_company or current_company.strip() == '':
        availability_score += 5
        breakdown["details"].append("No current company listed (+5)")

    # Has email (5 points) - easier to reach, more serious about being found
    if candidate_data.get('email'):
        availability_score += 5
        breakdown["details"].append("Public email available (+5)")

    score += availability_score
    breakdown["intent"] = availability_score

    # Profile README (5 points) - polishing presence
    if candidate_data.get('github_has_readme'):
        score += 5
        breakdown["intent"] += 5
        breakdown["details"].append("Has profile README (polished presence)")

    # Bio filled out (5 points) - maintaining profile
    if candidate_data.get('github_bio'):
        score += 5
        breakdown["intent"] += 5
        breakdown["details"].append("Has bio")

    # Website/social links (5 points) - professional presence
    links_count = 0
    if candidate_data.get('website_url'):
        links_count += 1
    if candidate_data.get('twitter_url'):
        links_count += 1
    if candidate_data.get('linkedin_url'):
        links_count += 1

    if links_count >= 2:
        score += 5
        breakdown["intent"] += 5
        breakdown["details"].append(f"Has {links_count} professional links")

    # === QUALITY SIGNALS (30 points max) ===

    # Original repos (10 points) - can build things
    original_repos = candidate_data.get('github_original_repos', 0)
    if original_repos >= 10:
        original_score = 10
        breakdown["details"].append(f"{original_repos} original repos")
    elif original_repos >= 5:
        original_score = 7
        breakdown["details"].append(f"{original_repos} original repos")
    elif original_repos >= 3:
        original_score = 5
        breakdown["details"].append(f"{original_repos} original repos")
    else:
        original_score = 0
        breakdown["details"].append(f"Only {original_repos} original repos")

    score += original_score
    breakdown["quality"] = original_score

    # Language diversity (5 points) - versatile
    languages = candidate_data.get('github_languages', [])
    lang_count = len(languages)

    if lang_count >= 5:
        lang_score = 5
        breakdown["details"].append(f"Versatile: {lang_count} languages")
    elif lang_count >= 3:
        lang_score = 3
        breakdown["details"].append(f"{lang_count} languages")
    elif lang_count >= 2:
        lang_score = 2
        breakdown["details"].append(f"{lang_count} languages")
    else:
        lang_score = 0
        breakdown["details"].append("Limited language diversity")

    score += lang_score
    breakdown["quality"] += lang_score

    # Stars received (3 points) - quality work
    total_stars = candidate_data.get('github_total_stars', 0)
    if total_stars >= 100:
        star_score = 3
        breakdown["details"].append(f"{total_stars} total stars (high quality)")
    elif total_stars >= 50:
        star_score = 2
        breakdown["details"].append(f"{total_stars} total stars")
    elif total_stars >= 20:
        star_score = 1
        breakdown["details"].append(f"{total_stars} total stars")
    else:
        star_score = 0

    score += star_score
    breakdown["quality"] += star_score

    # Active maintenance (10 points) - maintains projects regularly
    if candidate_data.get('has_active_maintenance'):
        score += 10
        breakdown["quality"] += 10
        breakdown["details"].append("Actively maintains projects (3+ commits across 2+ months)")

    # OSS contributions (7 points) - contributes to community
    oss_count = candidate_data.get('oss_contributions', 0)
    if oss_count > 0:
        oss_score = min(7, oss_count * 2)  # 2 points per contribution, max 7
        score += oss_score
        breakdown["quality"] += oss_score
        breakdown["details"].append(f"{oss_count} merged PR(s) to popular repos")

    # === COMPANY BONUS ===

    company_tier = candidate_data.get('company_tier', 'none')
    if company_tier == 'yc':
        score += 15
        breakdown["company_bonus"] = 15
        breakdown["details"].append(f"Works at YC company: {candidate_data.get('current_company')} (+15)")
    elif company_tier == 'unicorn':
        score += 10
        breakdown["company_bonus"] = 10
        breakdown["details"].append(f"Works at unicorn/funded startup: {candidate_data.get('current_company')} (+10)")
    elif company_tier == 'bigtech':
        score += 5
        breakdown["company_bonus"] = 5
        breakdown["details"].append(f"Works at big tech: {candidate_data.get('current_company')} (+5)")

    # === NEGATIVE SIGNALS (penalties) ===
    negative_score = 0
    bio = candidate_data.get('github_bio', '') or ''
    bio_lower = bio.lower()

    # "Not looking" signals (-10) - explicitly not interested
    # This is the ONLY negative signal - students and short tenure can still be great fits
    not_looking_keywords = ['not looking', 'not interested', 'not seeking', 'not available', 'not open to']
    if any(keyword in bio_lower for keyword in not_looking_keywords):
        negative_score -= 10
        breakdown["details"].append("⚠️ 'Not looking' signal in bio (-10)")

    # Apply negative signals
    if negative_score < 0:
        score += negative_score  # negative_score is already negative
        breakdown["negative_signals"] = negative_score
    else:
        breakdown["negative_signals"] = 0

    # === DETERMINE TIER ===

    if score >= 70:
        tier = "hot"
    elif score >= 30:  # Lowered from 40 to catch more mid-career + hireable candidates
        tier = "warm"
    else:
        tier = "cold"

    breakdown["total"] = score

    return score, tier, breakdown
