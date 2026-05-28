import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import re
from datetime import datetime, timedelta
from app.core.logging import get_logger

logger = get_logger(__name__)


def parse_tech_stack(text: str) -> List[str]:
    """
    Extract tech stack from text.

    Looks for common technology keywords and variations.
    """
    # Map variations to canonical names
    tech_variations = {
        # Languages
        'python': ['python', 'py'],
        'javascript': ['javascript', 'js'],
        'typescript': ['typescript', 'ts'],
        'go': ['golang', 'go'],
        'rust': ['rust'],
        'java': ['java'],
        'ruby': ['ruby', 'rails', 'ruby on rails'],
        'c++': ['c++', 'cpp'],
        'c#': ['c#', 'csharp'],
        'php': ['php'],
        'swift': ['swift'],
        'kotlin': ['kotlin'],
        'elixir': ['elixir'],

        # Frontend Frameworks
        'react': ['react', 'reactjs', 'react.js'],
        'vue': ['vue', 'vuejs', 'vue.js'],
        'angular': ['angular'],
        'svelte': ['svelte'],
        'next.js': ['next', 'nextjs', 'next.js'],
        'nuxt': ['nuxt', 'nuxtjs', 'nuxt.js'],
        'gatsby': ['gatsby'],
        'remix': ['remix'],

        # Backend Frameworks
        'node.js': ['node', 'nodejs', 'node.js'],
        'django': ['django'],
        'flask': ['flask'],
        'fastapi': ['fastapi'],
        'express': ['express', 'expressjs'],
        'nestjs': ['nest', 'nestjs'],
        'rails': ['rails', 'ruby on rails'],
        'laravel': ['laravel'],
        'spring': ['spring', 'spring boot'],

        # Databases
        'postgresql': ['postgresql', 'postgres', 'psql'],
        'mysql': ['mysql'],
        'mongodb': ['mongodb', 'mongo'],
        'redis': ['redis'],
        'sqlite': ['sqlite'],
        'cassandra': ['cassandra'],
        'dynamodb': ['dynamodb'],
        'supabase': ['supabase'],
        'firebase': ['firebase'],
        'planetscale': ['planetscale'],

        # Cloud & Infrastructure
        'aws': ['aws', 'amazon web services'],
        'gcp': ['gcp', 'google cloud'],
        'azure': ['azure'],
        'vercel': ['vercel'],
        'netlify': ['netlify'],
        'heroku': ['heroku'],
        'railway': ['railway'],
        'render': ['render'],
        'fly.io': ['fly', 'fly.io'],
        'cloudflare': ['cloudflare'],

        # DevOps & Tools
        'docker': ['docker'],
        'kubernetes': ['kubernetes', 'k8s'],
        'terraform': ['terraform'],
        'ansible': ['ansible'],
        'jenkins': ['jenkins'],
        'github actions': ['github actions'],
        'gitlab ci': ['gitlab ci'],
        'circleci': ['circleci'],

        # AI & ML
        'pytorch': ['pytorch', 'torch'],
        'tensorflow': ['tensorflow', 'tf'],
        'langchain': ['langchain'],
        'openai': ['openai', 'gpt'],
        'anthropic': ['anthropic', 'claude'],
        'huggingface': ['huggingface', 'hugging face'],

        # CSS & Styling
        'tailwind': ['tailwind', 'tailwindcss'],
        'sass': ['sass', 'scss'],
        'css': ['css'],
        'styled-components': ['styled-components', 'styled components'],

        # Testing
        'jest': ['jest'],
        'pytest': ['pytest'],
        'cypress': ['cypress'],
        'playwright': ['playwright'],
        'vitest': ['vitest'],

        # Build Tools
        'webpack': ['webpack'],
        'vite': ['vite'],
        'esbuild': ['esbuild'],
        'turbopack': ['turbopack'],

        # Mobile
        'react native': ['react native', 'react-native'],
        'flutter': ['flutter'],
        'expo': ['expo'],

        # Other Tools
        'graphql': ['graphql'],
        'rest': ['rest', 'rest api', 'restful'],
        'grpc': ['grpc'],
        'websocket': ['websocket', 'websockets'],
        'prisma': ['prisma'],
        'drizzle': ['drizzle'],
        'typeorm': ['typeorm'],
        'sqlalchemy': ['sqlalchemy'],
        'cursor': ['cursor'],
        'claude code': ['claude code'],
    }

    text_lower = text.lower()
    found_tech = set()

    # Check each canonical tech and its variations
    for canonical, variations in tech_variations.items():
        for variation in variations:
            if variation in text_lower:
                found_tech.add(canonical)
                break  # Found this tech, move to next

    return sorted(list(found_tech))


