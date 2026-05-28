"""
Complete VibeChekk DeepSeek Prompt - Exact Port

This is vibechekk's full production prompt (lines 564-829) ported to Python.
Includes all examples, edge cases, and engineered instructions.
"""

import requests
import json
from typing import Dict, List
from datetime import datetime, timedelta
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_candidate_specific_archetype_reason(
    archetype: str,
    composite_score: int,
    tier: str,
    total_stars: int,
    total_repo_count: int,
    last_90_days_commits: int,
    highest_stars: int,
    external_contribs: int,
    account_age_years: float,
    quality_points: int,
    languages: List
) -> str:
    """Generate candidate-specific archetype reasoning (like VibeChekk)"""

    # Build evidence-based reasoning specific to THIS candidate
    reasons = []

    if archetype == 'THE 10X ENGINEER':
        reasons.append(f"Classified as 10X ENGINEER because exceptional across visibility, quality, and depth with {total_stars:,} total stars across {total_repo_count} repositories")
        if highest_stars >= 10000:
            reasons.append(f"Top repository has {highest_stars:,} stars showing industry-wide impact")

    elif archetype == 'THE ARCHITECT':
        reasons.append(f"Classified as ARCHITECT because strong on multiple dimensions of engineering excellence with {total_stars:,} total stars across {total_repo_count} repositories")
        if quality_points >= 20:
            reasons.append("Demonstrates system design patterns with production-grade code quality")

    elif archetype == 'THE PROFESSOR':
        reasons.append(f"Classified as PROFESSOR due to exceptional documentation and teaching signals with {total_stars:,} stars across {total_repo_count} repositories")
        reasons.append("Strong community knowledge sharing and educational content")

    elif archetype == 'THE SPECIALIST':
        reasons.append(f"Classified as SPECIALIST because focused technical depth with {total_stars:,} total stars across {total_repo_count} repositories")
        if quality_points >= 15:
            reasons.append("Professional code quality showing domain specialization")

    elif archetype == 'THE SYSTEMS THINKER':
        reasons.append(f"Classified as SYSTEMS THINKER due to infrastructure and distributed systems focus with {total_repo_count} repositories")
        reasons.append("Complex architectures with production-grade implementations")

    elif archetype == 'THE MAINTAINER':
        reasons.append(f"Classified as MAINTAINER because actively maintains open-source projects with {total_stars:,} stars showing community adoption")
        if external_contribs >= 20:
            reasons.append(f"Also contributed to {external_contribs} external projects showing OSS engagement")

    elif archetype == 'THE CONTRIBUTOR':
        reasons.append(f"Classified as CONTRIBUTOR with {external_contribs} contributions to external projects")
        reasons.append(f"Active OSS participant with {total_stars:,} stars across {total_repo_count} own repositories")

    elif archetype == 'THE BUILDER':
        reasons.append(f"Classified as BUILDER because ships consistently with {last_90_days_commits} commits in last 90 days across {total_repo_count} repositories")
        reasons.append("Strong development momentum and practical execution")

    elif archetype == 'THE CRAFTSPERSON':
        reasons.append(f"Classified as CRAFTSPERSON due to high code quality focus with evidence of testing, CI/CD, and production-grade patterns")
        reasons.append(f"Engineering discipline evident across {total_repo_count} repositories with {total_stars:,} stars")

    elif archetype == 'THE HIDDEN GEM':
        reasons.append(f"Classified as HIDDEN GEM - demonstrates strong technical skills but has limited community visibility with {total_stars} total stars across {total_repo_count} repositories")
        reasons.append("Quality over popularity with evidence of solid engineering practices")

    elif archetype == 'THE GRINDER':
        reasons.append(f"Classified as GRINDER because exceptionally high commit velocity with {last_90_days_commits} commits in last 90 days")
        reasons.append(f"Sustained activity and consistent output across {total_repo_count} repositories")

    elif archetype == 'THE TINKERER':
        reasons.append(f"Classified as TINKERER - practical problem solver with {total_repo_count} repositories across {len(languages)} languages")
        reasons.append(f"Hands-on building with {last_90_days_commits} recent commits showing active development")

    elif archetype == 'THE HOBBYIST':
        reasons.append(f"Classified as HOBBYIST because passion-driven coding with {last_90_days_commits} commits across {total_repo_count} personal projects")
        reasons.append("Active exploration and learning mindset")

    elif archetype == 'THE EXPLORER':
        reasons.append(f"Classified as EXPLORER due to technology diversity with {len(languages)} languages across {total_repo_count} repositories")
        reasons.append("Breadth over depth showing curiosity-driven development")

    elif archetype == 'THE APPRENTICE':
        reasons.append(f"Classified as APPRENTICE - early career developer with {account_age_years:.0f} years on GitHub")
        reasons.append(f"Building foundational skills across {total_repo_count} repositories with {last_90_days_commits} recent commits")

    return ". ".join(reasons) + "."


