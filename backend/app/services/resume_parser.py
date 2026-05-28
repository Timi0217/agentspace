"""
Resume Parsing using DeepSeek

Extracts structured data from resume text:
- Years of experience (YOE)
- Current company
- Current role/title
"""

import json
import httpx
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def parse_resume_fields(resume_text: str) -> dict:
    """
    Parse resume text to extract structured fields using DeepSeek.

    Args:
        resume_text: Raw text extracted from resume PDF

    Returns:
        Dict with: yoe (int), current_company (str), current_role (str)
    """
    logger.info("Parsing resume (%d chars)", len(resume_text))

    prompt = f"""Extract the following information from this resume. Return ONLY valid JSON, no markdown formatting:

{{
  "yoe": <number of years of professional experience, or null if not clear>,
  "current_company": "<most recent company name, or null if not employed/clear>",
  "current_role": "<most recent job title, or null if not clear>"
}}

Guidelines:
- For YOE: Count years in professional roles only (exclude internships/education)
- For current company/role: Use the MOST RECENT position listed
- If unemployed/freelancing, set company to null
- Return null for any field you cannot determine with confidence

Resume:
{resume_text[:4000]}
"""

    try:
        response = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You are a resume parser. Extract structured data and return ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.0,
            },
            timeout=30.0,
        )

        response.raise_for_status()
        data = response.json()

        content = data['choices'][0]['message']['content']
        logger.debug("DeepSeek response: %s...", content[:200])

        # Strip markdown code fences if present
        json_text = content.strip()
        if json_text.startswith('```json'):
            json_text = json_text.replace('```json', '').replace('```', '').strip()
        elif json_text.startswith('```'):
            json_text = json_text.replace('```', '').strip()

        parsed_data = json.loads(json_text)

        logger.info("Extracted: YOE=%s, Company=%s, Role=%s",
                    parsed_data.get('yoe'), parsed_data.get('current_company'), parsed_data.get('current_role'))

        return parsed_data

    except json.JSONDecodeError as e:
        logger.error("JSON parse error: %s", e)
        logger.error("Response was: %s", content)
        return {}
    except Exception as e:
        logger.error("Error parsing resume: %s", e)
        return {}