def parse_posted_ago(text: str) -> Dict:
    """
    Parse 'posted X ago' text and convert to actual datetime.

    Examples:
    - "2 days ago" -> datetime 2 days ago
    - "3 weeks ago" -> datetime 3 weeks ago
    - "1 hour ago" -> datetime 1 hour ago
    - "just now" -> datetime now

    Returns: Dict with posted_at (datetime) and posted_ago_text (str)
    """
    result = {
        'posted_at': None,
        'posted_ago_text': None
    }

    text_lower = text.lower()

    # Look for patterns like "X days ago", "X hours ago", etc.
    patterns = [
        (r'(\d+)\s+day[s]?\s+ago', 'days'),
        (r'(\d+)\s+week[s]?\s+ago', 'weeks'),
        (r'(\d+)\s+month[s]?\s+ago', 'months'),
        (r'(\d+)\s+hour[s]?\s+ago', 'hours'),
        (r'(\d+)\s+minute[s]?\s+ago', 'minutes'),
    ]

    for pattern, unit in patterns:
        match = re.search(pattern, text_lower)
        if match:
            amount = int(match.group(1))
            result['posted_ago_text'] = match.group(0)

            # Calculate the datetime
            now = datetime.utcnow()
            if unit == 'days':
                result['posted_at'] = now - timedelta(days=amount)
            elif unit == 'weeks':
                result['posted_at'] = now - timedelta(weeks=amount)
            elif unit == 'months':
                result['posted_at'] = now - timedelta(days=amount * 30)  # Approximate
            elif unit == 'hours':
                result['posted_at'] = now - timedelta(hours=amount)
            elif unit == 'minutes':
                result['posted_at'] = now - timedelta(minutes=amount)

            break

    # Handle "just now" or "today"
    if 'just now' in text_lower or 'today' in text_lower:
        result['posted_at'] = datetime.utcnow()
        result['posted_ago_text'] = 'today'

    return result


def parse_location_requirement(text: str) -> str:
    """
    Parse location requirement from text.

    Returns: 'remote', 'hybrid', or 'onsite'
    """
    text_lower = text.lower()

    if 'remote' in text_lower or 'work from anywhere' in text_lower:
        return 'remote'
    elif 'hybrid' in text_lower:
        return 'hybrid'
    elif 'onsite' in text_lower or 'on-site' in text_lower or 'in office' in text_lower:
        return 'onsite'

    return 'remote'  # Default to remote


def parse_compensation(text: str) -> Dict:
    """
    Parse compensation information from text.

    Handles formats like:
    - $150-180k
    - $150k-$180k
    - $185K/yr - $225K/yr
    - 150k-180k
    - 0.5-1.0%
    - 0.5%-1%

    Returns: Dict with comp_min, comp_max, equity_min, equity_max
    """
    comp = {
        'comp_min': None,
        'comp_max': None,
        'equity_min': None,
        'equity_max': None
    }

    # Look for salary patterns (case-insensitive, handles /yr, /year suffixes)
    # Patterns: $150k-$180k, $150-180k, $185K/yr - $225K/yr, 150k-180k
    salary_patterns = [
        r'\$(\d+)[kK](?:/yr|/year)?\s*[-–]\s*\$?(\d+)[kK](?:/yr|/year)?',  # $185K/yr - $225K/yr
        r'\$(\d+)[-–]\$?(\d+)[kK]',  # $150-180k or $150-$180k
        r'(\d+)[kK][-–](\d+)[kK]',  # 150k-180k
    ]

    for pattern in salary_patterns:
        salary_matches = re.findall(pattern, text, re.IGNORECASE)
        if salary_matches:
            first_match = salary_matches[0]
            comp['comp_min'] = int(first_match[0]) * 1000
            comp['comp_max'] = int(first_match[1]) * 1000
            break

    # Look for equity patterns like "0.5-1.0%" or "0.5%-1%"
    equity_pattern = r'(\d+\.?\d*)%?[-–](\d+\.?\d*)%'
    equity_matches = re.findall(equity_pattern, text)

    if equity_matches:
        first_match = equity_matches[0]
        comp['equity_min'] = float(first_match[0])
        comp['equity_max'] = float(first_match[1])

    return comp


