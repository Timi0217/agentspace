"""
Personalized Outreach Generator

Generates customized cold outreach emails based on candidate's GitHub analysis.
Uses DeepSeek to create authentic, personalized messages that reference specific work.
"""

import requests
import json
from typing import Dict, Optional, List
from datetime import datetime
from app.core.logging import get_logger

logger = get_logger(__name__)

# Minor words that stay lowercase in title case (unless first word)
_MINOR_WORDS = {'a', 'an', 'the', 'and', 'but', 'or', 'for', 'in', 'on', 'at', 'to', 'of', 'nor', 'so', 'yet'}


def _title_case_subject(subject: str) -> str:
    """
    Title-case a subject line: capitalize first letter of major words,
    keep minor words lowercase (except first word).
    Preserves internal casing so BetterSEO stays BetterSEO, not Betterseo.
    """
    if not subject:
        return subject
    words = subject.split()
    result = []
    for i, word in enumerate(words):
        # Strip leading punctuation for checking (e.g. commas attached to previous word)
        if i == 0 or word.lower().rstrip('?,!.:') not in _MINOR_WORDS:
            # Capitalize first letter, preserve rest of word
            result.append(word[0].upper() + word[1:] if word else word)
        else:
            result.append(word.lower())
    return ' '.join(result)


import re as _re

def _extract_first_name(full_name: str, github_username: str) -> str:
    """
    Extract a clean first name from a GitHub display name.

    GitHub display names can include handles, initials, nicknames, etc.:
      "Dunni DK" -> "Dunni"
      "John Smith" -> "John"
      "Jane (jdoe)" -> "Jane"
      "A. Johnson" -> "Johnson"
      "MD Rafiq" -> "Rafiq" (skip 2-letter uppercase prefixes)
      "" -> use github_username as fallback
    """
    if not full_name or not full_name.strip():
        # Fallback to github username, capitalized
        return github_username.capitalize() if github_username else 'there'

    name = full_name.strip()

    # Remove parenthetical content: "Jane (jdoe)" -> "Jane"
    name = _re.sub(r'\s*\(.*?\)\s*', ' ', name).strip()
    # Remove quoted content: 'Jane "jdoe"' -> "Jane"
    name = _re.sub(r'\s*["\'].*?["\']\s*', ' ', name).strip()

    parts = name.split()
    if not parts:
        return github_username.capitalize() if github_username else 'there'

    first = parts[0]

    # If first token is 1-2 uppercase letters (initials like "DK", "A.", "MD"),
    # or ends with a period, skip to the next token
    if len(parts) > 1 and (
        (len(first) <= 2 and first.replace('.', '').isupper())
        or first.endswith('.')
    ):
        first = parts[1]

    # If the "first name" is all-caps and <= 3 chars, it's likely a handle/initials
    # e.g. "Dunni DK" — DK would've been caught above, but in case first token is the handle
    # Only applies if there's a longer alternative
    if len(parts) > 1 and first.isupper() and len(first) <= 3:
        # Pick the longest non-all-caps token as the actual name
        for p in parts:
            if not p.isupper() and len(p) > 2:
                first = p
                break

    # Capitalize properly (handles "dunni" -> "Dunni")
    return first.capitalize()


def score_repo_relevance(repo: Dict, candidate_languages: List[str], role_context: Optional[Dict] = None) -> float:
    """
    Score a repo for outreach relevance. Prioritizes complexity and substance
    over raw recency — a complex project updated a month ago beats a trivial
    one pushed yesterday.

    When role_context is provided, adds a significant bonus for repos whose
    language, name, or description overlap with the role's tech stack or JD keywords.

    Scoring (max ~130 base + 60 role bonus, with -30 irrelevance penalty):
    - Complexity (35 pts): Repo size as proxy for depth of work
    - Quality (30 pts): Stars, original work, description, maintainer
    - Activity (20 pts): Recency (capped — shouldn't dominate)
    - Relevance (15 pts): Language match with candidate's top languages
    - Conversational (10 pts): Has a description we can actually talk about
    - Role fit (60 pts): Language/keyword overlap with role tech stack and JD
    - Irrelevance penalty (-30 pts): When a role is specified, repos with zero overlap get penalized
    """
    score = 0.0

    # === COMPLEXITY SIGNALS (35 pts) — most important for outreach ===
    size_kb = repo.get('size_kb', 0)
    if size_kb >= 10000:      # 10MB+ — substantial project
        score += 35
    elif size_kb >= 5000:     # 5MB+
        score += 30
    elif size_kb >= 1000:     # 1MB+
        score += 25
    elif size_kb >= 500:      # 500KB+
        score += 20
    elif size_kb >= 100:      # 100KB+
        score += 12
    elif size_kb >= 10:       # 10KB+
        score += 5
    # Tiny repos (<10KB) get 0 — likely empty/starter projects

    # === QUALITY SIGNALS (30 pts) ===

    # Stars (10 pts)
    stars = repo.get('stars', 0)
    if stars >= 50:
        score += 10
    elif stars >= 20:
        score += 8
    elif stars >= 10:
        score += 6
    elif stars >= 5:
        score += 4
    elif stars >= 1:
        score += 2

    # Original vs fork (8 pts) — original work is more interesting to discuss
    if not repo.get('is_fork', False):
        score += 8

    # Is maintainer (7 pts) — their own project
    if repo.get('is_maintainer', False):
        score += 7

    # Forks by others (5 pts) — others found it useful enough to fork
    forks = repo.get('forks', 0)
    if forks >= 10:
        score += 5
    elif forks >= 3:
        score += 3
    elif forks >= 1:
        score += 1

    # === ACTIVITY SIGNALS (20 pts) — matters but shouldn't dominate ===
    updated_at = repo.get('updated_at', '')
    if updated_at:
        try:
            updated_date = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            days_since_update = (datetime.now(updated_date.tzinfo) - updated_date).days

            if days_since_update <= 7:
                score += 20
            elif days_since_update <= 30:
                score += 16
            elif days_since_update <= 90:
                score += 12
            elif days_since_update <= 180:
                score += 8
            elif days_since_update <= 365:
                score += 4
        except (ValueError, TypeError):
            score += 4

    # === RELEVANCE SIGNALS (15 pts) ===
    repo_language = repo.get('language', '')
    if repo_language and candidate_languages:
        if candidate_languages and repo_language == candidate_languages[0]:
            score += 15
        elif repo_language in candidate_languages[:3]:
            score += 10
        elif repo_language in candidate_languages:
            score += 5

    # === CONVERSATIONAL VALUE (10 pts) ===
    # A good description gives the AI something to work with
    description = repo.get('description') or ''
    desc_len = len(description.strip())
    if desc_len >= 50:        # Rich description
        score += 10
    elif desc_len >= 20:      # Decent description
        score += 6
    elif desc_len > 0:        # Bare minimum
        score += 2

    # === ROLE FIT (up to 60 pts bonus / -30 penalty) — when generating for a specific role ===
    # We distinguish between "topical overlap" (repo name/desc matches stack/JD keywords)
    # and "language-only match" (repo is in Python, role uses Python, but repo is unrelated).
    # Language-only match gets minimal credit. Topical overlap is what matters.
    if role_context:
        role_stack = [s.lower() for s in role_context.get('tech_stack', [])]
        jd_text = (role_context.get('description', '') or '').lower()
        repo_name_lower = (repo.get('name') or '').lower()
        repo_desc_lower = description.lower()
        repo_lang_lower = (repo.get('language') or '').lower()
        searchable = f"{repo_name_lower} {repo_desc_lower}"

        has_lang_match = repo_lang_lower and any(repo_lang_lower in s or s in repo_lang_lower for s in role_stack)

        # Repo name/description contains role tech stack keywords (25 pts)
        # Only match against repo NAME (not description) for common language names,
        # because descriptions like "Written in Python" would match everything.
        # Specific tools (aws, docker, kubernetes, etc.) can match in description too.
        generic_langs = {'python', 'javascript', 'typescript', 'java', 'go', 'rust', 'ruby', 'php', 'c++', 'c#', 'swift', 'kotlin'}
        stack_hits = 0
        for s in role_stack:
            if s in generic_langs:
                # Only match in repo name for generic language names
                if s in repo_name_lower:
                    stack_hits += 1
            else:
                # Match in both name and description for specific tools/frameworks
                if s in searchable:
                    stack_hits += 1
        topical_points = 0
        if stack_hits >= 2:
            topical_points += 25
        elif stack_hits >= 1:
            topical_points += 12

        # Repo name/description contains JD domain keywords (25 pts)
        domain_keywords = ['pipeline', 'data', 'api', 'infrastructure', 'deploy', 'distributed',
                           'healthcare', 'fintech', 'ml', 'machine learning', 'ai', 'cloud',
                           'lambda', 'serverless', 'kubernetes', 'docker', 'etl', 'ingestion',
                           'streaming', 'realtime', 'real-time', 'security', 'auth', 'database',
                           'microservice', 'backend', 'devops', 'monitoring', 'analytics',
                           'automation', 'scraping', 'crawler', 'scheduler', 'queue', 'worker']
        jd_domain_hits = [kw for kw in domain_keywords if kw in jd_text and kw in searchable]
        if len(jd_domain_hits) >= 2:
            topical_points += 25
        elif len(jd_domain_hits) >= 1:
            topical_points += 12

        if topical_points > 0:
            # Repo has actual topical overlap — full bonus
            # Language match adds 10 pts on top (minor boost, not the driver)
            score += topical_points
            if has_lang_match:
                score += 10
        elif has_lang_match:
            # Language-only match (e.g. Python string lib for a Python infra role)
            # Minimal credit — same language is weakly relevant at best
            score += 5
        else:
            # No overlap at all — penalize so it doesn't beat relevant repos on stars alone
            score -= 30

    return score


