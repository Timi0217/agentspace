"""
AI Screening Service using VAPI API

Handles personalized screening call generation and execution.
"""

import httpx
from typing import Dict, Any, Optional
from app.core.config import settings


def generate_personalized_questions(candidate: Any) -> list[str]:
    """
    Generate personalized screening questions based on candidate profile.

    Args:
        candidate: Candidate model instance with profile data

    Returns:
        List of personalized questions
    """
    questions = []

    # Standard opening questions
    questions.extend([
        "Hi! Thanks for taking the time to chat. Can you start by telling me about your background?",
        "What are you working on now?",
        "Why are you looking for something new?"
    ])

    # Personalized based on work history
    if candidate.current_company:
        questions.append(f"I see you're at {candidate.current_company}. Tell me more about your role there.")

    # Check for short tenures (potential red flags or interesting stories)
    if candidate.vibe_report and candidate.vibe_report.get('work_history'):
        for job in candidate.vibe_report.get('work_history', []):
            if job.get('duration_months', 12) < 6:
                company = job.get('company', 'that company')
                questions.append(f"I noticed you were at {company} for a short time. What was that experience like?")

    # Technical depth validation
    if candidate.vibe_report and candidate.vibe_report.get('verified_skills'):
        top_skills = [s for s in candidate.vibe_report.get('verified_skills', []) if s.get('level') in ['Expert', 'Advanced']]
        if top_skills:
            skill = top_skills[0].get('skill', 'your primary technology')
            questions.append(f"Your GitHub shows strong {skill} work. How deep is your expertise with {skill}?")

    # Project-specific questions
    if candidate.vibe_report and candidate.vibe_report.get('notable_projects'):
        projects = candidate.vibe_report.get('notable_projects', [])
        if projects:
            project = projects[0].get('name', 'that project')
            questions.append(f"I see you built {project}. Can you walk me through the technical challenges there?")

    # Standard role/fit questions
    questions.extend([
        "What kind of role are you looking for?",
        "Why founding or early-stage specifically? What attracts you to that environment?",
        "What's your timeline for making a move?",
        "What's your comp expectation? Think salary plus equity.",
        "Where are you located? Are you open to remote or would you prefer in-person?",
        "What's your ideal tech stack to work with?",
        "Is there anything else you want me to know about you or what you're looking for?"
    ])

    return questions


def create_screening_assistant(candidate: Any) -> Dict[str, Any]:
    """
    Create VAPI assistant configuration with personalized questions.

    Args:
        candidate: Candidate model instance

    Returns:
        VAPI assistant configuration dict
    """
    questions = generate_personalized_questions(candidate)

    # Build system prompt with questions embedded
    system_prompt = f"""You are a friendly technical recruiter conducting a screening call for {candidate.name or candidate.github_username}.

Your goal is to have a natural 10-15 minute conversation to learn about their background, motivations, and fit for founding/early-stage engineering roles.

Key points to cover:
1. Background and current work
2. Why they're exploring new opportunities
3. What type of role they want (founding engineer, early-stage, etc.)
4. Technical skills validation
5. Timeline and availability
6. Compensation expectations (salary + equity)
7. Location and remote preferences
8. Ideal tech stack

Be conversational and natural - not robotic. Listen actively and ask follow-up questions when something interesting comes up. Keep responses concise.

PERSONALIZED QUESTIONS TO ASK:
{chr(10).join([f"- {q}" for q in questions])}

After the call, you'll provide a structured summary with:
- Key technical skills validated
- Motivation for looking
- Comp expectations
- Timeline/availability
- Location preferences
- Culture fit signals
- Red flags (if any)
"""

    assistant_config = {
        "model": {
            "provider": "openai",
            "model": "gpt-4",
            "temperature": 0.7,
            "systemPrompt": system_prompt,
        },
        "voice": {
            "provider": "11labs",
            "voiceId": "rachel"  # Friendly, professional female voice
        },
        "name": f"Screening Call - {candidate.github_username}",
        "firstMessage": f"Hi {candidate.name.split()[0] if candidate.name else 'there'}! Thanks so much for joining. I'm excited to learn more about you. How are you doing today?",
        "recordingEnabled": True,
        "endCallFunctionEnabled": True,
        "dialKeypadFunctionEnabled": False,
        "maxDurationSeconds": 1200,  # 20 minutes max
    }

    return assistant_config