def fetch_github_contributions_graphql(username: str, github_token: str) -> tuple[int, int]:
    """
    Fetch accurate 90-day commit count and external contributions using GitHub GraphQL API.

    External contributions = repos contributed to but don't own (excludes own repos/forks)

    Returns:
        tuple[int, int]: (total_commits_90d, external_contributions)
    """
    from_date = (datetime.utcnow() - timedelta(days=90)).isoformat() + "Z"

    query = """
    query($username: String!, $from: DateTime!) {
      user(login: $username) {
        recentActivity: contributionsCollection(from: $from) {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          totalRepositoryContributions
          contributionCalendar {
            totalContributions
          }
        }
        repositoriesContributedTo(first: 100, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]) {
          totalCount
          nodes {
            nameWithOwner
            owner {
              login
            }
          }
        }
      }
    }
    """

    try:
        response = requests.post(
            "https://api.github.com/graphql",
            headers={
                "Authorization": f"bearer {github_token}",
                "Content-Type": "application/json"
            },
            json={"query": query, "variables": {"username": username, "from": from_date}},
            timeout=10
        )

        if response.ok:
            data = response.json()

            # Debug: Log full response to diagnose external contributions issue
            if data.get("errors"):
                logger.error("GraphQL errors for %s: %s", username, data['errors'])

            user_data = data.get("data", {}).get("user", {})
            contributions = user_data.get("recentActivity", {})
            total_commits = contributions.get("contributionCalendar", {}).get("totalContributions", 0)

            # External contributions = repos contributed to but don't own
            # Filter out repos where they are the owner
            contributed_repos = user_data.get("repositoriesContributedTo", {})
            all_contributed = contributed_repos.get("nodes", [])

            # Count only external repos (owner.login != username)
            external_repos = [
                repo for repo in all_contributed
                if repo.get("owner", {}).get("login", "").lower() != username.lower()
            ]
            external_contribs = len(external_repos)

            # Debug: Log if external contributions detected
            if external_contribs > 0:
                sample_repos = [repo.get("nameWithOwner", "") for repo in external_repos[:3]]
                logger.info("%s contributed to %d external repos (e.g., %s)", username, external_contribs, ', '.join(sample_repos))

            return total_commits, external_contribs
        else:
            logger.warning("GraphQL HTTP %d for %s: %s", response.status_code, username, response.text[:200])
    except Exception as e:
        logger.error("GraphQL error for %s: %s", username, e)

    return 0, 0