def select_best_repos(repos: List[Dict], candidate_languages: List[str], count: int = 2, role_context: Optional[Dict] = None) -> List[Dict]:
    """
    Select the most relevant repos for outreach based on scoring.

    Args:
        repos: List of repo dictionaries
        candidate_languages: Candidate's top programming languages
        count: Number of repos to select (default 2)
        role_context: Optional role details for role-relevant repo selection

    Returns:
        List of best scoring repos (up to count), or fallback if none available
    """
    if not repos:
        return [{'name': 'your GitHub projects', 'language': None}]

    # Log role context for debugging repo selection
    if role_context:
        logger.info("Repo selection with role context: tech_stack=%s, jd_len=%d",
                     role_context.get('tech_stack', []),
                     len(role_context.get('description', '')))
    else:
        logger.info("Repo selection WITHOUT role context (generic outreach)")

    # Score all repos
    scored_repos = []
    for repo in repos:
        score = score_repo_relevance(repo, candidate_languages, role_context=role_context)
        scored_repos.append((score, repo))

    # Sort by score descending
    scored_repos.sort(key=lambda x: x[0], reverse=True)

    # Return the top N repos
    best_repos = [repo for score, repo in scored_repos[:count]]

    # Log all scored repos (top 8) for debugging
    for i, (score, repo) in enumerate(scored_repos[:8], 1):
        marker = " <<<" if i <= count else ""
        logger.info("Repo #%d: '%s' (lang=%s, stars=%d, size=%dKB) score=%.1f%s",
                     i, repo.get('name'), repo.get('language', ''), repo.get('stars', 0),
                     repo.get('size_kb', 0), score, marker)

    return best_repos


def fetch_repos_for_outreach(github_username: str, github_token: Optional[str] = None) -> List[Dict]:
    """
    Fetch candidate's recent repos from GitHub for outreach personalization.

    Args:
        github_username: GitHub username
        github_token: Optional GitHub API token

    Returns:
        List of repo dictionaries
    """
    headers = {}
    if github_token:
        headers['Authorization'] = f'token {github_token}'

    try:
        repos_url = f"https://api.github.com/users/{github_username}/repos?sort=updated&per_page=100"
        response = requests.get(repos_url, headers=headers, timeout=10)

        if not response.ok:
            logger.warning("Failed to fetch repos for %s: %d", github_username, response.status_code)
            return []

        repos_data = response.json()
        repos = []

        for repo in repos_data[:30]:  # Scan top 30 repos (sorted by updated_at)
            repos.append({
                'name': repo.get('name') or 'unknown',
                'language': repo.get('language'),
                'stars': repo.get('stargazers_count', 0),
                'is_maintainer': repo.get('owner', {}).get('login') == github_username,
                'is_fork': repo.get('fork', False),
                'forks': repo.get('forks_count', 0),
                'size_kb': repo.get('size', 0),
                'description': repo.get('description') or '',
                'updated_at': repo.get('updated_at') or ''
            })

        logger.info("Fetched %d repos for %s", len(repos), github_username)
        return repos

    except Exception as e:
        logger.error("Error fetching repos: %s", e)
        return []


def enrich_repo_context(repo_name: str, github_username: str, github_token: Optional[str] = None) -> Dict:
    """
    Fetch README snippet and recent commit messages for a repo.
    Gives DeepSeek actual context to make specific observations.
    """
    headers = {}
    if github_token:
        headers['Authorization'] = f'token {github_token}'

    context = {'readme_snippet': '', 'recent_commits': []}

    try:
        # Fetch README (first 500 chars)
        readme_url = f"https://api.github.com/repos/{github_username}/{repo_name}/readme"
        readme_resp = requests.get(readme_url, headers=headers, timeout=5)
        if readme_resp.ok:
            import base64
            readme_data = readme_resp.json()
            content = readme_data.get('content', '')
            if content:
                decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
                # Strip markdown headers and take first 500 chars
                lines = [l for l in decoded.split('\n') if not l.startswith('#') and l.strip()]
                context['readme_snippet'] = ' '.join(lines)[:500].strip()
    except Exception as e:
        logger.debug("Failed to fetch README for %s/%s: %s", github_username, repo_name, e)

    try:
        # Fetch last 5 commit messages
        commits_url = f"https://api.github.com/repos/{github_username}/{repo_name}/commits?per_page=5"
        commits_resp = requests.get(commits_url, headers=headers, timeout=5)
        if commits_resp.ok:
            commits_data = commits_resp.json()
            context['recent_commits'] = [
                c.get('commit', {}).get('message', '').split('\n')[0][:100]
                for c in commits_data[:5]
                if c.get('commit', {}).get('message')
            ]
    except Exception as e:
        logger.debug("Failed to fetch commits for %s/%s: %s", github_username, repo_name, e)

    return context


