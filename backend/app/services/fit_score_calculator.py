"""
FitScore Calculator

Compares candidates against job requirements to generate a FitScore and recommendation.

Scoring Rubric:
- 90-100: Perfect fit, immediate hire candidate
- 80-89: Strong fit, definitely interview
- 70-79: Good fit, worth interviewing (SEND threshold)
- 60-69: Moderate fit, consider if pipeline thin
- 50-59: Weak fit, likely pass
- 0-49: Poor fit, definite pass (SKIP)
"""

import requests
import json
from typing import Dict, List
from app.core.logging import get_logger

logger = get_logger(__name__)


def parse_jd(jd_text: str, jd_title: str = None, seniority_override: str = None) -> Dict:
    """
    Parse job description to extract key requirements.

    In production, this would use NLP/AI to extract:
    - Required skills
    - Nice-to-have skills
    - Min years of experience
    - Seniority level
    - Responsibilities

    For now, simple keyword extraction with word-boundary matching.
    """

    import re

    jd_lower = jd_text.lower()

    # Extract languages/technologies
    # Keywords marked with True require word-boundary matching to avoid false positives
    # (e.g. "go" matching "MongoDB", "ts" matching "agents")
    tech_keywords = {
        'Python': [('python', False), ('django', False), ('flask', False), ('fastapi', False)],
        'JavaScript': [('javascript', False), ('node.js', False), ('nodejs', False)],
        'TypeScript': [('typescript', False)],
        'React': [('react', True), ('reactjs', False), ('react.js', False)],
        'Go': [('golang', False), ('\\bgo\\b', True)],
        'Rust': [('\\brust\\b', True)],
        'Java': [('\\bjava\\b', True), ('spring boot', False), ('spring framework', False)],
        'C++': [('c++', False), ('\\bcpp\\b', True)],
        'Ruby': [('\\bruby\\b', True), ('rails', False)],
        'PHP': [('\\bphp\\b', True), ('laravel', False)],
        'PostgreSQL': [('postgresql', False), ('postgres', False)],
        'MongoDB': [('mongodb', False)],
        'Redis': [('\\bredis\\b', True)],
        'Docker': [('docker', False)],
        'Kubernetes': [('kubernetes', False), ('\\bk8s\\b', True)],
        'AWS': [('\\baws\\b', True), ('amazon web services', False)],
        'GCP': [('\\bgcp\\b', True), ('google cloud', False)],
    }

    # Patterns that indicate a keyword is mentioned as an investor/backer, not a tech requirement
    # e.g. "founders of MongoDB & KAYAK", "backed by MongoDB", "invested by Google"
    investor_patterns = [
        r'founders?\s+of\s+[^.]*\b{kw}\b',
        r'backed\s+by\s+[^.]*\b{kw}\b',
        r'invest(?:ors?|ed|ment)\s+[^.]*\b{kw}\b',
        r'angels?\s+(?:including|from|like)\s+[^.]*\b{kw}\b',
        r'led\s+by\s+[^.]*\b{kw}\b.*(?:angel|investor|venture|fund)',
        r'\b{kw}\b[^.]*(?:angel|investor|venture|partner|backer)',
    ]

    def is_investor_mention(keyword: str) -> bool:
        """Check if ALL occurrences of the keyword are in investor/backer context."""
        kw_escaped = re.escape(keyword)
        # Find all positions where the keyword appears
        all_positions = [m.start() for m in re.finditer(kw_escaped, jd_lower)]
        if not all_positions:
            return False
        # Check each occurrence — if ANY is in a tech context (not investor), it's a real requirement
        for pos in all_positions:
            # Get surrounding context (sentence-ish window)
            ctx_start = max(0, pos - 120)
            ctx_end = min(len(jd_lower), pos + 120)
            ctx = jd_lower[ctx_start:ctx_end]
            is_investor = False
            for pat in investor_patterns:
                if re.search(pat.format(kw=kw_escaped), ctx):
                    is_investor = True
                    break
            if not is_investor:
                return False  # At least one mention is NOT investor context — it's a real skill
        return True  # ALL mentions are investor context

    required_skills = []
    for tech, keywords in tech_keywords.items():
        matched = False
        for kw, needs_regex in keywords:
            if needs_regex:
                if re.search(kw, jd_lower):
                    matched = True
                    break
            else:
                if kw in jd_lower:
                    matched = True
                    break
        if matched and not is_investor_mention(tech.lower()):
            required_skills.append(tech)

    # Determine seniority — use word-boundary regex to avoid false positives
    # (e.g. "leader" matching "lead", "seniority" matching "senior")
    seniority = 'Flexible'  # default when JD doesn't specify seniority
    if re.search(r'\bsenior\b', jd_lower) or re.search(r'\bsr\b', jd_lower) or re.search(r'\blead\b', jd_lower) or re.search(r'\bstaff\b', jd_lower):
        seniority = 'Senior'
    elif re.search(r'\bjunior\b', jd_lower) or re.search(r'\bentry\b', jd_lower) or 'early career' in jd_lower:
        seniority = 'Junior'
    elif re.search(r'\bprincipal\b', jd_lower) or re.search(r'\barchitect\b', jd_lower):
        seniority = 'Principal'

    # Extract years of experience
    min_years = 0
    if '5+ years' in jd_lower or '5 years' in jd_lower:
        min_years = 5
    elif '3+ years' in jd_lower or '3 years' in jd_lower:
        min_years = 3
    elif '7+ years' in jd_lower or '7 years' in jd_lower:
        min_years = 7

    # Use explicit override from role if set, otherwise use auto-detected
    final_seniority = seniority_override if seniority_override else seniority

    return {
        'required_skills': required_skills,
        'nice_to_have_skills': [],  # TODO: Extract from "nice to have" section
        'min_years_exp': min_years,
        'seniority': final_seniority,
        'raw_text': jd_text,
        'title': jd_title
    }


