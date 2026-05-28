"""
CaptainData API Integration

Enriches LinkedIn profile URLs with full professional data (experiences,
skills, education, headline, summary, etc.).

API Docs: https://docs.captaindata.com
Endpoint: GET /v1/people/enrich
Cost: 1 credit (basic) or 2 credits (full_enrich=true)
"""

import requests
from typing import Dict, List, Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.captaindata.com/v1"


def enrich_linkedin_profile(api_key: str, linkedin_url: str, full_enrich: bool = True) -> Dict:
    """
    Enrich a LinkedIn profile using CaptainData People Enrich API.

    Args:
        api_key: CaptainData API key
        linkedin_url: LinkedIn profile URL (e.g. https://www.linkedin.com/in/johndoe)
        full_enrich: If True, returns experiences, skills, education (costs 2 credits)

    Returns:
        Dictionary with enrichment results:
        {
            'success': bool,
            'full_name': str,
            'headline': str,
            'summary': str,
            'location': str,
            'job_title': str,
            'company_name': str,
            'skills': List[str],
            'experiences': List[dict],
            'education': List[dict],
            'languages': List[str],
            'open_to_work': bool,
            'linkedin_url': str,
            'profile_image_url': str,
            'connections': int,
            'followers': int,
            'raw': dict,
            'error': str (if failed),
        }
    """
    try:
        logger.info("CaptainData enriching LinkedIn: %s (full=%s)", linkedin_url, full_enrich)

        resp = requests.get(
            f"{BASE_URL}/people/enrich",
            headers={"X-API-Key": api_key},
            params={
                "li_profile_url": linkedin_url,
                "full_enrich": str(full_enrich).lower(),
            },
            timeout=30,
        )

        if resp.status_code == 400:
            error = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            logger.warning("CaptainData 400 for %s: %s", linkedin_url, error)
            return {"success": False, "error": f"Bad request: {error}"}

        if resp.status_code == 424:
            logger.warning("CaptainData 424 (dependency failed) for %s", linkedin_url)
            return {"success": False, "error": "LinkedIn profile could not be fetched (424)"}

        if not resp.ok:
            body = resp.text[:500]
            logger.error("CaptainData API error %d for %s: %s", resp.status_code, linkedin_url, body)
            return {"success": False, "error": f"CaptainData API error: {resp.status_code} — {body}"}

        data = resp.json()

        # Extract skills as flat list of names
        skills_raw = data.get("skills") or []
        skills = [s["name"] for s in skills_raw if isinstance(s, dict) and s.get("name")]

        # Extract experiences
        experiences = data.get("experiences") or []

        # Extract education
        education = data.get("education") or []

        result = {
            "success": True,
            "full_name": data.get("full_name"),
            "first_name": data.get("first_name"),
            "last_name": data.get("last_name"),
            "headline": data.get("headline"),
            "summary": data.get("summary"),
            "location": data.get("location"),
            "job_title": data.get("job_title"),
            "company_name": data.get("company_name"),
            "company_url": data.get("li_company_url"),
            "skills": skills,
            "experiences": experiences,
            "education": education,
            "languages": data.get("languages") or [],
            "open_to_work": data.get("open_to_work", False),
            "linkedin_url": data.get("li_profile_url") or linkedin_url,
            "profile_image_url": data.get("li_profile_image_url"),
            "connections": data.get("li_number_connections"),
            "followers": data.get("li_number_followers"),
            "past_company_name": data.get("past_company_name"),
            "past_job_title": data.get("past_job_title"),
            "raw": data,
        }

        logger.info(
            "CaptainData enriched %s: %s | %s @ %s | %d skills | %d experiences",
            linkedin_url,
            result["full_name"],
            result["job_title"],
            result["company_name"],
            len(skills),
            len(experiences),
        )
        return result

    except requests.exceptions.Timeout:
        logger.warning("CaptainData timeout for %s", linkedin_url)
        return {"success": False, "error": "CaptainData API timeout"}

    except Exception as e:
        logger.error("CaptainData unexpected error for %s: %s", linkedin_url, e)
        return {"success": False, "error": f"CaptainData enrichment failed: {str(e)}"}


def format_linkedin_text(data: Dict) -> str:
    """
    Convert CaptainData enrichment result into a human-readable text block
    that can be stored in candidate.linkedin_text for AI analysis.
    """
    if not data.get("success"):
        return ""

    parts = []

    if data.get("full_name"):
        parts.append(data["full_name"])
    if data.get("headline"):
        parts.append(data["headline"])
    if data.get("location"):
        parts.append(f"Location: {data['location']}")

    if data.get("summary"):
        parts.append(f"\nAbout:\n{data['summary']}")

    # Current role
    if data.get("job_title") and data.get("company_name"):
        parts.append(f"\nCurrent: {data['job_title']} at {data['company_name']}")

    # Experience history
    experiences = data.get("experiences") or []
    if experiences:
        parts.append("\nExperience:")
        for exp in experiences:
            title = exp.get("title", "")
            company = exp.get("company_name", "")
            location = exp.get("location", "")
            period = exp.get("date", "")
            duration = exp.get("job_time_period", "")
            line = f"  - {title} at {company}"
            if location:
                line += f" ({location})"
            if period:
                line += f" | {period}"
            if duration:
                line += f" [{duration}]"
            parts.append(line)

    # Education
    education = data.get("education") or []
    if education:
        parts.append("\nEducation:")
        for edu in education:
            school = edu.get("school_name", "")
            degree = edu.get("degree_name", "")
            date = edu.get("date", "")
            line = f"  - {school}"
            if degree:
                line += f" - {degree}"
            if date:
                line += f" ({date})"
            parts.append(line)

    # Skills
    skills = data.get("skills") or []
    if skills:
        parts.append(f"\nSkills: {', '.join(skills)}")

    # Languages
    languages = data.get("languages") or []
    if languages:
        parts.append(f"Languages: {', '.join(languages)}")

    if data.get("open_to_work"):
        parts.append("\nOpen to Work: Yes")

    if data.get("connections"):
        parts.append(f"Connections: {data['connections']}")

    return "\n".join(parts)