def generate_outreach_template(
    api_key: str,
    candidate: Dict,
    github_token: Optional[str] = None,
    role_context: Optional[Dict] = None,
    fit_analysis: Optional[Dict] = None,
) -> Dict:
    """
    Generate personalized outreach email template.

    If role_context is provided, generates a role-specific cold outreach that references
    the JD, comp, investors, and why the candidate is a fit. Otherwise generates a
    generic warm-up email.

    Args:
        api_key: DeepSeek API key
        candidate: Candidate data with vibe_report
        github_token: Optional GitHub token for fetching repos
        role_context: Optional role details (company, title, description, comp, investors, etc.)
        fit_analysis: Optional CrossChekk fit analysis (strengths, concerns, ai_summary)

    Returns:
        Dict with subject, body, and personalization notes
    """

    github_username = candidate.get('github_username', 'Unknown')
    name = _extract_first_name(candidate.get('name', ''), github_username)
    archetype = candidate.get('archetype', 'Developer')
    tier = candidate.get('tier', 'COMMON')
    vibe_report = candidate.get('vibe_report', {})

    # Extract key signals for personalization
    technical_signal = vibe_report.get('technical_signal', '')
    verified_skills = vibe_report.get('verified_skills', [])
    highlights = vibe_report.get('highlights', [])
    candidate_languages = candidate.get('github_languages', [])

    # Get positive highlights only (highlights are now strings, filter by keywords)
    if highlights and isinstance(highlights[0], str):
        # New format: array of strings
        positive_highlights = [h for h in highlights if not any(neg in h.lower() for neg in ['missing', 'no ', 'zero', 'lacking', 'limited', 'insufficient', 'dormant', 'weak', 'absent'])][:2]
    else:
        # Old format: array of objects (backwards compatibility)
        positive_highlights = [h for h in highlights if isinstance(h, dict) and h.get('type') == 'positive'][:2]

    # Fetch and select best 3 repos for personalization (role-aware when role_context provided)
    repos = fetch_repos_for_outreach(github_username, github_token)
    best_repos = select_best_repos(repos, candidate_languages, count=3, role_context=role_context)

    # Format repo names for subject and body (capitalize first letter for professional appearance)
    repo1_name = best_repos[0].get('name', 'project') if len(best_repos) >= 1 else 'GitHub work'
    repo2_name = best_repos[1].get('name', 'project') if len(best_repos) >= 2 else None
    repo3_name = best_repos[2].get('name', 'project') if len(best_repos) >= 3 else None
    repo1_name = repo1_name[0].upper() + repo1_name[1:] if repo1_name else repo1_name
    repo2_name = repo2_name[0].upper() + repo2_name[1:] if repo2_name else repo2_name
    repo3_name = repo3_name[0].upper() + repo3_name[1:] if repo3_name else repo3_name

    # Enrich top 2 repos with README + commits for specific observations
    repo1_context = enrich_repo_context(repo1_name, github_username, github_token) if repo1_name != 'GitHub work' else {}
    repo2_context = enrich_repo_context(repo2_name, github_username, github_token) if repo2_name else {}

    repo1_desc = (best_repos[0].get('description', '') or '') if len(best_repos) >= 1 else ''
    repo2_desc = (best_repos[1].get('description', '') or '') if len(best_repos) >= 2 else ''
    repo3_desc = (best_repos[2].get('description', '') or '') if len(best_repos) >= 3 else ''

    repo1_lang = (best_repos[0].get('language', '') or '') if len(best_repos) >= 1 else ''
    repo2_lang = (best_repos[1].get('language', '') or '') if len(best_repos) >= 2 else ''
    repo3_lang = (best_repos[2].get('language', '') or '') if len(best_repos) >= 3 else ''

    if repo3_name:
        repos_phrase = f"{repo1_name}, {repo2_name}, and {repo3_name}"
    elif repo2_name:
        repos_phrase = f"{repo1_name} and {repo2_name}"
    else:
        repos_phrase = repo1_name

    # Build repo detail strings for the prompt — include README + commits for depth
    def build_repo_detail(name, desc, lang, context):
        detail = name
        if desc:
            detail += f" — {desc}"
        if lang:
            detail += f" ({lang})"
        readme = context.get('readme_snippet', '')
        commits = context.get('recent_commits', [])
        if readme:
            detail += f"\n  README excerpt: {readme}"
        if commits:
            detail += f"\n  Recent commits: {', '.join(commits[:3])}"
        return detail

    repo1_detail = build_repo_detail(repo1_name, repo1_desc, repo1_lang, repo1_context) if repo1_name != 'GitHub work' else 'GitHub work'
    repo2_detail = build_repo_detail(repo2_name, repo2_desc, repo2_lang, repo2_context) if repo2_name else ""
    repo3_detail = ""
    if repo3_name:
        repo3_detail = f"{repo3_name}"
        if repo3_desc:
            repo3_detail += f" — {repo3_desc}"
        if repo3_lang:
            repo3_detail += f" ({repo3_lang})"

    # Build skills list for context (handle None values)
    skills_list = ", ".join([s.get('name') or 'Unknown' for s in verified_skills[:5] if isinstance(s, dict)])
    top_skills = [s.get('name') or 'engineering' for s in verified_skills[:2] if isinstance(s, dict)]
    if not top_skills:
        top_skills = ['engineering', 'full-stack']  # Fallback

    # Format highlights for prompt (handle both string and object formats)
    if positive_highlights and isinstance(positive_highlights[0], str):
        # New format: simple strings
        highlights_text = chr(10).join([f"- {h}" for h in positive_highlights])
    else:
        # Old format: objects with title/detail
        highlights_text = chr(10).join([f"- {h.get('title', '')}: {h.get('detail', '')}" for h in positive_highlights])

    # Build role-specific prompt if we have role context, otherwise generic warm-up
    if role_context and role_context.get('company'):
        rc = role_context
        company = rc.get('company', 'a startup')
        title = rc.get('title', 'Software Engineer')
        jd_text = rc.get('description', '')
        comp = rc.get('comp', '')
        equity = rc.get('equity', 'meaningful equity')
        location = rc.get('location', 'Flexible')
        stage = rc.get('stage', '')
        investors = rc.get('investors', [])
        role_stack = ', '.join(rc.get('tech_stack', []))

        # Build investors string
        investors_str = ', '.join(investors) if investors else ''

        # Build fit analysis context
        fit_context = ''
        if fit_analysis:
            strengths = fit_analysis.get('strengths', [])
            if strengths:
                fit_context = "\n\n## WHY THIS CANDIDATE FITS THIS ROLE (from CrossChekk analysis)\n"
                for s in strengths[:4]:
                    fit_context += f"- {s}\n"

        prompt = f"""Write a cold outreach email to a software engineer about a SPECIFIC ROLE. Study the examples below then write one for the candidate.

The structure: observation about their work + connect it to the specific role + why this role is worth their time. The hook is showing you understand BOTH their background AND the role well enough to see the connection. NEVER reveal the company name. Keep them hungry for more info.

## EXAMPLE 1

Candidate: Sarah
Repo 1: plotwise — data viz library (Python)
Role: Data Engineer at a Series A company (backed by a16z). Building data pipelines for clinical trial data. Paying up to $220K + significant equity. NYC hybrid.

Subject: plotwise + healthcare data pipelines
Body:
Hi Sarah,

Plotwise caught my eye, specifically the streaming mode for live data. The way you handle 10k+ datapoints without jank tells me you think about data pipeline performance the way most people think about UI.

I'm working with a Series A company (backed by a16z) on a Data Engineer role. They're building real-time pipelines for clinical trial data, paying up to $220K + significant equity. Given what you built with Plotwise, the pipeline architecture challenges here would be right in your wheelhouse.

Would you be open to hearing more about it?

## EXAMPLE 2

Candidate: Nick
Repo 1: python-lambda — AWS Lambda deployment toolkit (Python)
Role: Software Engineer at a seed stage company (backed by CRV, founders of MongoDB & KAYAK). Building AI-powered financial pipelines for healthcare. Paying up to $275K + significant equity. NYC on-site.
CrossChekk strengths: Built HIPAA-compliant data pipelines at Big Leap Health, distributed email ingestion pipeline at OneReceipt, security engineering at Twitter.

Subject: python-lambda + healthcare pipelines
Body:
Hi Nick,

Python-lambda caught my eye, specifically how you handle the async wait patterns for function updates. Building deployment tooling for serverless shows you think about infrastructure at the system level, not just application code.

I'm working with a seed stage company backed by CRV and the founders of MongoDB and KAYAK on a Software Engineer role. They're building AI-powered financial pipelines for healthcare practices, paying up to $275K + significant equity. Given your experience architecting HIPAA-compliant data pipelines at Big Leap Health and distributed systems at OneReceipt, you'd be solving similar data integration challenges at scale.

Would you be open to hearing more about it?

## NOW WRITE ONE FOR THIS CANDIDATE AND ROLE

**Name**: {name}
**Archetype**: {archetype}
**Skills**: {skills_list}
**Repo 1**: {repo1_detail}
{"**Repo 2**: " + repo2_detail if repo2_detail else ""}

**Role**: {title}
{f"**Stage**: {stage}" if stage else ""}
{f"**Backed by**: {investors_str}" if investors_str else ""}
{f"**Comp**: {comp}" if comp else ""}{f" + {equity} equity" if equity else ""}
{f"**Location**: {location}" if location else ""}
{f"**Tech Stack**: {role_stack}" if role_stack else ""}
**JD**: {jd_text[:2000] if jd_text else "Not available"}
{fit_context}
## RULES
- Subject: all lowercase, max 6 words. Reference repo + the problem domain. e.g. "[repo] + healthcare pipelines" or "[repo] caught my eye"
- 3-4 paragraphs, ~100-150 words total.
- P1: "Hi [name],"
- P2: Reference repo 1 with ONE specific detail. Connect it naturally to why this particular role would be interesting for them.
- P3: Pitch the role. NEVER mention the company name. Instead say "a [stage] company backed by [investors]". Describe what they're building (from the JD), the comp (always lead with the ceiling, e.g. "paying up to $275K + significant equity", never show a range), and connect the candidate's background to what the role needs. Use specific details from the CrossChekk analysis or their repos/resume to explain why THEY specifically would be a fit. This is the sell paragraph, make the connection between their experience and the role concrete and specific.
- P4: Short CTA: "Would you be open to hearing more about it?" or "Interested in learning more?"
- CRITICAL: NEVER reveal the company name. Say "a seed stage company", "a Series A company", etc. This creates intrigue and keeps them wanting to learn more.
- LOCATION REQUIREMENT: If the role has a location requirement (onsite, hybrid, or specific cities), you MUST naturally mention it in the pitch paragraph. For example: "paying up to $275K + significant equity, based in NYC (3 days onsite)" or "hybrid in SF". Candidates need to know upfront if they'll need to be in a specific city — do NOT omit this. If the location is "Remote" or "Flexible", you can skip it.
- No em dashes. No generic filler. No "hope you're doing well."
- NEVER say "I place engineers with YC startups" or any generic recruiter pitch. This is about ONE specific role.
- If the CrossChekk analysis mentions specific strengths, use them to make the connection concrete. Reference specific companies, projects, and skills from their background.

Return as JSON:
{{
  "subject": "...",
  "body": "Hi {name},\\n\\n...\\n\\n...\\n\\n...",
  "personalization_notes": ["...", "..."],
  "format_used": "role-specific"
}}
"""
    else:
        prompt = f"""Write a cold outreach email to a software engineer. Study the examples below then write one for the candidate.

The structure: observation + question + "I ask because [opportunity]". The question is the hook. It should be something they actually want to answer about their own project, and it should connect naturally to the opportunity. NOT a compliment followed by a pitch.

## EXAMPLE 1

Candidate: Sarah
Repo 1: plotwise — data viz library (Python). README: "Renders 10k+ datapoints with zero jank using WebGL." Commits: "add streaming mode for live data", "fix axis label overlap on mobile"
Repo 2: dashgen — dashboard generator (React)
Skills: Python, D3.js, React

Subject: Saw Plotwise, Had a Thought
Body:
Hi Sarah,

Plotwise caught my eye, the streaming mode specifically. Are you building this as a standalone tool or does it plug into something bigger? Between that and Dashgen it seems like you're working toward a full data platform.

I ask because engineers who build their own tools from scratch instead of gluing libraries together are exactly what early-stage teams need. I place engineers with YC, a16z, and Sequoia-backed startups (Seed to Series A), $150-200K base + meaningful equity, building from scratch with founders.

Would you be open to exploring early-stage roles?

## EXAMPLE 2

Candidate: Marcus
Repo 1: tuneflow — music production app (TypeScript). README: "Real-time audio processing in the browser using Web Audio API." Commits: "add MIDI import", "fix latency on bluetooth headphones"
Repo 2: beatmatch — BPM detection tool (TypeScript)
Skills: TypeScript, React Native

Subject: Re: Tuneflow
Body:
Hi Marcus,

Tuneflow and Beatmatch, you keep building in audio. The bluetooth latency fix tells me you actually use this yourself. Are you building toward a full audio platform, or is each tool solving a different itch?

I ask because engineers who build for a domain they genuinely care about are rare, and that's exactly what early-stage teams need. I place engineers with YC, a16z, and Sequoia-backed startups (Seed to Series A), $150-200K base + meaningful equity.

Would you be open to exploring early-stage roles?

## NOW WRITE ONE FOR THIS CANDIDATE

**Name**: {name}
**Archetype**: {archetype}
**Skills**: {skills_list}
**Repo 1**: {repo1_detail}
{"**Repo 2**: " + repo2_detail if repo2_detail else ""}
{"**Repo 3 (only if it genuinely adds)**: " + repo3_detail if repo3_detail else ""}

## RULES
- Subject: all lowercase, max 5 words, repo 1 only. Pick from: "saw [repo], had a thought" / "re: [repo]" / "is [repo] still active?"
- 4 paragraphs, ~100-140 words total.
- P1: "Hi [name],"
- P2: Reference repo 1 with ONE specific detail from README/commits. Then ask a GENUINE QUESTION about their project that they'd actually want to answer. Weave in repo 2 (optionally repo 3) naturally. The question should connect to what kind of engineer they are. IMPORTANT: If the question offers two options, both must feel equally ambitious. Never frame one option as "just practicing" or "honing skills" vs a bigger vision. Max 3 sentences.
- P3: "I ask because [bridge about their TRANSFERABLE QUALITY, not their specific domain]. I place engineers with YC, a16z, and Sequoia-backed startups (Seed to Series A), $150-200K base + meaningful equity." The bridge must describe a quality ANY startup would want (e.g. "build their own tools", "ship independently", "care deeply about a domain"). NEVER reference the candidate's specific industry/domain in the bridge (e.g. "improve how we evaluate talent" or "build audio tools" — these only apply to one type of startup). Max 15 words before "are exactly". One clean clause, never stacked. One flowing sentence for the opportunity, never two choppy fragments.
- P4: CTA — "Would you be open to exploring early-stage roles?" Keep it as one short sentence. This needs to be a clear yes/no ask that sets up a screening call.
- No em dashes (—). No generic filler that could apply to any engineer.

Return as JSON:
{{
  "subject": "...",
  "body": "Hi {name},\\n\\n...\\n\\n...\\n\\n...",
  "personalization_notes": ["...", "..."],
  "format_used": "example-based"
}}
"""

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
                        'content': 'You write recruiting emails that sound like a curious engineer, not a recruiter. You reference ONE specific detail from a repo to prove you looked, then ask a genuine question the person would actually want to answer. The question is the hook, not a compliment. The opportunity comes after, as context for why you asked. You close casually, no pressure. Match the examples exactly.'
                    },
                    {'role': 'user', 'content': prompt}
                ],
                'response_format': {'type': 'json_object'},
                'temperature': 0.7  # Higher creativity for writing
            },
            timeout=30
        )

        if not response.ok:
            logger.error("DeepSeek API error: %d", response.status_code)
            return generate_fallback_template(candidate, github_token, role_context)

        data = response.json()
        content = data['choices'][0]['message']['content']

        # Parse JSON response
        try:
            outreach = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if '```' in content:
                content = content.replace('```json', '').replace('```', '').strip()
            outreach = json.loads(content)

        # Validate subject line - should be short and personalized
        subject = outreach.get('subject', '')
        if not subject or len(subject) > 60 or len(subject) < 5:
            subject = f"Saw {repo1_name}, Had a Thought"
            logger.info("Adjusted subject to fallback (was %d chars)", len(outreach.get('subject', '')))

        # Title case subject (capitalize major words, preserve repo name casing)
        subject = _title_case_subject(subject)

        # Remove em dashes from subject too
        subject = subject.replace(' — ', ', ')

        # Detect and fix descriptive subjects — DeepSeek keeps ignoring curiosity gap rules
        # Descriptive subjects summarize the email instead of creating a curiosity gap
        import re
        descriptive_patterns = [
            r"'s\s+\w+\s+(approach|architecture|detection|implementation|system|design|setup|structure|stack|framework|logic|patterns?|handling|integration|workflow)",  # "vibechekk's typescript approach"
            r"'s\s+(approach|architecture|detection|implementation|system|design|setup|structure|stack|framework|logic|patterns?|handling|integration|workflow)$",  # "vibechekk's architecture"
            r"'s\s+\w+\s+\w+$",  # any "'s X Y" pattern — almost always descriptive (e.g. "vibechekk's detection logic")
            r"(approach|architecture|detection|implementation|design|setup)\s+to\b",  # "approach to X"
            r"^(about|regarding)\s+\w+'s",  # "about vibechekk's"
            r"\w+\s+(archetype|classification|analysis|processing|detection)\b",  # "vibechekk archetype detection"
        ]
        is_descriptive = any(re.search(p, subject, re.IGNORECASE) for p in descriptive_patterns)

        # Also check: if subject has 7+ words it's probably descriptive (too long)
        if len(subject.split()) >= 7:
            is_descriptive = True

        if is_descriptive:
            # Pick a curiosity-gap replacement that works with ANY body about the repo.
            # "reminded me of something" is excluded because it requires the body to
            # explain WHAT it reminded them of — and we can't modify the body here.
            # These subjects are universally compatible with any repo-focused body.
            import random
            curiosity_subjects = [
                f"Re: {repo1_name}",                           # feels like ongoing thread, works with any body
                f"Saw {repo1_name}, Had a Thought",            # works with any repo-focused body
                f"Is {repo1_name} Still Active?",              # implies something, works with any body
            ]
            subject = random.choice(curiosity_subjects)
            logger.info("Replaced descriptive subject with curiosity gap: '%s'", subject)

        # Post-process body to enforce critical rules DeepSeek often ignores
        body = outreach.get('body', '')

        # Fix greeting: ensure it uses the clean first name
        import re
        body = re.sub(r'^Hi\s+\S+', f'Hi {name}', body)

        # Fix comp figures: ensure "base" is always present
        body = body.replace('$150-200K + meaningful', '$150-200K base + meaningful')
        body = body.replace('$150-200K + 0.5', '$150-200K base + 0.5')
        body = body.replace('$150K-200K + ', '$150-200K base + ')  # Handle variant formatting

        # Remove overly specific product types
        body = body.replace('mobile products', 'products')
        body = body.replace('web products', 'products')
        body = body.replace('mobile product', 'product')
        body = body.replace('web product', 'product')
        body = body.replace('mobile apps', 'products')
        body = body.replace('mobile app', 'product')
        body = body.replace('web apps', 'products')
        body = body.replace('web app', 'product')
        body = body.replace('SaaS products', 'products')
        body = body.replace('SaaS product', 'product')
        body = body.replace('shape the mobile ', 'shape the ')
        body = body.replace('shape mobile ', 'shape ')

        # Note: recruiter-speak buzzwords are handled by generic_replacements dict below

        # Remove em dashes (major AI-generated content tell)
        # Replace with period and capitalize next word
        import re as re_mod
        def replace_em_dash(match):
            next_char = match.group(1)
            return '. ' + next_char.upper()
        body = re_mod.sub(r' — ([a-zA-Z])', replace_em_dash, body)
        body = body.replace(' — ', '. ')  # catch any remaining

        # Strip generic buzzword phrases — replace with nothing or simpler alternatives
        generic_replacements = {
            'solve real problems': 'build things that matter',
            'solves a real problem': 'matters',
            'solving real problems': 'building things that matter',
            'practical solutions': 'things that work',
            'builder mindset': 'approach',
            'build with purpose, not just features': 'build things that matter',
            'build with purpose': 'build things that matter',
            'not just another tech demo': '',
            'clean separation of concerns': 'solid structure',
            'separation of concerns': 'structure',
            'clean architecture': 'structure',
            'solid architecture': 'solid structure',
            'architectural thinking': 'approach',
            'design thinking': 'approach',
            'clean code practices': 'approach',
            'solid engineering': 'engineering',
            'strong design thinking': 'approach',
            'well-structured codebase': 'codebase',
            'scalable approach': 'approach',
            'clean codebase': 'codebase',
            'solid design patterns': 'patterns',
            'solid instincts': 'eye for detail',
            'modern architecture': 'good taste',
            'modern tech stack': 'good taste',
            'production-ready ': '',
            'production ready ': '',
            'cutting-edge ': '',
            'best practices': 'good instincts',
        }
        body_lower = body.lower()
        for phrase, replacement in generic_replacements.items():
            if phrase in body_lower:
                # Case-insensitive replacement
                import re as re_ci
                body = re_ci.sub(re.escape(phrase), replacement, body, flags=re.IGNORECASE)
                logger.info("Replaced generic phrase '%s' with '%s'", phrase, replacement)

        # Clean up any double spaces or empty commas from replacements
        body = re.sub(r'  +', ' ', body)
        body = re.sub(r' ,', ',', body)
        body = re.sub(r',\s*\.', '.', body)

        # Merge choppy "I work with..." + "$150-200K" into one sentence
        body = re.sub(
            r'I work with (YC, a16z, and Sequoia-backed startups \(Seed to Series A\))\.\s*\$',
            r'I place engineers with \1, $',
            body
        )
        body = re.sub(
            r'I work with (VC-backed startups \(Seed to Series A, YC, a16z, Sequoia\))\.\s*\$',
            r'I place engineers with YC, a16z, and Sequoia-backed startups (Seed to Series A), $',
            body
        )

        # Strip activity/metrics phrases from bridge — these are "you code a lot" in disguise
        activity_patterns = [
            (r'who maintain high activity across multiple repos', 'who ship their own products, not just client work'),
            (r'who maintain high activity', 'who ship their own products'),
            (r'with high activity across', 'who ship across'),
            (r'active across multiple repos', 'shipping their own tools'),
            (r'maintain multiple repos', 'ship their own tools'),
            (r'active across repos', 'shipping their own tools'),
        ]
        for pattern, replacement in activity_patterns:
            body = re.sub(pattern, replacement, body, flags=re.IGNORECASE)

        # Strip explain-back patterns — "a tool that [does X]", "which [does/is] X"
        explain_back_patterns = [
            r'wondered if you (considered|thought about)',
            r'have you (considered|thought about)',
            r'instead of (regex|REST|SQL|MongoDB)',
            r'you might (want to|consider)',
            r'I was looking at .+ and wondering if',
            r'wondering if you built it',
            r'Together,? they show',
            r'which seems like',
        ]
        for pattern in explain_back_patterns:
            if re.search(pattern, body, re.IGNORECASE):
                logger.warning("Detected explain-back/advice pattern in body: '%s'", pattern)

        # Fix broken P3 bridges — catch stacked clauses that don't parse
        # e.g. "engineers who build tools to ship things that matter they understand deeply"
        # The "they [verb] [word]" dangling after a clause is always a run-on — strip it
        body = re.sub(
            r'(engineers who .+?) they \w+ \w+?( are exactly)',
            r'\1\2',
            body,
            flags=re.IGNORECASE
        )

        # Enforce startup specifics — if body says "VC-backed startups" without names, add them
        if 'VC-backed startups' in body and 'YC' not in body and 'a16z' not in body:
            body = body.replace('VC-backed startups', 'VC-backed startups (Seed to Series A, YC, a16z, Sequoia, and others)')
        if 'early-stage startups' in body and 'YC' not in body and 'a16z' not in body:
            body = body.replace('early-stage startups', 'early-stage startups (YC, a16z, Sequoia-backed, and others)')

        logger.info("Generated personalized template for %s", github_username)
        return {
            'success': True,
            'subject': subject,
            'body': body,
            'personalization_notes': outreach.get('personalization_notes', []),
            'candidate_name': name,
            'candidate_github': github_username,
            'repos_referenced': [r for r in [repo1_name, repo2_name, repo3_name] if r]
        }

    except Exception as e:
        logger.error("Generation failed: %s", e)
        return generate_fallback_template(candidate, github_token, role_context, best_repos)