def calculate_classification(
    username: str,
    github_token: str,
    top_repos: List[Dict],
    quality_signals: List[Dict],
    github_data: Dict
) -> Dict:
    """
    Calculate tier and archetype classification based on composite scoring.

    This is the definitive source of truth for classification.
    Returns: {tier, archetype, composite_score, score_breakdown, metrics}
    """

    # Fetch accurate 90-day commits and external contributions via GraphQL
    last_90_days_commits, external_contribs_graphql = fetch_github_contributions_graphql(username, github_token)

    # Extract metrics
    highest_stars = max([r.get('stars', 0) for r in top_repos], default=0)
    total_stars = sum([r.get('stars', 0) for r in top_repos]) if top_repos else 0
    repo_count = len(top_repos)  # Count of top repos analyzed
    total_repo_count = github_data.get('github_public_repos', repo_count)  # Actual total from GitHub

    # Account age
    created_at = github_data.get('created_at')
    if created_at:
        account_age_years = (datetime.utcnow() - datetime.fromisoformat(created_at.replace('Z', ''))).days / 365.25
    else:
        account_age_years = 1

    # Languages
    languages = github_data.get('github_languages', [])

    # Composite scoring (adjusted for fairness)
    # VISIBILITY (0-25) - Smooth progression, no cliff at 10 stars
    visibility_points = 0
    if highest_stars >= 100000: visibility_points = 25
    elif highest_stars >= 50000: visibility_points = 23
    elif highest_stars >= 10000: visibility_points = 21
    elif highest_stars >= 5000: visibility_points = 19
    elif highest_stars >= 1000: visibility_points = 17
    elif highest_stars >= 500: visibility_points = 15
    elif highest_stars >= 250: visibility_points = 12
    elif highest_stars >= 100: visibility_points = 9
    elif highest_stars >= 50: visibility_points = 6
    elif highest_stars >= 10: visibility_points = 3
    elif highest_stars >= 5: visibility_points = 1  # NEW: Recognize small adoption (5-9 stars)

    # QUALITY (0-30) - Less web-dev biased, add baseline for substantive projects
    quality_points = 0
    has_tests = any(q.get('hasTests') for q in quality_signals if q)
    has_ci = any(q.get('hasCI') for q in quality_signals if q)
    has_typescript = any(q.get('hasTypeScript') for q in quality_signals if q)
    has_linting = any(q.get('hasLinting') for q in quality_signals if q)
    has_docs = any(q.get('hasDocs') for q in quality_signals if q)
    avg_file_count = sum(q.get('fileCount', 0) for q in quality_signals if q) / max(len(quality_signals), 1)

    # Baseline points for having substantive projects (compensates for missing web tooling)
    if avg_file_count > 50:
        quality_points += 3  # Baseline for substantial engineering work (file count only, no star double-counting)

    if has_tests: quality_points += 8      # Critical quality signal
    if has_ci: quality_points += 8         # Critical quality signal
    if has_typescript: quality_points += 1 # Minor bonus (reduced from 2 to minimize JS bias)
    if has_linting: quality_points += 0    # Removed (too JS-specific, non-JS langs use formatters we don't detect)
    if has_docs: quality_points += 5       # Increased from 4 (universal quality signal)
    if avg_file_count > 100: quality_points += 5  # Was 4, now 5
    elif avg_file_count > 50: quality_points += 3 # New tier
    elif avg_file_count > 30: quality_points += 2 # Same

    # ACTIVITY (0-25) - Smooth progression, no cliffs
    activity_points = 0
    if last_90_days_commits >= 100: activity_points += 10
    elif last_90_days_commits >= 50: activity_points += 9
    elif last_90_days_commits >= 20: activity_points += 7
    elif last_90_days_commits >= 10: activity_points += 5
    elif last_90_days_commits >= 5: activity_points += 3
    elif last_90_days_commits >= 2: activity_points += 1  # NEW: Recognize minimal activity (2-4 commits)

    if total_repo_count >= 20: activity_points += 8
    elif total_repo_count >= 15: activity_points += 7             # New tier
    elif total_repo_count >= 10: activity_points += 6             # Was 5, now 6
    elif total_repo_count >= 5: activity_points += 4              # Was 3, now 4
    elif total_repo_count >= 3: activity_points += 2              # New tier

    # Use GraphQL-fetched external contributions (PRs + Issues to external repos)
    external_contribs = external_contribs_graphql
    if external_contribs >= 50: activity_points += 7
    elif external_contribs >= 20: activity_points += 5      # Was 4, now 5
    elif external_contribs >= 10: activity_points += 3      # New tier
    elif external_contribs >= 5: activity_points += 2       # Same

    # EXPERTISE (0-20) - More generous for experienced accounts
    expertise_points = 0
    if account_age_years >= 10: expertise_points += 8    # Was 6, now 8
    elif account_age_years >= 7: expertise_points += 7   # Was 5, now 7
    elif account_age_years >= 5: expertise_points += 6   # Was 4, now 6
    elif account_age_years >= 3: expertise_points += 4   # Was 2, now 4
    elif account_age_years >= 2: expertise_points += 2   # New tier

    if len(languages) >= 7: expertise_points += 6        # Was 5, now 6
    elif len(languages) >= 5: expertise_points += 4      # Was 3, now 4
    elif len(languages) >= 3: expertise_points += 3      # Was 2, now 3
    elif len(languages) >= 2: expertise_points += 1      # New tier

    # Total composite score
    composite_score = visibility_points + quality_points + activity_points + expertise_points

    # DEBUG: Log scoring breakdown with archetype-relevant dimensions (null-safe)
    langs_count = len(languages) if languages else 0
    logger.debug("%s: composite=%d (vis=%d, qual=%d, act=%d, exp=%d) | commits_90d=%d | repos_analyzed=%d | total_repos=%d | langs=%d | external=%d",
                 username, composite_score, visibility_points, quality_points, activity_points, expertise_points,
                 last_90_days_commits, repo_count, total_repo_count, langs_count, external_contribs)

    # Dynamic archetype determination based on composite score AND behavioral signals
    # This enables all 15 archetypes (not just 5 hardcoded ones)

    # Check for maintainer status (tier-specific thresholds)
    is_maintainer = any(r.get('is_maintainer') and r.get('stars', 0) >= 50 for r in top_repos)  # Lowered from 100
    high_impact_maintainer = any(r.get('is_maintainer') and r.get('stars', 0) >= 500 for r in top_repos)

    # STEP 1: Calculate tier from composite score
    # Thresholds rebalanced for more even distribution across score range
    # Calibrated for pre-filtered candidate pool (behavior_score ≥30, active, 5+ repos)
    if composite_score >= 85:  # Lowered from 88
        tier = 'LEGENDARY'
        tier_badge = '🌟🌟🌟'
        percentile = 'Top 1%'
    elif composite_score >= 73:  # Lowered from 78
        tier = 'ULTRA RARE'
        tier_badge = '🌟🌟'
        percentile = 'Top 5%'
    elif composite_score >= 60:  # Lowered from 65
        tier = 'RARE'
        tier_badge = '⭐'
        percentile = 'Top 15%'
    elif composite_score >= 47:  # Lowered from 50
        tier = 'UNCOMMON'
        tier_badge = '◆'
        percentile = 'Top 30%'
    else:
        tier = 'COMMON'
        tier_badge = '●'
        percentile = 'Top 50%'

    # STEP 2: Archetype determined by DeepSeek (not Python)
    # Python only provides tier - DeepSeek independently classifies archetype
    archetype = None  # Will be determined by DeepSeek

    # Quality tier
    quality_tier = 'production-ready' if quality_points >= 24 else 'professional' if quality_points >= 15 else 'developing' if quality_points >= 6 else 'basic'

    # Activity level
    if last_90_days_commits > 50: recently_active = 'very-active'
    elif last_90_days_commits > 20: recently_active = 'active'
    elif last_90_days_commits > 5: recently_active = 'occasional'
    else: recently_active = 'dormant'

    # Tier badges and percentiles already set above (lines 305-324)

    # Return classification result
    return {
        'tier': tier,
        'archetype': archetype,
        'tier_badge': tier_badge,
        'percentile': percentile,
        'composite_score': composite_score,
        'score_breakdown': {
            'visibility': visibility_points,
            'quality': quality_points,
            'activity': activity_points,
            'expertise': expertise_points
        },
        'metrics': {
            'last_90_days_commits': last_90_days_commits,
            'highest_stars': highest_stars,
            'total_stars': total_stars,
            'repo_count': repo_count,
            'total_repo_count': total_repo_count,
            'account_age_years': account_age_years,
            'external_contribs': external_contribs,
            'languages': languages,
            'quality_tier': quality_tier,
            'recently_active': recently_active,
            'has_tests': has_tests,
            'has_ci': has_ci,
            'has_typescript': has_typescript,
            'has_linting': has_linting,
            'has_docs': has_docs,
            'avg_file_count': avg_file_count,
            'is_maintainer': is_maintainer
        }
    }


