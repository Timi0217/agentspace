"""
People Data Labs (PDL) API Integration

Enriches email addresses with LinkedIn profiles and professional data.

API Docs: https://docs.peopledatalabs.com/docs/person-enrichment-api
"""

import requests
from typing import Optional, Dict
from app.core.logging import get_logger

logger = get_logger(__name__)


def enrich_by_email(api_key: str, email: str) -> Dict:
    """
    Enrich a person by email using People Data Labs API.

    Args:
        api_key: PDL API key
        email: Email address to enrich

    Returns:
        Dictionary with enrichment results:
        {
            'success': bool,
            'linkedin_url': str (if found),
            'name': str,
            'title': str,
            'company': str,
            'location': str,
            'skills': List[str],
            'raw': dict (full PDL response),
            'error': str (if failed)
        }
    """

    try:
        url = f'https://api.peopledatalabs.com/v5/person/enrich'

        params = {
            'api_key': api_key,
            'email': email,
            'min_likelihood': '5'  # Minimum confidence score (0-10)
        }

        logger.info("Enriching email: %s", email)

        response = requests.get(url, params=params, timeout=30)

        # 404 means no match found (not an error, just no data)
        if response.status_code == 404:
            logger.info("No matching profile in PDL database for %s", email)
            return {
                'success': False,
                'error': 'No matching profile in PDL database'
            }

        if not response.ok:
            error_text = response.text
            logger.error("API error: %d - %s", response.status_code, error_text)
            return {
                'success': False,
                'error': f'PDL API error: {response.status_code}'
            }

        data = response.json()

        # Check likelihood score
        likelihood = data.get('likelihood', 0)
        if likelihood < 5:
            logger.warning("Low likelihood match (%d) for %s", likelihood, email)
            return {
                'success': False,
                'error': f'Low confidence match (likelihood: {likelihood})'
            }

        # Extract person data
        person_data = data.get('data', {})

        # Extract LinkedIn URL
        linkedin_url = person_data.get('linkedin_url')

        # Alternative: check profiles array
        if not linkedin_url:
            profiles = person_data.get('profiles', [])
            for profile in profiles:
                if profile.get('network') == 'linkedin' and profile.get('url'):
                    linkedin_url = profile['url']
                    break

        # Extract basic info
        full_name = person_data.get('full_name')
        first_name = person_data.get('first_name')
        last_name = person_data.get('last_name')

        # Extract job info
        job_title = person_data.get('job_title')
        job_company_name = person_data.get('job_company_name')

        # Extract location
        location_name = person_data.get('location_name')
        location_country = person_data.get('location_country')

        # Extract skills
        skills = person_data.get('skills', [])

        # Extract experience
        experience = person_data.get('experience', [])

        logger.info("Successfully enriched %s", email)
        logger.info("LinkedIn URL: %s", linkedin_url)
        logger.info("Name: %s", full_name)
        logger.info("Title: %s @ %s", job_title, job_company_name)

        return {
            'success': True,
            'linkedin_url': linkedin_url,
            'name': full_name,
            'first_name': first_name,
            'last_name': last_name,
            'title': job_title,
            'company': job_company_name,
            'location': location_name,
            'location_country': location_country,
            'skills': skills,
            'experience': experience,
            'raw': person_data,
            'likelihood': likelihood
        }

    except requests.exceptions.Timeout:
        logger.warning("Timeout for %s", email)
        return {
            'success': False,
            'error': 'PDL API timeout'
        }

    except Exception as e:
        logger.error("Unexpected error for %s: %s", email, e)
        return {
            'success': False,
            'error': f'PDL enrichment failed: {str(e)}'
        }