def generate_fallback_template(
    candidate: Dict,
    github_token: Optional[str] = None,
    role_context: Optional[Dict] = None,
    best_repos: Optional[List[Dict]] = None
) -> Dict:
    """
    Generate basic warm-up template if DeepSeek fails.
    Uses same structure as AI-generated template.
    """
    github_username = candidate.get('github_username', 'Unknown')
    name = _extract_first_name(candidate.get('name', ''), github_username)
    vibe_report = candidate.get('vibe_report', {})
    candidate_languages = candidate.get('github_languages', [])

    # Fetch and select best repos if not provided
    if not best_repos:
        repos = fetch_repos_for_outreach(github_username, github_token)
        best_repos = select_best_repos(repos, candidate_languages, count=3)

    # Format repo names (capitalize first letter for professional appearance)
    repo1_name = best_repos[0].get('name', 'project') if len(best_repos) >= 1 else 'GitHub work'
    repo2_name = best_repos[1].get('name', 'project') if len(best_repos) >= 2 else None
    repo3_name = best_repos[2].get('name', 'project') if len(best_repos) >= 3 else None
    repo1_name = repo1_name[0].upper() + repo1_name[1:] if repo1_name else repo1_name
    repo2_name = repo2_name[0].upper() + repo2_name[1:] if repo2_name else repo2_name
    repo3_name = repo3_name[0].upper() + repo3_name[1:] if repo3_name else repo3_name

    repo1_desc = (best_repos[0].get('description') or '') if len(best_repos) >= 1 else ''
    repo2_desc = (best_repos[1].get('description') or '') if len(best_repos) >= 2 else ''

    if repo3_name:
        repos_phrase = f"{repo1_name}, {repo2_name}, and {repo3_name}"
    elif repo2_name:
        repos_phrase = f"{repo1_name} and {repo2_name}"
    else:
        repos_phrase = repo1_name

    # Extract skills (handle None values defensively)
    verified_skills = vibe_report.get('verified_skills', [])
    skill1 = (verified_skills[0].get('name') or 'engineering') if len(verified_skills) > 0 and isinstance(verified_skills[0], dict) else 'engineering'
    skill2 = (verified_skills[1].get('name') or 'full-stack') if len(verified_skills) > 1 and isinstance(verified_skills[1], dict) else 'full-stack'

    # Build observation + question from repo info
    if repo2_name:
        technical_obs = f"{repo1_name} caught my eye. Between that and {repo2_name}, you keep building your own tools. Is {repo1_name} a side project or something you'd want to go full-time on?"
    else:
        technical_obs = f"{repo1_name} caught my eye. Is this a side project or something you'd want to go full-time on?"

    # Subject — curiosity gap, leads with repo1
    subject = f"Saw {repo1_name}, Had a Thought"

    # Body — question-based structure
    body = f"""Hi {name},

{technical_obs}

I ask because engineers who build their own tools are exactly who early-stage teams need. I place engineers with YC, a16z, and Sequoia-backed startups (Seed to Series A), $150-200K base + meaningful equity, building from scratch with founders.

Would you be open to exploring early-stage roles?"""

    repos_list = [r for r in [repo1_name, repo2_name, repo3_name] if r]
    return {
        'success': True,
        'subject': subject,
        'body': body,
        'personalization_notes': [
            'Fallback template - DeepSeek generation failed',
            f'Referenced repos: {", ".join(repos_list)}',
            f'Skills mentioned: {skill1}, {skill2}'
        ],
        'candidate_name': name,
        'candidate_github': github_username,
        'repos_referenced': repos_list
    }