def calculate_fit_score(
    api_key: str,
    candidate_data: Dict,
    parsed_jd: Dict
) -> Dict:
    """
    Calculate FitScore by comparing candidate against job requirements.

    Args:
        api_key: DeepSeek API key
        candidate_data: Candidate info including vibe_report, skills, etc.
        parsed_jd: Parsed job description with requirements

    Returns:
        FitScore result with recommendation
    """

    github_handle = candidate_data.get('github_username', 'Unknown')
    name = candidate_data.get('name', 'Unknown')
    archetype = candidate_data.get('archetype', 'Unknown')
    tier = candidate_data.get('tier', 'Unknown')
    tech_stack = candidate_data.get('tech_stack', [])
    vibe_report = candidate_data.get('vibe_report', {})
    github_metrics = candidate_data.get('github_metrics', {})
    yoe = candidate_data.get('yoe', 0)
    current_role = candidate_data.get('current_role')
    current_company = candidate_data.get('current_company')
    location = candidate_data.get('location')
    raw_notes = candidate_data.get('notes', '')
    resume_text = candidate_data.get('resume_text', '') or ''
    linkedin_text = candidate_data.get('linkedin_text', '') or ''
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

    # Extract trajectory_summary from vibe_report (snake_case)
    trajectory_summary = vibe_report.get('trajectory_summary', '')
    if not trajectory_summary:
        # Build trajectory from available data
        parts = []
        if yoe: parts.append(f"{yoe} years of experience")
        if current_role and current_company: parts.append(f"currently {current_role} at {current_company}")
        elif current_role: parts.append(f"currently {current_role}")
        if archetype and tier: parts.append(f"classified as {archetype} ({tier} tier)")
        trajectory_summary = '. '.join(parts) if parts else 'No detailed trajectory available'

    # Extract verified_skills from vibe_report
    verified_skills = vibe_report.get('verified_skills', [])

    # Extract top repos from vibe_report
    top_repos = vibe_report.get('top_repos', [])

    # Extract highlights and convert to merit_points format (VibeChekk uses meritPoints)
    highlights = vibe_report.get('highlights', [])
    # Handle both formats: strings (e.g. "Built X with Y stars") or dicts (e.g. {type, title, detail})
    merit_points = []
    for h in highlights:
        if isinstance(h, dict) and h.get('type') == 'positive':
            merit_points.append(h)
        elif isinstance(h, str):
            merit_points.append({'title': h, 'detail': '', 'type': 'positive'})
    merit_points = merit_points[:5]

    # Build seniority from tier first (tier already encodes experience level), then YOE as fallback
    seniority = 'Unknown'

    # Tier mapping — actual tiers: COMMON, UNCOMMON, RARE, ULTRA RARE, LEGENDARY
    tier_upper = tier.upper() if tier else ''
    if 'LEGENDARY' in tier_upper:
        seniority = 'Senior+'  # Top-tier, exceptional
    elif 'ULTRA' in tier_upper:
        seniority = 'Senior+'  # Top 1-5%
    elif 'RARE' in tier_upper:
        seniority = 'Senior'  # Strong senior-level signal
    elif 'UNCOMMON' in tier_upper:
        seniority = 'Mid-Senior'  # Solid performer
    elif 'COMMON' in tier_upper:
        seniority = 'Mid-Level'  # Competent engineer
    elif yoe >= 7:
        # Fallback to YOE if tier not available
        seniority = 'Senior'
    elif yoe >= 4:
        seniority = 'Mid-Level'
    elif yoe > 0:
        seniority = 'Junior'

    # Debug logging
    logger.debug("="*80)
    logger.debug("Building prompt for %s", github_handle)
    logger.debug("="*80)
    logger.debug("name: %s", name)
    logger.debug("current_role: %s", current_role)
    logger.debug("current_company: %s", current_company)
    logger.debug("seniority: %s", seniority)
    logger.debug("location: %s", location)
    logger.debug("archetype: %s", archetype)
    logger.debug("tier: %s", tier)
    logger.debug("trajectory_summary: %s...", trajectory_summary[:200] if trajectory_summary else 'MISSING')
    logger.debug("merit_points count: %d", len(merit_points))
    logger.debug("="*80)

    # Build prompt for DeepSeek - EXACTLY matching VibeChekk format
    # Include the full JD text (up to 3000 chars) so DeepSeek can reference specific requirements
    jd_title = parsed_jd.get('title', 'Unknown')
    jd_full_text = parsed_jd.get('raw_text', '')

    prompt = f"""You are an expert technical recruiter. Analyze this candidate against the FULL job description below and determine if they are a good fit.

=== FULL JOB DESCRIPTION ===
Title: {jd_title}
{jd_full_text}
=== END JOB DESCRIPTION ===

CANDIDATE PROFILE:
- GitHub: @{github_handle}
- Name: {name or 'Unknown'}
- Current Role: {current_role or 'Unknown'} at {current_company or 'Unknown'}
- Seniority: {seniority}
- Location: {location or 'Unknown'}
- Archetype: {archetype} ({tier})
- Career Summary: {trajectory_summary}
- Tech Stack (from GitHub): {', '.join(tech_stack[:15]) if tech_stack else 'Unknown'}
{"- Verified Skills (from GitHub): " + ", ".join(f"{s.get('name', '')} ({s.get('level', '')})" if isinstance(s, dict) else str(s) for s in verified_skills[:20]) if verified_skills else ""}

KEY ACHIEVEMENTS (from GitHub):
{chr(10).join([f"{i+1}. {mp.get('title', '')}: {mp.get('detail', '')}" for i, mp in enumerate(merit_points)]) if merit_points else 'No achievements available'}
{chr(10).join([
    '',
    'NOTABLE GITHUB PROJECTS:',
    *[f"- {r.get('name', '?')} — {r.get('description', 'No description')}"
      f" | ★ {r.get('stars', 0)} stars, {r.get('forks', 0)} forks"
      f" | Language: {r.get('language', 'N/A')}"
      for r in top_repos[:5]],
    ''
]) if top_repos else ''}
{"" if not resume_text else chr(10) + "=== RESUME / WORK HISTORY ===" + chr(10) + "IMPORTANT: This is the candidate's full resume. It contains their complete work history, specific projects, domain experience, and skills that may NOT be visible from GitHub alone. You MUST read and weigh this carefully — do not base your analysis on GitHub data alone." + chr(10) + resume_text + chr(10) + "=== END RESUME ===" + chr(10)}
{"" if not linkedin_text else chr(10) + "=== LINKEDIN PROFILE ===" + chr(10) + linkedin_text + chr(10) + "=== END LINKEDIN ===" + chr(10)}
{"" if not candidate_notes else "=== RECRUITER NOTES & LINKEDIN PROFILE ===" + chr(10) + "IMPORTANT: These notes may contain the candidate's LinkedIn profile, work history, and background information that is NOT visible from GitHub. Read carefully — this often contains critical domain experience, specific company roles, and skills." + chr(10) + candidate_notes + chr(10) + "=== END NOTES ===" + chr(10)}
EXTRACTED SKILLS FROM JD (for reference):
- Required Skills: {', '.join(parsed_jd['required_skills']) if parsed_jd['required_skills'] else 'See full JD above'}
- Seniority Level: {parsed_jd['seniority']}

Analyze the fit and return a JSON object. Your analysis MUST:
1. Reference SPECIFIC requirements from the job description (quote or paraphrase them)
2. Map the candidate's actual experience to specific JD requirements
3. Call out where the candidate fits AND where they don't, citing the JD

{{
  "fitScore": 75,  // 0-100 score based on overall match
  "recommendation": "SEND",  // "SEND" (>= 70 score) or "SKIP" (< 70 score)

  "skillsMatch": {{
    "matched": [
      {{"name": "<skill from JD>", "evidence": "<specific repo, project, or role where candidate uses this>", "jd_relevance": "<why this matters for the JD>"}},
      {{"name": "<another skill>", "evidence": "<concrete evidence from their GitHub or resume>", "jd_relevance": "<maps to which JD requirement>"}}
    ],  // Skills AND qualifications the candidate has that the job requires — include both technical skills (Python, React) AND non-technical requirements (founder experience, social impact work, coaching, domain expertise). Each with WHERE they demonstrate it and WHY it matters for the JD. IMPORTANT: Use ONLY data from the candidate profile above — never invent repos, companies, or projects.
    "missing": ["<skill JD requires but candidate lacks>"],  // Skills/qualifications the JD EXPLICITLY requires that the candidate lacks — ONLY include things actually stated in the JD, never invent gaps
    "extra": [
      {{"name": "<bonus skill>", "evidence": "<where they demonstrate it>", "jd_relevance": "<why it adds value beyond JD requirements>"}}
    ]  // Valuable BONUS skills beyond JD requirements — each with WHERE they use it and WHY it matters. Domain expertise (healthcare, fintech, etc.) goes here when the JD says it's "a plus" or "preferred" — it adds value but its ABSENCE must NEVER appear in concernsForRole or lower the score.
  }},

  "experienceMatch": {{
    "candidateLevel": "{seniority}",  // If the provided value is "Unknown", infer the candidate's seniority from their resume, work history, and GitHub activity (e.g. co-founder + multiple companies + years of work = Mid-Senior or Senior). Never return "Unknown" — always infer a level. Otherwise use the provided seniority level - DO NOT downgrade based on role fit
    "requiredLevel": "{parsed_jd['seniority']}",  // From JD. Copy this value exactly — do not override it.
    "meets": true  // Whether candidate meets experience requirement
  }},

  "strengthsForRole": [
    "JD asks for X — candidate has proven this through Y",
    "Role requires Z — candidate's experience at Company shows..."
  ],  // 3-7 specific reasons tied to JD requirements. Include BOTH technical matches AND non-technical/cultural matches (founder experience, mission alignment, coaching, domain expertise, leadership, etc.). Many JDs have requirements beyond pure tech skills — treat those as first-class strengths when the candidate matches them.

  "concernsForRole": [
    "JD requires X but candidate has no evidence of this",
    "Role needs Y experience — candidate's background is in Z instead"
  ],  // 0-5 specific gaps tied to JD requirements. CAN be empty [] if the candidate genuinely covers all major JD requirements. Do NOT manufacture concerns just to fill this field. Only include concerns backed by a real, evidenced gap.

  "aiSummaryShort": "A punchy 2-3 sentence executive summary. MUST start with the candidate's first name in 3rd person (e.g. 'Alex is a ...' or 'Alex brings ...'). Lead with the strongest signal — their most relevant experience or most impressive project — then state the fit verdict. For strong fits (score >= 75), the summary should be enthusiastic and conviction-forward — do NOT end on a hedge or concern. For weaker fits, note the primary gap. Do NOT invent gaps from technologies the JD never mentioned.",

  "aiSummary": "A rich, detailed narrative for a hiring manager. Use multiple paragraphs separated by \\n\\n for readability — as many as the depth of analysis warrants. Use <b></b> HTML tags to highlight 3-5 key insight phrases across the ENTIRE summary. Wrap ONLY full insight sentences or clauses that would make a hiring manager stop and think 'wow' — e.g. '<b>concrete evidence he has already worked to create pathways to real second chances within the system</b>', '<b>an analogous challenge to working within the criminal justice ecosystem</b>', '<b>a mission-driven builder whose past initiatives uniquely mirror the company future goals</b>'. NEVER wrap names (people, companies, job titles), technologies, programming languages, or short labels in <b> tags. <b> is reserved for the emotional/analytical punchlines only. IMPORTANT: The conclusion/closing paragraph MUST contain at least one <b>-wrapped statement — this should be the most powerful takeaway that summarizes why this candidate is special (e.g. '<b>represents a rare combination of technical depth, healthcare domain expertise, and startup experience that could significantly accelerate Orchid's platform development</b>'). Also bold any standout characterizations mid-summary that capture the candidate's unique value proposition (e.g. '<b>his open-source contributions demonstrate the engineer's engineer mentality the JD values</b>'). Think of bolding as highlighting the 3-5 moments in the summary that a hiring manager skimming would need to see to understand the candidate's core value. Reference SPECIFIC companies the candidate worked at, specific projects/repos they built, domain expertise from their resume, and how each maps to the JD requirements. Name their GitHub repos, their past employers, and concrete technologies used. This should read like a talent brief that makes the candidate's experience tangible and real — not a generic summary. For strong fits, the narrative should build conviction — end with why this candidate is worth interviewing, not with a caveat."
}}

CRITICAL FORMAT RULES:
- concernsForRole MUST be a flat array of strings like ["concern1", "concern2"]
- DO NOT structure it as an object with critical/moderate/minor keys
- skillsMatch.matched and skillsMatch.extra MUST be arrays of objects with "name", "evidence", and "jd_relevance" keys
- "evidence" should reference WHERE the candidate uses this skill (specific repo, company, project from GitHub or resume). Always include quantitative proof when the resume or GitHub provides it — star counts (e.g. "1.5K stars"), download numbers (e.g. "3.3M+ monthly downloads"), revenue (e.g. "$100K ARR"), user counts, growth metrics, etc. Numbers make evidence credible and help hiring managers gauge impact.
- "jd_relevance" should explain WHY this skill matters for this specific JD
- skillsMatch.missing should remain a flat array of strings

RESUME CROSS-REFERENCING (CRITICAL):
- Go through EVERY skill, technology, and qualification the JD asks for and check whether the RESUME mentions it — in a project description, job bullet point, or skills section. Many candidates use technologies in their day jobs or side projects that never appear on GitHub.
- If the resume mentions a JD-required skill, it MUST appear in skillsMatch.matched with evidence citing the resume project/role — do NOT omit it just because it's not on GitHub.
- A skill is MATCHED if the candidate has used it anywhere — GitHub repos, resume projects, work history, or side projects. Not just GitHub.
- EVIDENCE QUALITY: When the resume or GitHub provides business metrics or quantitative proof, you MUST include them in the evidence string. Examples: revenue ("$100K ARR"), star counts ("1.5K stars"), download numbers ("3.3M+ monthly downloads"), user counts ("10K+ users"), growth metrics. Do not write "built X" when the resume says "built X generating $100K ARR" — include the number. Concrete proof makes the candidate's skills credible to hiring managers.

SCORING RUBRIC:
- 90-100: Perfect fit, immediate hire candidate
- 80-89: Strong fit, definitely interview
- 70-79: Good fit, worth interviewing
- 60-69: Moderate fit, consider if pipeline thin
- 50-59: Weak fit, likely pass
- 0-49: Poor fit, definite pass

SCORING NON-TECHNICAL REQUIREMENTS:
Many JDs list non-technical requirements that are just as important as tech skills: founder/0-to-1 experience, mission alignment, social impact background, coaching/mentoring, entrepreneurial mindset, specific domain experience, leadership, etc. When a candidate matches these, they should contribute SIGNIFICANTLY to the fitScore — not just be mentioned as vague strengths while the score stays low. A candidate who matches every explicit requirement in a JD (both technical and non-technical) should score 82+, not 71.

IMPORTANT:
- GROUNDING RULE: Use ONLY data from the candidate profile provided above. NEVER invent, hallucinate, or borrow repos, companies, projects, or achievements from examples or other candidates. If the candidate's profile is thin, say so honestly — a short but accurate analysis is better than a fabricated one.
- Reference the actual job description in your analysis — don't just analyze the candidate in isolation
- strengthsForRole and concernsForRole should cite specific JD requirements
- aiSummary should read like a detailed recruiter talent brief for a hiring manager — name specific companies, repos, projects, and technologies FROM THE CANDIDATE'S ACTUAL PROFILE. NOT "this candidate has experience in X" but rather "At [their actual company], they built [their actual project] using [their actual tech stack]. Their open-source project [actual repo name] ([actual star count] stars) shows deep [relevant] expertise." Make it tangible and specific — but ONLY reference real data from the candidate profile above.
- Be granular with scoring (avoid round numbers like 40, 50, 60, 70)
- Candidate seniority is independent of role fit — don't conflate "poor fit" with "junior"
- Use the provided Seniority level exactly in experienceMatch.candidateLevel
- If a RESUME is provided, it is the MOST authoritative source of the candidate's experience. GitHub only shows open-source activity — the resume shows their full professional history including domain expertise, specific companies, projects, and skills that may never appear on GitHub.
- When the resume shows relevant domain experience (e.g. healthcare, fintech, etc.) that the JD asks for, this MUST be reflected as a strength, not ignored.
- Do NOT say "lacks experience in X" if the resume clearly shows experience in X — even if GitHub doesn't show it.
- SCAN THE RESUME PROJECT BY PROJECT. Each resume project or job bullet may mention technologies (TypeScript, Redis, NuxtJS, etc.), design skills (UI/UX, frontend polish), or domain expertise that the JD requires. Every match MUST be included in skillsMatch.matched. Do not be lazy — read every line of the resume.
- skillsMatch.missing MUST only contain skills the JD explicitly asks for. Do NOT invent missing skills from technologies the JD never mentioned. READ THE JD CAREFULLY before deciding something is required:
  * If a company name (e.g. MongoDB) appears in the JD as an INVESTOR, partner, or backer — it is NOT a required technology. "Founded by the founders of MongoDB" means MongoDB invested, not that the tech stack uses MongoDB.
  * If a language/framework (e.g. Go, Rust, Java) is NOT listed in the JD's requirements/qualifications section, do NOT add it to missing skills — even if you think the company might use it. Only explicitly listed technologies count.
  * concernsForRole must NEVER cite a technology the JD doesn't explicitly require. If the JD lists "Python and database systems" as requirements, only Python and database experience are required — not Go, not MongoDB, not any other tech you infer from context.
  * When in doubt about whether something is required, re-read the "Proficiency in" or "Requirements" section of the JD verbatim. If it's not there, it's not required.
- DOMAIN/INDUSTRY EXPERIENCE — "A PLUS" ≠ REQUIRED: When the JD says domain experience is "a plus," "preferred," "nice to have," or "bonus," treat it ONLY as an upside: if the candidate HAS it, put it in skillsMatch.extra and boost the score; if the candidate LACKS it, do NOT mention it in concernsForRole, do NOT dock the score, and do NOT frame it as a gap. Many companies (healthcare, fintech, legal-tech, etc.) hire strong generalist engineers who lack their specific industry background. Only flag missing domain experience as a concern if the JD uses hard-requirement language like "required," "must have," or "X years of experience in Y industry." The company's vertical alone does not make domain experience a requirement.
- The aiSummaryShort and concernsForRole must NOT mention technology gaps unless the JD explicitly requires that technology. Never fabricate gaps.
- SELF-CONSISTENCY CHECK: Before finalizing, re-read your strengthsForRole. If you cited evidence in a strength (e.g. volunteer work, coaching, domain experience, community work), do NOT then list its absence as a concern. If the candidate has evidence of coaching inmates, mentoring students, volunteering with underserved communities, etc., you CANNOT say they "lack evidence of hands-on coaching" or "lack case work experience." A concern must not contradict a strength you already wrote.
- concernsForRole should only flag GENUINELY missing evidence — things the candidate truly has no track record of. If in doubt, omit the concern rather than contradict yourself.
- LOCATION & RELOCATION — NOT A RED FLAG: If a candidate is based in a different city than the JD requires but their profile indicates they are OPEN to relocation, willing to relocate, or mention relocation preferences — do NOT frame this as a concern or "hurdle." Relocation assistance is standard practice for strong candidates. Only flag location as a concern if the candidate explicitly states they will NOT relocate. Phrases like "requires relocation bonus" or "open to NYC" signal willingness, not resistance.
- SPECIALIZATION DEPTH — NOT A WEAKNESS: If a candidate has deep specialization in a specific area (e.g. blockchain, ML, data pipelines), do NOT frame this as "narrow expertise" or a concern. Deep expertise is a strength. The fact that someone spent 2 years going deep in one area shows focus and mastery, not limitation. Only flag it as a concern if the JD explicitly requires breadth that the candidate demonstrably lacks across ALL their experience (not just their most recent role).
- INVESTOR/BACKER NAMES — NEVER TECH REQUIREMENTS: This bears repeating because it keeps happening. If the JD mentions a company name (MongoDB, Google, a16z, etc.) as an investor, backer, founder background, or partner — that is NOT a technology requirement. Do NOT say "candidate shows no evidence of MongoDB experience" when MongoDB is listed as an investor. Do NOT connect investor names to technology gaps in any way — not in concernsForRole, not in aiSummary, not in aiSummaryShort.
- STOP MANUFACTURING NEGATIVES — NEGATIVITY BIAS CHECK: You have a persistent tendency to ALWAYS find something negative to say, even for strong candidates. This undermines credibility. Apply these rules:
  * If the resume or skills section LISTS a technology (e.g. "Python" in skills), do NOT say "lacks concrete evidence of production backend services with Python." They listed it — that IS evidence. You can note they haven't listed specific Python backend projects if that's true, but frame it as "interview topic" not "concern."
  * ADJACENT/FOUNDATIONAL EXPERIENCE COUNTS: If a candidate has deep ML/PyTorch experience and the role involves LLMs, that is FOUNDATIONAL — not a gap. LLMs are built on ML. PyTorch is the primary framework for LLM fine-tuning. Do NOT say "no evidence of LLM experience" when the candidate has core ML infrastructure experience. The same applies broadly: React experience covers Next.js roles, Python experience covers FastAPI roles, database experience covers any specific database, distributed systems experience covers cloud infrastructure, etc. A senior engineer with foundational expertise can learn a specific framework in weeks. Frame this as a STRENGTH ("strong ML foundation positions them well for LLM work") not a gap.
  * FOR SCORES >= 75: concernsForRole should have AT MOST 1-2 items, and they must be genuinely significant gaps — not nitpicks. If you're scoring someone 78+ but listing 3+ concerns, your concerns are too nitpicky. Cut the weakest ones.
  * FOR SCORES >= 80: The aiSummary MUST NOT end on a "however" or caveat paragraph. End with conviction about why this candidate is worth interviewing. If you write "However, significant gaps exist..." for an 80+ score candidate, something is wrong — either your score is too high or your concern is manufactured.
  * NEVER say "no evidence of X" when the candidate clearly has adjacent/foundational experience in X. Instead say "while not directly demonstrated, their [foundational skill] provides a strong base for [specific requirement]."
  * DO NOT treat specific framework/tool versions as gaps. If the JD says "FastAPI" and the candidate knows Python + Flask + Django, that's a match — FastAPI is learnable in days for any Python developer. The same applies to specific databases, cloud providers, etc.
  * BEFORE writing each concern, ask yourself: "Would a reasonable hiring manager actually care about this, or am I being pedantic?" If a senior engineer with 5+ years of Python is being flagged for "no evidence of FastAPI specifically," that's pedantic. Cut it.
- Return ONLY valid JSON, no markdown
"""

    # Log the candidate profile section of the prompt for debugging
    logger.debug("PROMPT PREVIEW (Candidate Profile section):")
    logger.debug("="*80)
    candidate_profile_section = prompt.split("CANDIDATE PROFILE:")[1].split("KEY ACHIEVEMENTS:")[0] if "CANDIDATE PROFILE:" in prompt else "NOT FOUND"
    logger.debug("%s", candidate_profile_section[:800])
    logger.debug("="*80)

    try:
        import time as _time

        max_retries = 3
        response = None
        last_err = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.info("Calling DeepSeek API (attempt %d/%d)...", attempt, max_retries)
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
                                'content': 'You are an expert technical recruiter who evaluates candidate fit objectively based on data. Use precise, granular scoring - avoid round numbers and common patterns. Your role is to make the CASE for why a candidate should be interviewed — not to find reasons to reject them. For candidates scoring 75+, lead with conviction and enthusiasm. Only flag concerns that a hiring manager would genuinely care about.'
                            },
                            {'role': 'user', 'content': prompt}
                        ],
                        'temperature': 0.4
                    },
                    timeout=90
                )
                response.raise_for_status()
                break  # Success — exit retry loop
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as retry_err:
                last_err = retry_err
                if attempt < max_retries:
                    backoff = 2 ** attempt  # 2s, 4s
                    logger.warning("DeepSeek attempt %d failed (%s), retrying in %ds...", attempt, retry_err, backoff)
                    _time.sleep(backoff)
                else:
                    logger.error("DeepSeek failed after %d attempts: %s", max_retries, retry_err)
                    raise

        logger.info("DeepSeek response status: %d", response.status_code)

        if not response.ok:
            logger.error("DeepSeek API error response: %s", response.text[:500])

        response.raise_for_status()
        data = response.json()

        content = data['choices'][0]['message']['content']
        logger.debug("DeepSeek response length: %d chars", len(content))
        logger.debug("Response preview: %s...", content[:300])

        # Strip markdown code fences if present
        json_text = content.strip()
        if json_text.startswith('```json'):
            json_text = json_text.replace('```json', '').replace('```', '').strip()
        elif json_text.startswith('```'):
            json_text = json_text.replace('```', '').strip()

        fit_result = json.loads(json_text)

        logger.info("Successfully parsed fitScore: %s, recommendation: %s", fit_result.get('fitScore'), fit_result.get('recommendation'))

        return fit_result

    except json.JSONDecodeError as e:
        logger.error("JSON Parse Error: %s", e)
        logger.error("Raw content that failed to parse: %s", content[:1000] if 'content' in locals() else 'N/A')
        error_msg = f"JSON Parse Error: {e}"
    except requests.exceptions.RequestException as e:
        logger.error("Request Error: %s", e)
        error_msg = f"Request Error: {e}"
    except Exception as e:
        logger.error("Unexpected Error: %s: %s", type(e).__name__, e)
        error_msg = str(e)

    # DeepSeek failed — raise so callers know not to persist a bogus analysis
    raise RuntimeError(f"DeepSeek analysis failed: {error_msg}")