def scrape_work_at_startup() -> List[Dict]:
    """
    Scrape YC Work at a Startup for engineering roles.

    Uses Playwright for JavaScript rendering since jobs load dynamically.

    Returns: List of role dicts
    """
    roles = []

    try:
        from playwright.sync_api import sync_playwright
        import time

        url = "https://www.workatastartup.com/companies"
        params = {
            'role': 'engineering',
            'jobType': 'fulltime',
            'sortBy': 'created_desc',
            'layout': 'list-compact',
        }

        # Build full URL with query params
        query_string = '&'.join(f"{k}={v}" for k, v in params.items())
        full_url = f"{url}?{query_string}"

        logger.info("Scraping %s", full_url)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()

                # Navigate and wait for content to load
                page.goto(full_url, wait_until='networkidle')
                time.sleep(3)  # Give extra time for JS to render

                # Try multiple possible selectors for job cards
                # YC sites often use custom React components
                job_cards_selectors = [
                    'div[class*="CompanyCard"]',
                    'div[class*="job"]',
                    'div[data-company]',
                    'a[href*="/companies/"]',
                    'div.company',
                ]

                job_cards = []
                for selector in job_cards_selectors:
                    job_cards = page.query_selector_all(selector)
                    if job_cards:
                        logger.info("Found %d cards with selector: %s", len(job_cards), selector)
                        break

                if not job_cards:
                    logger.warning("No job cards found - page structure may have changed")
                    return roles

                # Parse each job card
                for idx, card in enumerate(job_cards[:30]):  # Limit to 30 jobs
                    try:
                        # Get all text content from the card
                        card_text = card.inner_text()
                        lines = [line.strip() for line in card_text.split('\n') if line.strip()]

                        # YC Work at a Startup usually has company name as first non-empty line
                        # followed by batch (S21, W22, etc.)
                        company_name = "Unknown Company"
                        title = "Software Engineer"  # Default

                        # Try to extract company name from first few lines
                        # Usually format is: Company Name (W21) • Description
                        for i, line in enumerate(lines[:5]):
                            # Skip batch info alone (S21, W22, etc.)
                            if re.match(r'^[SW]\d{2}$', line):
                                continue
                            # Skip very long lines (likely descriptions)
                            if len(line) > 150:
                                continue
                            # Look for company name with batch like "Jiga (W21)"
                            batch_match = re.match(r'^(.+?)\s*\([SW]\d{2}\)', line)
                            if batch_match:
                                company_name = batch_match.group(1).strip()
                                break
                            # Otherwise, first suitable short line is likely company name
                            if i == 0 or (company_name == "Unknown Company" and len(line) < 50):
                                # Clean up: remove • and everything after it (tagline)
                                if '•' in line:
                                    company_name = line.split('•')[0].strip()
                                else:
                                    company_name = line
                                break

                        # Find job title - look for engineer/developer keywords
                        title_keywords = ['engineer', 'developer', 'backend', 'frontend', 'full stack', 'founding', 'software', 'technical']
                        for line in lines:
                            if any(keyword in line.lower() for keyword in title_keywords):
                                if 20 < len(line) < 100 and line != company_name:  # Reasonable title length
                                    title = line.strip()
                                    break

                        # Try to get the link to job/company page
                        link_elem = card.query_selector('a[href]')
                        jd_url = None
                        if link_elem:
                            href = link_elem.get_attribute('href')
                            if href:
                                jd_url = href if href.startswith('http') else f"https://www.workatastartup.com{href}"

                                # Try to extract company name from URL if it's a company page
                                # Format: /companies/company-name or /companies/company-name/jobs/...
                                if '/companies/' in href and company_name == "Unknown Company":
                                    parts = href.split('/companies/')
                                    if len(parts) > 1:
                                        company_slug = parts[1].split('/')[0]
                                        # Convert slug to title case (e.g., 'some-company' -> 'Some Company')
                                        company_name = company_slug.replace('-', ' ').title()

                        role = {
                            'company_name': company_name,
                            'title': title,
                            'jd_text': card_text[:2000],  # First 2000 chars as description
                            'jd_url': jd_url,
                            'source': 'work_at_startup',
                            'status': 'sourced',
                        }

                        # Parse tech stack from card text
                        tech_stack = parse_tech_stack(card_text)
                        if tech_stack:
                            role['tech_stack'] = tech_stack

                        # Parse location
                        location_req = parse_location_requirement(card_text)
                        role['location_requirement'] = location_req

                        # Parse compensation if available
                        comp_data = parse_compensation(card_text)
                        role.update(comp_data)

                        # Parse posted date (e.g., "2 days ago")
                        posted_data = parse_posted_ago(card_text)
                        if posted_data['posted_at']:
                            role['posted_at'] = posted_data['posted_at'].isoformat()
                        if posted_data['posted_ago_text']:
                            role['posted_ago_text'] = posted_data['posted_ago_text']

                        roles.append(role)
                        logger.info("Parsed: %s - %s", company_name, title)

                    except Exception as e:
                        logger.error("Error parsing job card %d: %s", idx, e)
                        continue

            finally:
                browser.close()

    except ImportError:
        logger.error("Playwright not installed. Install with: pip install playwright && playwright install chromium")
    except Exception as e:
        logger.error("Error scraping: %s", e)
        import traceback
        traceback.print_exc()

    return roles