def generate_role_pitch(
    api_key: str,
    candidate: Dict,
    role: Dict,
    email_history: Dict,
    fit_analysis: Optional[Dict] = None,
    candidate_opened: bool = False,
) -> Dict:
    """
    Generate a role-specific email for a candidate we've already contacted.

    Two modes based on whether the candidate opened the prior email:
    - OPENED (candidate_opened=True): Follow-up in the same email chain (Re: subject).
      References prior outreach, pitches the new JD role.
    - NOT OPENED (candidate_opened=False): Fresh JD-specific cold email in a NEW chain.
      They never saw the first email, so start fresh with JD context. New subject line.

    Args:
        api_key: DeepSeek API key
        candidate: Candidate data (name, github_username, archetype, tech_stack, etc.)
        role: Role data (title, company, jd_text, tech_stack, comp, equity, location, stage, investors)
        email_history: Prior thread (outreach_subject, outreach_body, reply_text, followup_body)
        fit_analysis: Optional CrossChekk fit analysis (strengths, concerns, ai_summary)
        candidate_opened: Whether the candidate opened the prior email

    Returns:
        Dict with subject, body
    """
    name = _extract_first_name(candidate.get('name', ''), candidate.get('github_username', ''))
    github_username = candidate.get('github_username', '')

    # Build the prior thread summary for context
    prior_subject = email_history.get('outreach_subject', '')
    prior_body = email_history.get('outreach_body', '')
    reply_text = email_history.get('reply_text', '')
    followup_body = email_history.get('followup_body', '')

    thread_parts = []
    if prior_body:
        thread_parts.append(f"YOUR ORIGINAL EMAIL:\nSubject: {prior_subject}\n{prior_body}")
    if reply_text:
        thread_parts.append(f"{name.upper()}'S REPLY:\n{reply_text}")
    if followup_body:
        thread_parts.append(f"YOUR FOLLOW-UP:\n{followup_body}")

    thread_summary = "\n\n---\n\n".join(thread_parts) if thread_parts else "No prior emails."

    # Build role details
    role_title = role.get('title', 'Software Engineer')
    jd_text = role.get('jd_text', '')
    role_stack = ', '.join(role.get('tech_stack', [])) or 'not specified'
    comp_str = role.get('comp', '')
    equity_str = role.get('equity', 'significant equity')
    location = role.get('location', 'Remote')
    stage = role.get('stage', '')
    investors = role.get('investors', [])
    investors_str = ', '.join(investors) if investors else ''

    # Build fit analysis context
    fit_context = ''
    if fit_analysis:
        strengths = fit_analysis.get('strengths', [])
        if strengths:
            fit_context = "\n\n## WHY THIS CANDIDATE FITS THIS ROLE (from CrossChekk analysis)\n"
            for s in strengths[:4]:
                fit_context += f"- {s}\n"

    # Candidate context
    candidate_stack = ', '.join(candidate.get('tech_stack', [])[:8]) or 'not specified'
    archetype = candidate.get('archetype', '')
    tier = candidate.get('tier', '')
    raw_notes = candidate.get('linkedin_text', '')
    # Support JSON array of note chunks or legacy plain text
    candidate_notes = ''
    if raw_notes:
        try:
            parsed = json.loads(raw_notes)
            if isinstance(parsed, list):
                candidate_notes = '\n\n'.join(str(c) for c in parsed if c)
            else:
                candidate_notes = raw_notes
        except (json.JSONDecodeError, TypeError):
            candidate_notes = raw_notes
    resume_text = candidate.get('resume_text', '')

    # Build extended profile context from notes/resume
    profile_context = ''
    if candidate_notes:
        notes_excerpt = candidate_notes[:2000]
        profile_context += f"\n\n### Candidate Notes (LinkedIn, background, context):\n{notes_excerpt}"
    if resume_text and not candidate_notes:
        res_excerpt = resume_text[:2000]
        profile_context += f"\n\n### Resume:\n{res_excerpt}"

    # Truncate JD to keep prompt reasonable
    jd_excerpt = jd_text[:2000] if jd_text else 'No JD available.'

    # Build prompt based on three scenarios:
    # 1. Opened + replied → follow-up in same chain, acknowledge reply
    # 2. Opened but no reply → follow-up in same chain, re-engage with JD role
    # 3. Not opened → completely fresh JD-specific cold email, new subject line
    if reply_text:
        situation_rules = """- They replied to our previous email. Acknowledge their response naturally and build on it.
- Since they engaged, be direct about pitching this specific role as something you think fits.
- Reference what they said in their reply if relevant to this role."""
        subject_rule = '- Subject: "Re: [original subject]" to keep the thread going.'
        system_msg = 'You write recruiting follow-up emails. You are continuing a conversation with someone you already emailed. You pitch a specific role that matches their background. You NEVER reveal the company name. You are direct, specific about the role, and connect their work to the opportunity. No generic recruiting language.'
    elif candidate_opened:
        situation_rules = """- They opened our previous email but never replied. Don't be pushy about it.
- The new role is your reason for following up. Lead with that.
- Briefly reference your previous email (e.g. "I reached out a while back about your work on [repo]") then pivot to the new role.
- The tone should feel like: "I have something specific now that I think is worth your time."
- Do NOT repeat the same pitch structure as the original email. This should feel different and more targeted."""
        subject_rule = '- Subject: "Re: [original subject]" to keep the thread going.'
        system_msg = 'You write recruiting follow-up emails. You are continuing a conversation with someone you already emailed. You pitch a specific role that matches their background. You NEVER reveal the company name. You are direct, specific about the role, and connect their work to the opportunity. No generic recruiting language.'
    else:
        # Not opened — fresh start, new email chain, JD-specific cold outreach
        situation_rules = """- They were previously emailed but never opened it. They have NO context about you or Chekk.
- This is a FRESH first impression. Do NOT reference any previous email. Do NOT say "following up" or "I reached out before."
- Treat this like a cold outreach but with full JD context. Lead with a specific observation about their work (repos, LinkedIn, resume) and connect it to the role.
- The structure should be: specific observation about their work → pitch the role → connect their background to what the role needs → CTA."""
        subject_rule = '- Subject: a fresh subject line referencing their most notable repo or work + the theme of the role (e.g. "Plotwise + Real-Time Pipelines"). Do NOT use "Re:" since this is a new email chain.'
        system_msg = 'You write personalized cold recruiting emails. You pitch a specific role that matches the candidate\'s background. You NEVER reveal the company name. You lead with a genuine technical observation about their work, then pitch the role. No generic recruiting language.'

    if candidate_opened or reply_text:
        # Follow-up: show prior thread and examples
        prompt = f"""Write a follow-up email pitching a SPECIFIC ROLE to a candidate we've already reached out to. Study the examples below then write one.

## EXAMPLE (opened but no reply to previous outreach)

Prior email subject: "Saw Plotwise, Had a Thought"
Prior email: Generic warm-up about their repos and early-stage roles.
Role: Data Engineer at a Series A company (backed by a16z). Building real-time pipelines for clinical trial data. Paying up to $220K + significant equity. NYC hybrid.

Subject: Re: Saw Plotwise, Had a Thought
Body:
Hi Sarah,

Following up on my last note. I've got something specific now that I think is worth your time.

I'm working with a Series A company backed by a16z on a Data Engineer role. They're building real-time pipelines for clinical trial data, paying up to $220K + significant equity. Given what you built with Plotwise, specifically the streaming mode for live data, the pipeline architecture challenges here would be right in your wheelhouse.

Interested?

## EXAMPLE (replied to previous outreach)

Prior email: Role-specific outreach about python-lambda and a healthcare pipeline role.
Reply: "Sure, happy to hear more. I'm currently at AWS but open to exploring."
Role: Founding Engineer at a seed stage company (backed by Reid Hoffman, Vinod Khosla). Building justice tech platform. Paying up to $200K + significant equity.

Subject: Re: Python-lambda + Healthcare Pipelines
Body:
Hi Nick,

Great to hear you're open to exploring. This one's a bit different from the healthcare pipeline role but I think it's even more interesting for your background.

I'm working with a seed stage company backed by Reid Hoffman and Vinod Khosla on a Founding Engineer role. They're building an all-in-one platform to break the cycle of poverty and incarceration, paying up to $200K + significant equity. Your experience leading the ECS module for AWS CDK from 0 to 1 is exactly the kind of infrastructure ownership they need at this stage.

Interested?

## PRIOR EMAIL THREAD
{thread_summary}

## THE ROLE TO PITCH
- Title: {role_title}
{f"- Stage: {stage}" if stage else ""}
{f"- Backed by: {investors_str}" if investors_str else ""}
- Tech Stack: {role_stack}
{f"- Comp: {comp_str}" if comp_str else ""}{f" + {equity_str}" if equity_str else ""}
{f"- Location: {location}" if location else ""}
- JD: {jd_excerpt}
{fit_context}

## CANDIDATE CONTEXT
- Name: {name}
- Tech stack: {candidate_stack}
- Archetype: {archetype}
- Tier: {tier}{profile_context}

## RULES
{situation_rules}
- CRITICAL: NEVER reveal the company name. Say "a {stage + ' ' if stage else ''}company{' backed by ' + investors_str if investors_str else ''}" instead. This creates intrigue.
- Pitch the role: what they're building (from the JD), the comp (always lead with the ceiling, e.g. "paying up to $275K + significant equity"), and connect the candidate's background to what the role needs.
- Use specific details from CrossChekk analysis, their repos, LinkedIn, or resume to explain why THEY specifically fit this role. Be concrete.
- {"If candidate notes or resume context is provided, use specific details from their background (job titles, companies, projects) to explain the fit." if (candidate_notes or resume_text) else ""}
- Keep it 80-130 words. 3-4 short paragraphs.
{subject_rule}
- No em dashes. No generic filler. No "hope you're doing well."
- End with a single word CTA: "Interested?" — nothing more.
- Tone: casual, direct, like a quick follow-up from someone they've already talked to.

Return as JSON:
{{
  "subject": "Re: ...",
  "body": "Hi {name},\\n\\n...\\n\\nInterested?"
}}
"""
    else:
        # Not opened — fresh JD-specific cold email, no mention of prior outreach
        prompt = f"""Write a personalized cold outreach email pitching a SPECIFIC ROLE to an engineer. This is their first impression of you. Study the examples below then write one.

## EXAMPLE 1

Role: Data Engineer at a Series A company (backed by a16z). Building real-time pipelines for clinical trial data. Paying up to $220K + significant equity. NYC hybrid.

Subject: Plotwise + Real-Time Pipelines
Body:
Hi Sarah,

Plotwise caught my eye, specifically the streaming mode for processing live data feeds. Building reliable real-time data pipelines is hard, and you clearly understand the tradeoffs between throughput and latency at that level.

I'm working with a Series A company backed by a16z on a Data Engineer role. They're building real-time pipelines for clinical trial data, paying up to $220K + significant equity. The pipeline architecture challenges here would be right in your wheelhouse given what you built with Plotwise.

Interested?

## EXAMPLE 2

Role: Founding Engineer at a seed stage company (backed by Reid Hoffman, Vinod Khosla). Building justice tech platform. Paying up to $200K + significant equity.

Subject: Amazon-ecs-local-container-endpoints + 0-to-1 Infrastructure
Body:
Hi Hsing-hui,

Amazon-ecs-local-container-endpoints caught my eye, specifically how you built local versions of ECS Task IAM Roles and Metadata endpoints. Creating tooling that helps developers test applications locally before deploying to ECS/Fargate shows you think about infrastructure at the system level.

I'm working with a seed stage company backed by Reid Hoffman and Vinod Khosla on a Founding Engineer role. They're building a platform from scratch, paying up to $200K + significant equity. Your experience leading the ECS module for AWS CDK from 0 to 1 is exactly the kind of infrastructure ownership they need.

Interested?

## THE ROLE TO PITCH
- Title: {role_title}
{f"- Stage: {stage}" if stage else ""}
{f"- Backed by: {investors_str}" if investors_str else ""}
- Tech Stack: {role_stack}
{f"- Comp: {comp_str}" if comp_str else ""}{f" + {equity_str}" if equity_str else ""}
{f"- Location: {location}" if location else ""}
- JD: {jd_excerpt}
{fit_context}

## CANDIDATE CONTEXT
- Name: {name}
- GitHub: {github_username}
- Tech stack: {candidate_stack}
- Archetype: {archetype}
- Tier: {tier}{profile_context}

## RULES
{situation_rules}
- CRITICAL: NEVER reveal the company name. Say "a {stage + ' ' if stage else ''}company{' backed by ' + investors_str if investors_str else ''}" instead. This creates intrigue.
- Pitch the role: what they're building (from the JD), the comp (always lead with the ceiling, e.g. "paying up to $275K + significant equity"), and connect the candidate's background to what the role needs.
- Use specific details from CrossChekk analysis, their repos, LinkedIn, or resume to explain why THEY specifically fit this role. Be concrete.
- {"If candidate notes or resume context is provided, use specific details from their background (job titles, companies, projects) to explain the fit." if (candidate_notes or resume_text) else ""}
- Keep it 80-130 words. 3-4 short paragraphs.
{subject_rule}
- No em dashes. No generic filler. No "hope you're doing well."
- End with a single word CTA: "Interested?" — nothing more.
- Tone: casual, direct, concise. You are a recruiter reaching out cold.

Return as JSON:
{{
  "subject": "[repo or work reference] + [role theme]",
  "body": "Hi {name},\\n\\n...\\n\\nInterested?"
}}
"""

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
                        'content': system_msg
                    },
                    {'role': 'user', 'content': prompt}
                ],
                'response_format': {'type': 'json_object'},
                'temperature': 0.7
            },
            timeout=30
        )

        if not response.ok:
            logger.error("DeepSeek API error for role pitch: %d", response.status_code)
            return _fallback_role_pitch(name, prior_subject, role_title, stage, investors_str, comp_str, equity_str, reply_text, candidate_opened)

        data = response.json()
        content = data['choices'][0]['message']['content']

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            if '```' in content:
                content = content.replace('```json', '').replace('```', '').strip()
            result = json.loads(content)

        if candidate_opened or reply_text:
            subject = result.get('subject', f'Re: {prior_subject}')
        else:
            # Fresh cold email — don't default to Re:
            subject = result.get('subject', '')
            # Strip "Re:" if DeepSeek added it anyway for the not-opened case
            if subject.startswith('Re: ') or subject.startswith('RE: '):
                subject = subject[4:]
        body = result.get('body', '')

        # Fix greeting
        import re
        body = re.sub(r'^Hi\s+\S+', f'Hi {name}', body)

        # Remove em dashes
        def replace_em_dash(match):
            next_char = match.group(1)
            return '. ' + next_char.upper()
        body = re.sub(r' — ([a-zA-Z])', replace_em_dash, body)
        body = body.replace(' — ', '. ')

        # Strip company name if DeepSeek leaked it
        company_name = role.get('company', '')
        if company_name and company_name in body:
            # Replace with stage description
            stage_desc = f"a {stage + ' ' if stage else ''}company"
            if investors_str:
                stage_desc += f" backed by {investors_str}"
            body = body.replace(company_name, stage_desc)
            logger.warning("Stripped leaked company name '%s' from role pitch", company_name)

        logger.info("Generated role pitch for %s -> %s", github_username, role_title)
        return {
            'success': True,
            'subject': subject,
            'body': body,
        }

    except Exception as e:
        logger.error("Role pitch generation failed: %s", e)
        return _fallback_role_pitch(name, prior_subject, role_title, stage, investors_str, comp_str, equity_str, reply_text, candidate_opened)


def _fallback_role_pitch(
    name: str,
    prior_subject: str,
    role_title: str,
    stage: str,
    investors_str: str,
    comp_str: str,
    equity_str: str,
    reply_text: str,
    candidate_opened: bool = False,
) -> Dict:
    """Fallback role pitch if DeepSeek fails."""
    company_desc = f"a {stage + ' ' if stage else ''}company"
    if investors_str:
        company_desc += f" backed by {investors_str}"

    comp_part = f", {comp_str}" if comp_str else ""
    equity_part = f" + {equity_str}" if equity_str else ""

    if reply_text:
        opener = "Thanks for getting back to me. I wanted to follow up with something specific."
        subject = f'Re: {prior_subject}'
    elif candidate_opened:
        opener = "Following up on my last note. I've got something specific now that I think is worth your time."
        subject = f'Re: {prior_subject}'
    else:
        opener = f"Your work caught my eye, and I think it's a strong fit for what I'm seeing in the market."
        subject = f'{role_title} Opportunity'

    body = f"""Hi {name},

{opener}

I'm working with {company_desc} on a {role_title} role{comp_part}{equity_part}. Based on your background, this looks like a strong fit.

Interested?"""

    return {
        'success': True,
        'subject': subject,
        'body': body,
    }