def analyze_with_full_vibechekk_prompt(
    api_key: str,
    username: str,
    classification: Dict,
    top_repos: List[Dict],
    quality_signals: List[Dict],
    code_samples: str = "No code samples available",
    resume_text: str = None
) -> Dict:
    """
    DeepSeek independently classifies archetype + generates narrative.

    Python provides tier (score-based) - DeepSeek classifies archetype within tier.
    No anchoring bias - DeepSeek makes independent decision based on evidence.
    """

    # Extract classification results from Python
    tier = classification['tier']
    tier_badge = classification['tier_badge']
    percentile = classification['percentile']
    composite_score = classification['composite_score']
    score_breakdown = classification['score_breakdown']
    metrics = classification['metrics']
    # Note: archetype is None (DeepSeek will determine it)

    # Unpack metrics for prompt
    last_90_days_commits = metrics['last_90_days_commits']
    highest_stars = metrics['highest_stars']
    total_stars = metrics['total_stars']
    repo_count = metrics['repo_count']
    total_repo_count = metrics['total_repo_count']
    account_age_years = metrics['account_age_years']
    external_contribs = metrics['external_contribs']
    languages = metrics['languages']
    quality_tier = metrics['quality_tier']
    recently_active = metrics['recently_active']
    has_tests = metrics['has_tests']
    has_ci = metrics['has_ci']
    has_typescript = metrics['has_typescript']
    has_linting = metrics['has_linting']
    has_docs = metrics['has_docs']
    avg_file_count = metrics['avg_file_count']
    visibility_points = score_breakdown['visibility']
    quality_points = score_breakdown['quality']
    activity_points = score_breakdown['activity']
    expertise_points = score_breakdown['expertise']

    # Format repo list with fork status (CRITICAL for accurate analysis)
    repo_list_str = ""
    for i, repo in enumerate(top_repos[:10]):
        qual = quality_signals[i] if i < len(quality_signals) else {}
        markers = []
        if qual.get('hasTests'): markers.append('✓Tests')
        if qual.get('hasCI'): markers.append('✓CI')
        markers_str = ' '.join(markers) if markers else ''

        # Show fork status explicitly
        fork_status = "(Fork)" if repo.get('is_fork', False) else "(Original)"

        repo_list_str += f"• {repo.get('name')} {fork_status} ({repo.get('language', 'Unknown')}, {repo.get('stars', 0)}⭐) {markers_str}\n"

    # Define 1:1 archetype/tier mapping (Option B: Precise specifications)
    # Calibrated for pre-filtered pool (50+ repos, active Python developers)
    TIER_ARCHETYPES = {
        'LEGENDARY': {
            'THE 10X ENGINEER': 'Industry-defining impact, frameworks/tools used by thousands'
        },
        'ULTRA RARE': {
            'THE ARCHITECT': 'System design at scale, maintains quality in complex systems, scalable architecture patterns',
            'THE PROFESSOR': 'Comprehensive technical writing (API docs, tutorials, guides), proven teaching impact'
        },
        'RARE': {
            'THE SPECIALIST': 'Deep domain expertise with production-grade code, niche mastery',
            'THE SYSTEMS THINKER': 'Infrastructure/distributed systems, complex architectures',
            'THE MAINTAINER': 'OSS project maintenance, community engagement'
            # PROFESSOR removed - ULTRA RARE exclusive (73+ score required)
        },
        'UNCOMMON': {
            'THE CRAFTSPERSON': 'Code quality obsession as PRIMARY identity, exceptional engineering discipline across all projects',
            'THE BUILDER': 'Ships quality products consistently, development momentum',
            'THE CONTRIBUTOR': 'Active OSS participation, multiple project contributions',
            'THE HIDDEN GEM': 'Strong skills but low visibility, quality over popularity',
            'THE EXPLORER': 'True polyglot breadth (15+ languages OR 100+ repos), extreme technology diversity'
            # EXPLORER moved from COMMON - raised bar for pre-filtered pool
        },
        'COMMON': {
            'THE TINKERER': 'Practical problem solving, ships practical applications, hands-on building',
            'THE GRINDER': 'High commit velocity, sustained activity',
            'THE HOBBYIST': 'Passion-driven coding, active exploration, personal projects',
            'THE APPRENTICE': 'Early career, building foundations, portfolio development'
            # EXPLORER removed - moved to UNCOMMON with higher threshold
        }
    }

    # Get valid archetypes for this tier
    valid_archetypes = TIER_ARCHETYPES[tier]
    archetypes_list = '\n'.join([f"- **{name}**: {desc}" for name, desc in valid_archetypes.items()])

    # Build the independent classification prompt
    prompt = f"""⚠️⚠️⚠️ CRITICAL INSTRUCTION - READ FIRST ⚠️⚠️⚠️

This developer has {account_age_years:.0f} years of GitHub history. Your assessment MUST prioritize RECENT work (last 2 years) as their CURRENT skill level.

**Critical Rules:**
- Recent work (last 2 years) defines current skill level
- Old repos provide context but do NOT define current ability
- Mark historical skills (5+ years old) as "Historical" explicitly in evidence

════════════════════════════════════════════════════════════════

## YOUR CLASSIFICATION TASK

Based on the metrics and code evidence below, classify this developer into ONE archetype.

**Tier:** {tier} {tier_badge} ({percentile})

**Composite Score:** {composite_score}/100
- Visibility: {visibility_points}/25 (stars, reach)
- Quality: {quality_points}/30 (tests, CI, docs, architecture)
- Activity: {activity_points}/25 (commits, repos, OSS contributions)
- Expertise: {expertise_points}/20 (account age, language diversity)

**Available Archetypes for {tier} Tier:**
{archetypes_list}

**CLASSIFICATION RULES - STRICT ENFORCEMENT:**

This is a PRE-FILTERED pool (50+ repos, active Python developers). Apply higher standards:

**THE PROFESSOR** - ULTRA RARE ONLY (73+ score required):
- 5+ substantial documentation files (tutorials/, guides/, comprehensive API docs)
- NOT just README + a few markdown reference files
- Evidence of TEACHING INTENT: walkthroughs, educational content, architecture explanations
- Must demonstrate exceptional documentation that teaches others
- If only standard README + basic docs → NOT PROFESSOR (consider ARCHITECT or MAINTAINER)

**THE EXPLORER** - UNCOMMON ONLY (47-59 score range):
- 15+ distinct programming languages OR 100+ repositories
- NOT just JavaScript + TypeScript + JSON/YAML config files
- True polyglot breadth across different paradigms (functional, systems, scripting, web, mobile, etc.)
- Must show genuine expertise across multiple technology stacks
- If 5-14 languages with standard web stack → NOT EXPLORER (consider BUILDER or TINKERER)
- If 50-99 repos without extreme breadth → NOT EXPLORER (consider TINKERER or HOBBYIST)

**THE TINKERER** - Requires:
- Multiple practical applications that solve real problems
- NOT just code experiments or learning repos
- Evidence of shipping: deployed projects, production use, real users
- If mostly experimental/learning repos → consider HOBBYIST or APPRENTICE instead

**THE MAINTAINER** - Requires:
- Active OSS project ownership with community engagement
- NOT just owning repos with few contributors
- Evidence: issue responses, PR reviews, community discussions
- If solo projects with minimal external contributions → consider BUILDER instead

**THE CRAFTSPERSON** - ONLY if quality is PRIMARY identity:
- Quality score 24+ out of 30 (exceptional, not just baseline)
- MULTIPLE quality signals present (tests + CI + linting + docs + TypeScript)
- NOT just "has tests and CI" (that's baseline in this pre-filtered pool)
- Quality is DEFINING characteristic, not just present alongside other traits
- IMPORTANT: Choose other archetypes if candidate has quality + another strong identity:
  * Quality + complex system design → THE ARCHITECT (not CRAFTSPERSON)
  * Quality + ships products → THE BUILDER (not CRAFTSPERSON)
  * Quality + domain expertise → THE SPECIALIST (not CRAFTSPERSON)
  * Quality + OSS maintenance → THE MAINTAINER (not CRAFTSPERSON)
  * Quality + extreme breadth → THE EXPLORER (not CRAFTSPERSON)
- CRAFTSPERSON is for developers whose PRIMARY identity is quality obsession, not just good engineering practices

**Instructions:**
1. Analyze the metrics, repos, and code samples below
2. Apply the CLASSIFICATION RULES above strictly
3. Pick the ONE archetype that best fits this developer's profile
4. Generate a complete professional assessment explaining your classification

---

## GITHUB PROFILE DATA

**Activity Metrics:**
- Account age: {account_age_years:.1f} years | Total repos: {repo_count} | Total stars: {total_stars}
- Recent activity: {last_90_days_commits} commits (last 90 days) - {recently_active}
- External contributions: {external_contribs} contributions to other projects
- Code quality tier: {quality_tier}

**Quality Indicators:**
- Tests: {'✓ Yes' if has_tests else '✗ No'} | CI/CD: {'✓ Yes' if has_ci else '✗ No'}
- TypeScript: {'✓ Yes' if has_typescript else '✗ No'} | Linting: {'✓ Yes' if has_linting else '✗ No'}
- Documentation: {'✓ Yes' if has_docs else '✗ No'}
- Avg file count: {avg_file_count:.0f} files per repo

---

## REPOSITORIES

{repo_list_str.strip()}

---

## CODE SAMPLES

The code below shows excerpts from their top repositories, prioritized by recency. Analyze patterns across repos including: code style consistency, complexity progression, architectural choices, and problem-solving approach.

{code_samples}

---

## REQUIRED OUTPUT STRUCTURE

Return JSON with these fields:

**archetype** (string, REQUIRED)
- Pick ONE from the available archetypes list above
- Must match exactly (e.g., "THE TINKERER", "THE CRAFTSPERSON")

**archetype_reason** (3-4 sentences, ~60-80 words)
- Explain WHY your chosen archetype classification fits using evidence
- Cite specific repos (by name), commit patterns, stars, or code quality signals
- Use concrete GitHub data (e.g., "150 stars across 5 repos", "tests and CI in 3 repos")
- Never mention internal scores (e.g., don't say "6/25 visibility" or "29/30 quality")

**trajectory_summary** (2-3 sentences, ~40-50 words)
- Evolution over time, prioritizing recent (last 2 years)
- How their focus/skills have changed

**recruiter_summary** (3 paragraphs, ~120-180 words total)
1. **Current Technical Strengths**: What they can build TODAY
2. **Development Practices**: Code quality, testing, documentation
3. **Team Fit & Seniority**: Best environment, experience level

**highlights** (array of 3-7 strings)
- Each highlight is a single string (NOT an object)
- Include 2-4 positive highlights: Recent achievements citing specific repos (e.g., "Built production REST API with 1.2K stars (repo: awesome-api)")
- Include 1-3 negative highlights: Gaps expected for their tier (e.g., "Missing CI/CD pipeline - expected for RARE tier")
- Be specific with repo names and numbers

**technical_signal** (1 sentence, ~20-30 words)
- One concrete example from recent code

**technical_signal_detailed** (2-3 paragraphs, ~150-200 words)
- Architectural choices, code patterns, complexity handling
- Areas for growth specific to their tier

**verified_skills** (5-8 skills)
- Format: {{"name": "Python", "level": "Advanced", "evidence": "Used in 8 repos with async patterns"}}
- Levels: Beginner, Intermediate, Advanced, Expert
- Mark old skills (5+ years) as "Historical"

---

## QUALITY GUIDELINES

**Evidence-based:**
- Every claim cites specific repos or code patterns
- Never mention composite scores or internal metrics in narratives
- Reference actual repository names

**Balanced:**
- Include genuine concerns, not all positive
- Gaps should be tier-specific (RARE missing MLOps, COMMON missing tests)

**Time-aware:**
- Recent work (last 2 years) defines current skill
- Old work provides context, mark as "Historical"

**Edge cases:**
- Limited code → Focus on repo structure, commit patterns
- Only forks → State explicitly: "All repos are forks; no original work visible"
- Low activity → Be honest: "Insufficient activity for confident assessment"
- Old repos only → "Assessment based on historical work only"

Return ONLY valid JSON matching this structure (no markdown code blocks):"""

    # Add resume text if available
    if resume_text:
        prompt += f"""
## ADDITIONAL CONTEXT: RESUME DATA

The candidate has provided resume information for enriched analysis:

{resume_text}

Use this to fill gaps about experience, projects, education not visible on GitHub.

---
"""

    # Call DeepSeek API
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
                        'content': """You are a senior technical recruiter assessing developers for hiring decisions.

Core principles:
- Evidence-based: Every claim cites specific repos, code patterns, or commit behavior
- Balanced: Include genuine strengths AND concerns (never all positive)
- Actionable: Recruiters know what to probe, managers know technical depth
- Time-aware: Recent work defines current skill, old work provides context only

Quality standards:
- Reference specific technologies and repository names
- Mark historical skills (5+ years old) as "Historical" explicitly
- Never mention internal scores or composite metrics
- Write for hiring managers, not social media

CRITICAL: You must classify the developer into ONE archetype from the provided tier options."""
                    },
                    {'role': 'user', 'content': prompt}
                ],
                'response_format': {
                    'type': 'json_object',
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'archetype': {
                                'type': 'string',
                                'enum': list(valid_archetypes.keys())  # Enforced by API - only valid archetypes allowed
                            },
                            'archetype_reason': {'type': 'string'},
                            'trajectory_summary': {'type': 'string'},
                            'recruiter_summary': {'type': 'string'},
                            'highlights': {
                                'type': 'array',
                                'items': {'type': 'string'},
                                'minItems': 3,
                                'maxItems': 7
                            },
                            'technical_signal': {'type': 'string'},
                            'technical_signal_detailed': {'type': 'string'},
                            'verified_skills': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'name': {'type': 'string'},
                                        'level': {'type': 'string'},
                                        'evidence': {'type': 'string'}
                                    },
                                    'required': ['name', 'level', 'evidence']
                                },
                                'minItems': 5,
                                'maxItems': 8
                            }
                        },
                        'required': ['archetype', 'archetype_reason', 'trajectory_summary', 'recruiter_summary', 'highlights', 'technical_signal', 'technical_signal_detailed', 'verified_skills']
                    }
                },
                'temperature': 0.3
            },
            timeout=60
        )

        if not response.ok:
            logger.error("DeepSeek API error: %d - %s", response.status_code, response.text)
            raise Exception(f"DeepSeek API error: {response.status_code}")

        data = response.json()
        raw_content = data['choices'][0]['message']['content']

        # Parse JSON
        try:
            analysis = json.loads(raw_content.strip())
        except json.JSONDecodeError:
            if '```' in raw_content:
                raw_content = raw_content.replace('```json', '').replace('```', '').strip()
            analysis = json.loads(raw_content)

        # Extract archetype from DeepSeek's response
        deepseek_archetype = analysis.get('archetype')

        # Validate archetype is in valid list (should be enforced by API schema)
        if deepseek_archetype not in valid_archetypes:
            logger.warning("Invalid archetype '%s' for tier %s, defaulting to first option", deepseek_archetype, tier)
            deepseek_archetype = list(valid_archetypes.keys())[0]

        # Add classification metadata
        # - Tier from Python (objective score-based threshold)
        # - Archetype from DeepSeek (independent classification)
        analysis['label'] = deepseek_archetype
        analysis['rarity'] = tier
        analysis['rarity_badge'] = tier_badge
        analysis['rarity_percentile'] = percentile
        analysis['composite_score'] = composite_score
        analysis['score_breakdown_detailed'] = score_breakdown

        logger.info("Generated narrative for %s (%s, %s)", username, deepseek_archetype, tier)
        return analysis

    except Exception as e:
        logger.error("Failed to generate narrative: %s", e)

        # Fallback: Default to first archetype in tier
        fallback_archetype = list(valid_archetypes.keys())[0]
        logger.info("Using fallback archetype: %s", fallback_archetype)

        # Fallback with basic narrative using classification helper
        return {
            'label': fallback_archetype,
            'rarity': tier,
            'rarity_badge': tier_badge,
            'rarity_percentile': percentile,
            'composite_score': composite_score,
            'score_breakdown_detailed': score_breakdown,
            'archetype_reason': get_candidate_specific_archetype_reason(
                fallback_archetype, composite_score, tier, total_stars, total_repo_count,
                last_90_days_commits, highest_stars, external_contribs,
                account_age_years, quality_points, languages
            ),
            'trajectory_summary': f'GitHub history of {account_age_years:.0f} years with {last_90_days_commits} commits in last 90 days, showing {"high" if last_90_days_commits >= 50 else "moderate" if last_90_days_commits >= 20 else "light"} recent activity.',
            'recruiter_summary': f'Developer with {account_age_years:.0f} years on GitHub across {total_repo_count} repositories. Recent activity: {last_90_days_commits} commits in 90 days. Total impact: {total_stars} stars.',
            'highlights': [],
            'technical_signal': f'GitHub activity: {total_stars} stars across {total_repo_count} repositories',
            'verified_skills': []
        }