def create_screening_call(candidate: Any, phone_number: str) -> Dict[str, Any]:
    """
    Create an outbound screening call via VAPI API.

    Args:
        candidate: Candidate model instance
        phone_number: Candidate's phone number

    Returns:
        VAPI call response with call_id
    """
    assistant_config = create_screening_assistant(candidate)

    # Create call via VAPI API
    response = httpx.post(
        "https://api.vapi.ai/call/phone",
        headers={
            "Authorization": f"Bearer {settings.VAPI_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "assistant": assistant_config,
            "phoneNumberId": settings.VAPI_PHONE_NUMBER,
            "customer": {
                "number": phone_number,
                "name": candidate.name or candidate.github_username
            }
        },
        timeout=30.0
    )

    response.raise_for_status()
    return response.json()


def get_call_details(call_id: str) -> Dict[str, Any]:
    """
    Fetch call details from VAPI API.

    Args:
        call_id: VAPI call ID

    Returns:
        Call details including transcript and recording
    """
    response = httpx.get(
        f"https://api.vapi.ai/call/{call_id}",
        headers={
            "Authorization": f"Bearer {settings.VAPI_API_KEY}"
        },
        timeout=30.0
    )

    response.raise_for_status()
    return response.json()


def extract_screening_data(transcript: str, candidate: Any) -> Dict[str, Any]:
    """
    Use DeepSeek to extract structured data from screening transcript.

    Args:
        transcript: Full call transcript
        candidate: Candidate model instance

    Returns:
        Structured screening data
    """
    from app.services.deepseek import call_deepseek

    prompt = f"""Extract structured information from this screening call transcript.

Candidate: {candidate.name or candidate.github_username}

Transcript:
{transcript[:8000]}

Return ONLY valid JSON with this structure:
{{
  "comp_expectation": "salary range + equity (e.g., '150-180k + 0.5-1% equity')",
  "location": "location + remote preference",
  "availability": "timeline to start (e.g., '2 weeks notice', 'immediately', '1 month')",
  "motivation": "why looking for new role (1-2 sentences)",
  "technical_validation": "key skills mentioned and depth (1-2 sentences)",
  "culture_fit_signals": "signals about culture fit, work style, values",
  "red_flags": "any concerns or red flags (or null)",
  "top_strengths": ["strength 1", "strength 2", "strength 3"],
  "ideal_role": "what they're looking for in next role",
  "why_early_stage": "why interested in founding/early-stage"
}}
"""

    result = call_deepseek(prompt, temperature=0.0)

    # Parse JSON from response
    import json
    json_text = result.strip()
    if json_text.startswith('```json'):
        json_text = json_text.replace('```json', '').replace('```', '').strip()

    return json.loads(json_text)


def generate_screening_summary(transcript: str, screening_data: Dict[str, Any]) -> str:
    """
    Generate human-readable summary for hiring managers.

    Args:
        transcript: Full call transcript
        screening_data: Structured data from extraction

    Returns:
        Formatted summary text
    """
    summary = f"""## Screening Call Summary

**Motivation:** {screening_data.get('motivation', 'Not specified')}

**Technical Validation:** {screening_data.get('technical_validation', 'Not specified')}

**Top Strengths:**
{chr(10).join([f"- {s}" for s in screening_data.get('top_strengths', [])])}

**Ideal Role:** {screening_data.get('ideal_role', 'Not specified')}

**Why Early-Stage:** {screening_data.get('why_early_stage', 'Not specified')}

**Comp Expectation:** {screening_data.get('comp_expectation', 'Not discussed')}

**Location:** {screening_data.get('location', 'Not specified')}

**Availability:** {screening_data.get('availability', 'Not specified')}

**Culture Fit Signals:** {screening_data.get('culture_fit_signals', 'Not specified')}

{f"**⚠️ Red Flags:** {screening_data.get('red_flags')}" if screening_data.get('red_flags') else ''}
"""

    return summary