def scrape_hn_hiring() -> List[Dict]:
    """
    Scrape Hacker News Who's Hiring thread for founding/early engineer roles.

    Uses the Algolia HN API to fetch the latest thread and comments.

    Returns: List of role dicts
    """
    roles = []

    try:
        # Get latest Who's Hiring thread via Algolia API
        url = "https://hn.algolia.com/api/v1/search_by_date"
        params = {
            'query': 'Ask HN: Who is hiring',
            'tags': 'story',
        }

        response = requests.get(url, params=params, timeout=30)
        threads = response.json().get('hits', [])

        if not threads:
            return []

        # Get comments from latest thread
        thread_id = threads[0]['objectID']
        comments_url = f"https://hn.algolia.com/api/v1/items/{thread_id}"
        response = requests.get(comments_url, timeout=30)
        thread = response.json()

        # Filter for founding/early engineer roles
        founding_keywords = ['founding', 'first engineer', 'early engineer',
                            '#1', 'employee #', 'seed stage', 'early stage']

        for comment in thread.get('children', [])[:100]:  # Limit to first 100 comments
            text = comment.get('text', '')

            # Check if this is a founding/early engineer role
            if not any(keyword in text.lower() for keyword in founding_keywords):
                continue

            try:
                role = parse_hn_job_posting(text)
                role['source'] = 'hn_who_is_hiring'
                role['status'] = 'sourced'
                roles.append(role)
            except Exception as e:
                logger.error("Error parsing HN comment: %s", e)
                continue

    except Exception as e:
        logger.error("Error scraping HN Who's Hiring: %s", e)

    return roles


def parse_hn_job_posting(text: str) -> Dict:
    """
    Parse a Hacker News job posting comment into structured data.

    HN posts typically follow a format like:
    Company Name | Role Title | Location | Details

    Returns: Dict with role information
    """
    role = {}

    # Try to extract company name (usually first line or starts with company name)
    lines = text.split('\n')
    first_line = lines[0] if lines else text[:100]

    # Parse compensation
    comp_data = parse_compensation(text)
    role.update(comp_data)

    # Parse tech stack
    role['tech_stack'] = parse_tech_stack(text)

    # Parse location
    role['location_requirement'] = parse_location_requirement(text)

    # Extract company and title from first line
    # Common format: "Company Name | Job Title | Location"
    parts = first_line.split('|')
    if len(parts) >= 2:
        role['company_name'] = parts[0].strip()
        role['title'] = parts[1].strip()
    else:
        # Fallback: use first 50 chars as company, next 50 as title
        role['company_name'] = first_line[:50].strip()
        role['title'] = 'Founding Engineer'

    # Use full text as job description
    role['jd_text'] = text

    # Try to find URL in text
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    if urls:
        role['company_website'] = urls[0]
        if len(urls) > 1:
            role['jd_url'] = urls[1]

    return role


def nightly_role_sourcing(db) -> Dict[str, int]:
    """
    Nightly job to source new roles from job boards.

    Args:
        db: Database session

    Returns: Dict with sourcing stats
    """
    from app.api.crud import create_role
    from app.schemas.role import RoleCreate

    stats = {
        'work_at_startup': 0,
        'hn_who_is_hiring': 0,
        'total_saved': 0,
        'errors': 0,
    }

    # Scrape Work at a Startup
    try:
        waas_roles = scrape_work_at_startup()
        stats['work_at_startup'] = len(waas_roles)

        for role_data in waas_roles:
            try:
                role = RoleCreate(**role_data)
                create_role(db, role)
                stats['total_saved'] += 1
            except Exception as e:
                logger.error("Error saving role: %s", e)
                stats['errors'] += 1
    except Exception as e:
        logger.error("Error in Work at a Startup scraping: %s", e)
        stats['errors'] += 1

    # Scrape HN Who's Hiring
    try:
        hn_roles = scrape_hn_hiring()
        stats['hn_who_is_hiring'] = len(hn_roles)

        for role_data in hn_roles:
            try:
                role = RoleCreate(**role_data)
                create_role(db, role)
                stats['total_saved'] += 1
            except Exception as e:
                logger.error("Error saving role: %s", e)
                stats['errors'] += 1
    except Exception as e:
        logger.error("Error in HN Who's Hiring scraping: %s", e)
        stats['errors'] += 1

    return stats
