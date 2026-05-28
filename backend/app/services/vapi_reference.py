"""
VAPI Reference Call Service

Handles automated reference check calls (5 min quick calls).
"""

import httpx
from typing import Dict, Any
from app.core.config import settings


def create_reference_assistant(candidate_name: str, reference_name: str, relationship: str) -> Dict[str, Any]:
    """
    Create VAPI assistant for reference call.

    Args:
        candidate_name: Name of candidate being referenced
        reference_name: Name of person giving reference
        relationship: Relationship to candidate

    Returns:
        VAPI assistant configuration
    """
    system_prompt = f"""You are conducting a quick 5-minute reference check for {candidate_name}.

You're speaking with {reference_name} who was their {relationship}.

Ask these questions naturally and conversationally:
1. How do you know {candidate_name}? (confirm relationship)
2. What was it like working with them?
3. What are their strengths as an engineer?
4. Any areas where they could grow or improve?
5. Would you work with them again?

Keep responses concise and focused. Be friendly but professional. Listen for both technical and soft skills signals.

After the call, provide a structured summary with:
- Overall sentiment (positive/neutral/negative)
- Key strengths mentioned
- Growth areas (if any)
- Would work with them again (yes/no/maybe)
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
            "voiceId": "rachel"
        },
        "name": f"Reference Check - {candidate_name}",
        "firstMessage": f"Hi {reference_name.split()[0]}! Thanks so much for taking the time. I just have a few quick questions about {candidate_name}. Should only take 5 minutes. How are you doing today?",
        "recordingEnabled": True,
        "endCallFunctionEnabled": True,
        "dialKeypadFunctionEnabled": False,
        "maxDurationSeconds": 600,  # 10 minutes max
    }

    return assistant_config


def create_reference_call(reference: Any, candidate_name: str, phone_number: str) -> Dict[str, Any]:
    """
    Create outbound reference check call via VAPI.

    Args:
        reference: Reference model instance
        candidate_name: Candidate's name
        phone_number: Reference's phone number

    Returns:
        VAPI call response with call_id
    """
    assistant_config = create_reference_assistant(
        candidate_name=candidate_name,
        reference_name=reference.reference_name,
        relationship=reference.relationship
    )

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
                "name": reference.reference_name
            }
        },
        timeout=30.0
    )

    response.raise_for_status()
    return response.json()


def extract_reference_data(transcript: str, candidate_name: str) -> Dict[str, Any]:
    """
    Extract structured data from reference call transcript.

    Args:
        transcript: Full call transcript
        candidate_name: Candidate being referenced

    Returns:
        Structured reference data
    """
    from app.services.deepseek import call_deepseek
    import json

    prompt = f"""Extract structured information from this reference check call for {candidate_name}.

Transcript:
{transcript[:6000]}

Return ONLY valid JSON:
{{
  "would_work_again": true | false | null,
  "overall_sentiment": "positive" | "neutral" | "negative",
  "strengths": "key strengths mentioned (2-3 sentences)",
  "areas_to_grow": "growth areas if mentioned (or null)",
  "summary": "one-sentence overall take on the candidate"
}}

Be honest and direct. Extract the real signal.
"""

    result = call_deepseek(prompt, temperature=0.0)

    # Parse JSON
    json_text = result.strip()
    if json_text.startswith('```json'):
        json_text = json_text.replace('```json', '').replace('```', '').strip()

    return json.loads(json_text)
