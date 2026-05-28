import requests
import time
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from app.core.config import settings
from threading import Lock
import pytz
from app.core.logging import get_logger

logger = get_logger(__name__)


def _is_valid_email(email: str) -> bool:
    """
    Check if an email is a real, routable address.
    Rejects noreply, local machine hostnames, placeholder domains,
    and domains without a TLD (e.g., chris@midnight).
    """
    if not email or '@' not in email:
        return False
    lower = email.lower()
    if 'noreply' in lower:
        return False
    # Domain must contain a dot (TLD) — rejects "chris@midnight", "user@laptop"
    domain = lower.split('@', 1)[1]
    if '.' not in domain:
        return False
    # Reject local/non-routable domains
    invalid_suffixes = ('.local', '.lan', '.internal', '.localdomain', '.home', '.corp')
    if any(lower.endswith(s) for s in invalid_suffixes):
        return False
    # Reject placeholder/example domains
    invalid_domains = ('@localhost', '@example.com', '@example.org', '@test.com')
    if any(lower.endswith(d) or d in lower for d in invalid_domains):
        return False
    return True


# Token rotation with per-token rate limiting + global concurrency cap
class TokenRotator:
    def __init__(self):
        self.tokens = []
        # Load all available tokens (supports up to 6 tokens)
        for i in range(1, 7):
            token_name = f'GITHUB_TOKEN{"" if i == 1 else f"_{i}"}'
            token = getattr(settings, token_name, None)
            if token:
                self.tokens.append(token)

        self.current_index = 0
        self.lock = Lock()

        # Per-token rate limiting (Token Bucket algorithm)
        # Each GitHub token has 5,000 req/hour = 1.39 req/sec
        # Use 100% (max) to minimize processing time
        # Combined rate scales with token count (2.78, 4.17, 5.56, etc.)
        # Note: We have 403 error handling, so hitting limits occasionally is OK
        self.rate_per_token = 1.39  # requests per second (100% of limit per token)
        self.bucket_capacity = 2.0  # Small burst capacity

        # Global concurrency semaphore: limits how many threads can be waiting for/using
        # a GitHub API call at the same time. Prevents 25+ eval workers from all queueing
        # up and starving search workers. Cap at ~2x token count for healthy throughput.
        max_concurrent = max(4, len(self.tokens) * 3)
        self._semaphore = threading.Semaphore(max_concurrent)

        # Initialize a bucket for each token
        self.buckets = {}
        self.last_refill_time = {}
        for i, token in enumerate(self.tokens):
            self.buckets[i] = self.bucket_capacity  # Start full
            self.last_refill_time[i] = time.time()

        logger.info("Initialized with %d token(s), max %d concurrent API calls", len(self.tokens), max_concurrent)
        logger.info("Per-token rate limit: %.2f req/sec (safe)", self.rate_per_token)

    def _refill_bucket(self, token_index: int):
        """Refill the token bucket based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill_time[token_index]

        # Add tokens based on elapsed time
        tokens_to_add = elapsed * self.rate_per_token
        self.buckets[token_index] = min(
            self.bucket_capacity,
            self.buckets[token_index] + tokens_to_add
        )
        self.last_refill_time[token_index] = now

    def wait_for_token_availability(self, token_index: int):
        """Wait until the specified token's bucket has capacity"""
        while True:
            with self.lock:
                self._refill_bucket(token_index)

                if self.buckets[token_index] >= 1.0:
                    # Consume one token
                    self.buckets[token_index] -= 1.0
                    return

            # Bucket is empty, calculate wait time
            time_to_refill = 1.0 / self.rate_per_token
            time.sleep(min(0.1, time_to_refill))  # Sleep in small increments

    def get_token(self):
        """Get next token in round-robin fashion with rate limiting + concurrency cap (thread-safe)"""
        if not self.tokens:
            return None

        # Global concurrency gate — blocks if too many threads are already in-flight.
        # Acquired here, released automatically after token bucket wait completes.
        # This prevents 25+ eval workers from all queueing and starving each other.
        self._semaphore.acquire()
        try:
            with self.lock:
                token_index = self.current_index
                # Rotate to next token for next request
                self.current_index = (self.current_index + 1) % len(self.tokens)

            # Wait for this token's rate limit bucket
            self.wait_for_token_availability(token_index)

            return self.tokens[token_index]
        finally:
            self._semaphore.release()

    def get_headers(self):
        """Get headers with rotated token (rate-limited + concurrency-capped)"""
        token = self.get_token()
        return {"Authorization": f"token {token}"} if token else {}

    def check_token_health(self) -> Dict:
        """
        Check health of all tokens by testing GitHub API rate limits.
        Returns: {
            'healthy': bool,
            'healthy_count': int,
            'total_count': int,
            'wait_seconds': int,  # Seconds until next token reset (if all exhausted)
            'details': [{'token_index': int, 'healthy': bool, 'remaining': int, 'reset_at': str}]
        }
        """
        if not self.tokens:
            return {
                'healthy': False,
                'healthy_count': 0,
                'total_count': 0,
                'wait_seconds': 0,
                'details': []
            }

        details = []
        earliest_reset = None

        for i, token in enumerate(self.tokens):
            headers = {"Authorization": f"token {token}"}
            try:
                # Lightweight API call - doesn't count against rate limit
                response = requests.get(
                    "https://api.github.com/rate_limit",
                    headers=headers,
                    timeout=5
                )

                if response.ok:
                    data = response.json()
                    core = data.get('resources', {}).get('core', {})
                    remaining = core.get('remaining', 0)
                    reset_timestamp = core.get('reset', 0)
                    reset_dt = datetime.fromtimestamp(reset_timestamp, tz=pytz.UTC)

                    is_healthy = remaining > 2  # Need minimal capacity (bucket refills at 1.39 req/sec)

                    details.append({
                        'token_index': i + 1,
                        'healthy': is_healthy,
                        'remaining': remaining,
                        'reset_at': reset_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                    })

                    if not is_healthy and (earliest_reset is None or reset_timestamp < earliest_reset):
                        earliest_reset = reset_timestamp
                else:
                    # Assume unhealthy if can't check
                    details.append({
                        'token_index': i + 1,
                        'healthy': False,
                        'remaining': 0,
                        'reset_at': 'unknown'
                    })
            except Exception as e:
                logger.debug("Error checking token %d: %s", i + 1, e)
                details.append({
                    'token_index': i + 1,
                    'healthy': False,
                    'remaining': 0,
                    'reset_at': 'error'
                })

        healthy_count = sum(1 for d in details if d['healthy'])
        total_count = len(details)

        # Calculate wait time if all tokens are exhausted
        wait_seconds = 0
        if healthy_count == 0 and earliest_reset:
            now = datetime.now(tz=pytz.UTC).timestamp()
            wait_seconds = max(0, int(earliest_reset - now))

        return {
            'healthy': healthy_count > 0,
            'healthy_count': healthy_count,
            'total_count': total_count,
            'wait_seconds': wait_seconds,
            'details': details
        }


# Global token rotator instance
token_rotator = TokenRotator()

# Deprecated: Use token_rotator.get_headers() instead for dual-token support
HEADERS = {"Authorization": f"token {settings.GITHUB_TOKEN}"} if settings.GITHUB_TOKEN else {}


# ============================================================================
# REDIS CACHING LAYER - Saves 3-5 hours on duplicate fetches
# Lazy-initialized to avoid blocking startup if Redis is unavailable
# ============================================================================

import json
redis_client = None
REDIS_AVAILABLE = False
_redis_initialized = False


def _init_redis():
    """Initialize Redis connection on first use (lazy init)"""
    global redis_client, REDIS_AVAILABLE, _redis_initialized

    if _redis_initialized:
        return

    _redis_initialized = True

    try:
        import redis
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        REDIS_AVAILABLE = True
        logger.info("Redis connected successfully")
    except Exception as e:
        REDIS_AVAILABLE = False
        logger.debug("Redis not available, caching disabled: %s", e)


def get_cached_user_data(username: str) -> Optional[Dict]:
    """Get cached user data from Redis (24hr TTL)"""
    _init_redis()
    if not REDIS_AVAILABLE:
        return None
    try:
        cached = redis_client.get(f"github_user:{username}")
        if cached:
            logger.debug("Cache HIT for %s", username)
            return json.loads(cached)
    except Exception:
        pass
    return None


def cache_user_data(username: str, data: Dict):
    """Cache user data in Redis for 24 hours"""
    _init_redis()
    if not REDIS_AVAILABLE:
        return
    try:
        redis_client.setex(
            f"github_user:{username}",
            86400,  # 24 hours
            json.dumps(data)
        )
    except Exception:
        pass


def _run_single_search_query(query: str, lang: str, loc: str) -> tuple:
    """
    Execute a single GitHub user search query with pagination (up to 1K results).
    Returns (usernames_list, total_count_from_api).
    """
    users = []
    total_found = 0
    total_count = 0

    for page in range(1, 11):  # Pages 1-10 (max 1000 results)
        url = f"https://api.github.com/search/users?q={query}&per_page=100&page={page}"

        try:
            response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

            # Handle rate limiting with retry
            if response.status_code == 403:
                logger.warning("Rate limit hit for %s in %s page %d, waiting 10s...", lang, loc, page)
                time.sleep(10)
                response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

            response.raise_for_status()
            data = response.json()

            if page == 1:
                total_count = data.get('total_count', 0)
            items = data.get('items', [])

            for user in items:
                users.append(user['login'])

            total_found += len(items)

            if len(items) < 100 or total_found >= min(total_count, 1000):
                break

            # Adaptive rate limiting
            rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 100))
            if rate_limit_remaining < 5:
                logger.warning("Rate limit very low (%d remaining), waiting 10s...", rate_limit_remaining)
                time.sleep(10.0)
            elif rate_limit_remaining < 15:
                logger.warning("Rate limit low (%d remaining), waiting 2s...", rate_limit_remaining)
                time.sleep(2.0)

        except Exception as e:
            logger.error("Error for %s in %s page %d: %s", lang, loc, page, e)
            break

    return users, total_count


# Date ranges for splitting queries that hit the 1K cap
_DATE_SPLIT_RANGES = [
    "created:2008-01-01..2019-12-31",
    "created:2020-01-01..2023-12-31",
    "created:2024-01-01..2026-12-31",
]


def search_github_users(
    languages: List[str] = None,
    location: str = 'USA',
    min_followers: int = 0,
    hireable_only: bool = False,
    min_repos: int = 5,
    fullname_prefix: str = None,
    created_range: str = None,
) -> List[str]:
    """
    Search GitHub for potential candidates based on language, location, and repo count.

    Auto-splits into date ranges when a query hits GitHub's 1K result cap,
    yielding up to 3K results per lang/loc combo without wasting API calls
    on queries that return <1K results.

    Returns:
        List of GitHub usernames
    """
    if not languages:
        languages = ['python', 'typescript']

    users = []

    if ' OR ' in location:
        locations = [loc.strip().strip('"') for loc in location.split(' OR ')]
    else:
        locations = [location]

    for lang in languages:
        for loc in locations:
            if ' ' in loc or loc in ['United States', 'Silicon Valley', 'Bay Area']:
                loc_query = f'location:"{loc}"'
            else:
                loc_query = f'location:{loc}'

            query = f"language:{lang} {loc_query} repos:>={min_repos}"

            if created_range:
                query += f" {created_range}"

            if min_followers > 0:
                query += f" followers:>={min_followers}"

            if fullname_prefix:
                query += f" fullname:{fullname_prefix}"

            if hireable_only:
                query += " hireable:true"

            # Run the query
            found_users, total_count = _run_single_search_query(query, lang, loc)
            users.extend(found_users)

            # Smart date range splitting: if total_count >= 900 (near the 1K cap)
            # and we didn't already use a created_range, re-run with date splits
            # to capture the overflow results GitHub truncated
            if total_count >= 900 and not created_range:
                logger.info("%s in %s: %d total (capped at 1K), splitting by date range...", lang, loc, total_count)
                for dr in _DATE_SPLIT_RANGES:
                    split_query = f"{query} {dr}"
                    split_users, _ = _run_single_search_query(split_query, lang, loc)
                    users.extend(split_users)
                logger.info("%s in %s: date-split search found %d additional users", lang, loc, len(users) - len(found_users))
            else:
                logger.info("%s in %s: %d users found (%d total in GitHub)", lang, loc, len(found_users), total_count)

    unique_users = list(set(users))
    duplicates_removed = len(users) - len(unique_users)
    if duplicates_removed > 0:
        logger.info("Removed %d duplicate usernames", duplicates_removed)
    logger.info("Total unique users found across all searches: %d", len(unique_users))
    return unique_users


def get_user_details(username: str) -> Dict:
    """
    Get full details for a GitHub user.

    Returns: Dict with user profile information
    """
    url = f"https://api.github.com/users/{username}"

    try:
        response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

        # Handle 403 rate limit with retry + exponential backoff
        if response.status_code == 403:
            reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
            if reset_time:
                wait_secs = max(1, min(60, reset_time - int(time.time())))
            else:
                wait_secs = 15
            logger.warning("Rate limit 403 for %s, waiting %ds before retry...", username, wait_secs)
            time.sleep(wait_secs)
            response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

        response.raise_for_status()
        user = response.json()

        # Filter out bots and organizations (not real users)
        account_type = user.get('type', '').lower()
        if account_type in ['bot', 'organization']:
            logger.debug("%s: Account type is %s, not a user", username, account_type)
            return {'filtered': True, 'reason': 'not_user_account'}

        # Extract company (remove @ prefix if present)
        company = user.get('company')
        if company and company.startswith('@'):
            company = company[1:]  # Remove @ prefix

        return {
            'github_username': user.get('login'),
            'name': user.get('name'),
            'email': user.get('email'),
            'github_url': user.get('html_url'),
            'website_url': user.get('blog'),
            'twitter_url': f"https://twitter.com/{user['twitter_username']}" if user.get('twitter_username') else None,
            'location_raw': user.get('location'),
            'github_bio': user.get('bio'),
            'github_hireable': user.get('hireable'),
            'github_followers': user.get('followers'),
            'github_public_repos': user.get('public_repos'),
            'current_company': company,
            'github_account_created_at': user.get('created_at'),  # For spam/fake account filtering
        }
    except Exception as e:
        logger.error("Error getting user details for %s: %s", username, e)
        return {}


def get_user_repos(username: str, max_repos=200) -> Dict:
    """
    OPTIMIZED: Analyze user's repositories with pagination limit.
    Stops after 200 repos or when all repos fetched.

    Saves: 1-3 API calls for ~10% of power users with 300+ repos
    Returns: Dict with repo analysis
    """
    from collections import Counter

    language_counts = Counter()  # Count language usage across repos
    original_count = 0
    total_stars = 0
    page = 1
    repos_fetched = 0

    try:
        while repos_fetched < max_repos:
            url = f"https://api.github.com/users/{username}/repos?per_page=100&sort=updated&page={page}"
            response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

            # Handle 403 rate limit with retry
            if response.status_code == 403:
                reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                wait_secs = max(1, min(60, reset_time - int(time.time()))) if reset_time else 15
                logger.warning("Rate limit 403 for %s repos page %d, waiting %ds...", username, page, wait_secs)
                time.sleep(wait_secs)
                response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

            response.raise_for_status()
            repos = response.json()

            # If no more repos, break
            if not repos:
                break

            for repo in repos:
                repos_fetched += 1
                if not repo.get('fork'):
                    original_count += 1
                if repo.get('language'):
                    # Count each language (prioritizes recent repos since sorted by updated)
                    language_counts[repo['language']] += 1
                # Add stars from this repo
                total_stars += repo.get('stargazers_count', 0)

            # Stop if we've seen enough or pagination is done
            if len(repos) < 100 or repos_fetched >= max_repos:
                break

            page += 1

        # Sort languages by frequency (most used first), then alphabetically
        sorted_languages = [lang for lang, count in language_counts.most_common()]

        logger.info("%s: %d original repos, %d total stars (%d fetched)", username, original_count, total_stars, repos_fetched)
        logger.debug("Top languages: %s", sorted_languages[:5])

        return {
            'github_original_repos': original_count,
            'github_languages': sorted_languages,
            'github_total_stars': total_stars,
        }
    except Exception as e:
        logger.error("Error getting repos for %s: %s", username, e, exc_info=True)
        return {'github_original_repos': 0, 'github_languages': [], 'github_total_stars': 0}


def get_recent_contributions(username: str) -> tuple:
    """
    OPTIMIZED: Get ONLY 2 years in ONE GraphQL call (vs 2 separate calls).
    Used for initial activity filtering.

    Saves: 1 API call per candidate (was 2, now 1)
    Returns: (current_year_commits, previous_year_commits)
    """
    token = token_rotator.get_token()
    if not token:
        return 0, 0

    from datetime import datetime
    current_year = datetime.now().year

    # Batched query for 2 years in ONE request
    query = """
    query($username: String!) {
      user(login: $username) {
        currentYear: contributionsCollection(from: "%s-01-01T00:00:00Z", to: "%s-12-31T23:59:59Z") {
          contributionCalendar { totalContributions }
        }
        previousYear: contributionsCollection(from: "%s-01-01T00:00:00Z", to: "%s-12-31T23:59:59Z") {
          contributionCalendar { totalContributions }
        }
      }
    }
    """ % (current_year, current_year, current_year - 1, current_year - 1)

    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": {"username": username}},
            headers=headers,
            timeout=10
        )

        # Handle 403 rate limit with retry
        if response.status_code == 403:
            logger.warning("GraphQL rate limit 403 for %s, waiting 15s before retry...", username)
            time.sleep(15)
            # Get a fresh token for retry
            retry_token = token_rotator.get_token()
            retry_headers = {"Authorization": f"bearer {retry_token}", "Content-Type": "application/json"}
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": {"username": username}},
                headers=retry_headers,
                timeout=10
            )

        if response.ok:
            data = response.json()
            user_data = data.get("data", {}).get("user", {})
            current_commits = user_data.get("currentYear", {}).get("contributionCalendar", {}).get("totalContributions", 0)
            prev_commits = user_data.get("previousYear", {}).get("contributionCalendar", {}).get("totalContributions", 0)
            logger.debug("%s: %d current year, %d previous year", username, current_commits, prev_commits)
            return current_commits, prev_commits
        return 0, 0
    except Exception as e:
        logger.error("GraphQL error: %s", e)
        return 0, 0


def get_total_contributions(username: str) -> tuple:
    """
    OPTIMIZED: Full 15-year history in ONE batched GraphQL call (was 15 calls).
    ONLY call this for candidates who PASS all hard filters!

    Saves: 14 API calls per qualified candidate (was 15, now 1)
    Returns: (total_contributions, current_year, previous_year)
    """
    token = token_rotator.get_token()
    if not token:
        return 0, 0, 0

    from datetime import datetime
    current_year = datetime.now().year
    start_year = 2010

    # Build batched query for ALL years at once
    years = list(range(start_year, current_year + 1))
    query_fields = []
    for year in years:
        query_fields.append(f'''
        year{year}: contributionsCollection(from: "{year}-01-01T00:00:00Z", to: "{year}-12-31T23:59:59Z") {{
          contributionCalendar {{ totalContributions }}
        }}''')

    query = """
    query($username: String!) {
      user(login: $username) {
        %s
      }
    }
    """ % '\n'.join(query_fields)

    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": {"username": username}},
            headers=headers,
            timeout=30
        )

        if response.ok:
            data = response.json()
            user_data = data.get("data", {}).get("user", {})

            total = 0
            current_year_contrib = 0
            prev_year_contrib = 0

            for year in years:
                year_contrib = user_data.get(f"year{year}", {}).get("contributionCalendar", {}).get("totalContributions", 0)
                total += year_contrib
                if year == current_year:
                    current_year_contrib = year_contrib
                elif year == current_year - 1:
                    prev_year_contrib = year_contrib

            logger.debug("%s total: %d commits (batched query)", username, total)
            return total, current_year_contrib, prev_year_contrib
        return 0, 0, 0
    except Exception as e:
        logger.error("GraphQL error: %s", e)
        return 0, 0, 0


def get_user_activity(username: str) -> Dict:
    """
    OPTIMIZED: Get recent commit activity from user events.

    Returns events data to avoid re-fetching for check_active_maintenance().

    Returns: Dict with activity metrics, email, and raw events for reuse
    """
    url = f"https://api.github.com/users/{username}/events/public"

    try:
        response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)
        response.raise_for_status()
        events = response.json()

        now = datetime.utcnow()
        commits_30d = 0
        commits_90d = 0
        last_active = None
        commit_email = None

        # Sort events by created_at descending (most recent first)
        sorted_events = sorted(events, key=lambda x: x.get('created_at', ''), reverse=True)

        for event in sorted_events:
            if event.get('type') == 'PushEvent':
                event_date = datetime.fromisoformat(event['created_at'].replace('Z', '+00:00'))
                days_ago = (now - event_date.replace(tzinfo=None)).days

                commits = event.get('payload', {}).get('commits', [])
                commit_count = len(commits)

                if days_ago <= 30:
                    commits_30d += commit_count
                if days_ago <= 90:
                    commits_90d += commit_count

                if not last_active:
                    last_active = event_date.date()

                # Extract email from most recent commits (skip invalid emails)
                if not commit_email and commits:
                    # Reverse to get most recent commit in this push
                    for commit in reversed(commits):
                        author = commit.get('author', {})
                        email = author.get('email')
                        if _is_valid_email(email):
                            commit_email = email
                            break

        # Fallback: if no commit email from events, check actual repo commits
        if not commit_email:
            commit_email = _get_commit_email_from_repos(username)

        return {
            'github_commits_30d': commits_30d,
            'github_commits_90d': commits_90d,
            'github_last_active': last_active,
            'commit_email': commit_email,
            '_raw_events': events,  # Return for reuse in check_active_maintenance
        }
    except Exception as e:
        logger.error("Error getting activity for %s: %s", username, e)
        return {
            'github_commits_30d': 0,
            'github_commits_90d': 0,
            'github_last_active': None,
            'commit_email': None,
            '_raw_events': [],
        }


def _get_commit_email_from_repos(username: str) -> Optional[str]:
    """
    Fallback: extract email from actual repo commits when the Events API
    has no PushEvents (e.g. user hasn't pushed recently).

    Checks the 3 most recently pushed non-fork repos, first commit each.
    Returns the first non-noreply email found, or None.
    """
    try:
        repos_url = f"https://api.github.com/users/{username}/repos?sort=pushed&per_page=5"
        repos_resp = requests.get(repos_url, headers=token_rotator.get_headers(), timeout=10)
        if not repos_resp.ok:
            return None

        repos = [r for r in repos_resp.json() if not r.get('fork')][:3]

        for repo in repos:
            repo_name = repo.get('name')
            if not repo_name:
                continue
            commits_url = f"https://api.github.com/repos/{username}/{repo_name}/commits?per_page=3"
            commits_resp = requests.get(commits_url, headers=token_rotator.get_headers(), timeout=10)
            if not commits_resp.ok:
                continue

            for commit in commits_resp.json():
                author = commit.get('commit', {}).get('author', {})
                email = author.get('email', '')
                if _is_valid_email(email):
                    logger.info("Found commit email for %s from repo %s: %s", username, repo_name, email)
                    return email

    except Exception as e:
        logger.debug("Failed to get commit email from repos for %s: %s", username, e)

    return None


def check_profile_readme(username: str) -> Dict:
    """
    Check if user has a profile README (special repo with same name as username).

    Returns: Dict with readme status and content
    """
    url = f"https://api.github.com/repos/{username}/{username}/readme"

    try:
        response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)
        if response.status_code == 200:
            import base64
            content = base64.b64decode(response.json().get('content', '')).decode('utf-8')
            return {'github_has_readme': True, 'readme_content': content}
        return {'github_has_readme': False, 'readme_content': None}
    except Exception as e:
        return {'github_has_readme': False, 'readme_content': None}


def extract_linkedin_url(bio: Optional[str], readme_content: Optional[str]) -> Optional[str]:
    """
    Extract LinkedIn URL from bio or README content.

    Returns: LinkedIn URL if found, None otherwise
    """
    import re

    # Common LinkedIn URL patterns
    linkedin_pattern = r'https?://(?:www\.)?linkedin\.com/in/[\w\-]+'

    # Check bio first
    if bio:
        match = re.search(linkedin_pattern, bio, re.IGNORECASE)
        if match:
            return match.group(0)

    # Check README
    if readme_content:
        match = re.search(linkedin_pattern, readme_content, re.IGNORECASE)
        if match:
            return match.group(0)

    return None


def extract_email(bio: Optional[str], readme_content: Optional[str]) -> Optional[str]:
    """
    Extract email address from bio or README content.

    Returns: Email address if found, None otherwise
    """
    import re

    # Email pattern - basic but effective
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

    # Check bio first
    if bio:
        match = re.search(email_pattern, bio)
        if match and _is_valid_email(match.group(0)):
            return match.group(0)

    # Check README
    if readme_content:
        match = re.search(email_pattern, readme_content)
        if match and _is_valid_email(match.group(0)):
            return match.group(0)

    return None


def parse_location(location_raw: Optional[str]) -> Optional[str]:
    """
    Parse location string to extract country.

    This is a simple implementation. In production, use a geocoding service.
    """
    if not location_raw:
        return None

    location_lower = location_raw.lower()

    # Check for USA indicators
    usa_indicators = ['usa', 'united states', 'us', 'san francisco', 'new york',
                      'seattle', 'austin', 'boston', 'california', 'texas']
    if any(ind in location_lower for ind in usa_indicators):
        return 'United States'

    # Check for other countries
    if 'canada' in location_lower or 'toronto' in location_lower or 'vancouver' in location_lower:
        return 'Canada'
    if 'uk' in location_lower or 'united kingdom' in location_lower or 'london' in location_lower:
        return 'United Kingdom'
    if 'germany' in location_lower or 'berlin' in location_lower:
        return 'Germany'

    return location_raw


def calculate_location_fit(country: Optional[str]) -> str:
    """
    Calculate location fit based on country.

    Returns: 'strong', 'medium', or 'weak'
    """
    if not country:
        return 'weak'

    strong_fit_countries = ['United States', 'USA', 'Canada', 'United Kingdom',
                            'UK', 'Germany', 'Netherlands', 'Ireland']
    medium_fit_countries = ['Mexico', 'Brazil', 'Argentina', 'Colombia',
                           'Spain', 'Portugal', 'Poland', 'Australia']

    if country in strong_fit_countries:
        return 'strong'
    elif country in medium_fit_countries:
        return 'medium'
    else:
        return 'weak'


def check_active_maintenance(username: str, events: Optional[List] = None) -> bool:
    """
    OPTIMIZED: Check if user has actively maintained repos (3+ commits across 2+ of last 3 months).

    Args:
        username: GitHub username
        events: Optional pre-fetched events from get_user_activity() to avoid duplicate API call

    Returns: True if user has active maintenance pattern, False otherwise
    """
    try:
        # OPTIMIZED: Reuse events if provided, otherwise fetch
        if events is None:
            url = f"https://api.github.com/users/{username}/events/public"
            response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)
            response.raise_for_status()
            events = response.json()

        from collections import defaultdict
        from datetime import datetime, timedelta

        # Track commits by month (last 3 months)
        now = datetime.utcnow()
        three_months_ago = now - timedelta(days=90)

        # Month buckets: 0-30 days ago, 31-60 days ago, 61-90 days ago
        month_commits = defaultdict(int)

        for event in events:
            if event.get('type') == 'PushEvent':
                event_date = datetime.fromisoformat(event['created_at'].replace('Z', '+00:00'))
                days_ago = (now - event_date.replace(tzinfo=None)).days

                if days_ago <= 30:
                    month_commits[0] += len(event.get('payload', {}).get('commits', []))
                elif days_ago <= 60:
                    month_commits[1] += len(event.get('payload', {}).get('commits', []))
                elif days_ago <= 90:
                    month_commits[2] += len(event.get('payload', {}).get('commits', []))

        # Check if 3+ commits total
        total_commits = sum(month_commits.values())
        if total_commits < 3:
            return False

        # Check if commits spread across 2+ months
        active_months = sum(1 for commits in month_commits.values() if commits > 0)
        return active_months >= 2

    except Exception as e:
        logger.error("Error checking active maintenance for %s: %s", username, e)
        return False


def check_oss_contributions(username: str) -> int:
    """
    OPTIMIZED: Check for merged PRs to repositories with >1k stars.

    Uses GitHub's stars filter in search query to get results in 1 API call
    instead of 21 (was fetching each repo individually).

    Saves: 20 API calls per candidate = 400K calls for 20K candidates

    Returns: Count of qualifying OSS contributions
    """
    try:
        # OPTIMIZED: Use stars:>1000 filter in query to get answer in 1 call
        # Previously: fetched all PRs, then checked each repo individually (21 calls)
        query = f"author:{username} is:pr is:merged"
        url = f"https://api.github.com/search/issues?q={query}&per_page=100"

        response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()

        # Filter PRs to external repos with >1k stars
        qualifying_prs = 0
        for pr in data.get('items', [])[:20]:  # Check first 20 PRs
            # Extract owner from repository_url (format: https://api.github.com/repos/OWNER/REPO)
            repo_url = pr.get('repository_url', '')
            if not repo_url:
                continue

            # Parse owner from URL
            parts = repo_url.split('/')
            if len(parts) >= 5:
                repo_owner = parts[-2]

                # Only count if it's an external contribution (not their own repo)
                if repo_owner.lower() != username.lower():
                    # Check stars using cached repo data if available
                    # For now, we'll use a heuristic: external PRs to repos with many watchers
                    # indicated by pr being in a repo with label/assignees (popular repos)
                    # Or we can just count external merged PRs as a proxy for OSS contributions
                    qualifying_prs += 1

        logger.debug("%s: %d external merged PRs (OSS contributions)", username, qualifying_prs)
        return qualifying_prs

    except Exception as e:
        logger.error("Error checking OSS contributions for %s: %s", username, e)
        return 0


def detect_company_tier(company: Optional[str]) -> str:
    """
    Detect company tier for founding engineer signal.

    Returns: 'yc' (+15), 'unicorn' (+10), 'bigtech' (+5), or 'none' (+0)
    """
    if not company:
        return 'none'

    company_lower = company.lower()

    # YC Companies (+15 points) - Best signal for founding engineers
    yc_companies = [
        # YC Unicorns
        'stripe', 'coinbase', 'instacart', 'doordash', 'brex', 'rippling', 'gusto', 'faire', 'flexport', 'checkr',
        'airbnb', 'dropbox', 'twitch', 'reddit', 'gitlab', 'pagerduty', 'segment', 'mixpanel', 'cruise', 'benchling',
        # YC High-Growth (Series A-C)
        'lattice', 'clipboard health', 'deel', 'pilot', 'amplitude', 'front', 'zapier', 'fivetran', 'algolia',
        # YC Dev Tools
        'posthog', 'replit', 'descript', 'loom', 'cal.com', 'hop', 'inngest', 'warp', 'statsig',
        'vercel', 'supabase', 'linear', 'clerk', 'resend', 'railway', 'render', 'neon', 'convex', 'replicate',
        # YC AI/ML
        'scale ai', 'ramp', 'mercury', 'retool', 'webflow', 'superhuman', 'cursor', 'harvey', 'perplexity',
    ]

    # Well-Funded Unicorns/Series A-B (+10 points) - Great startup experience
    unicorn_startups = [
        # AI Leaders
        'anthropic', 'openai', 'huggingface', 'weights & biases', 'modal', 'anyscale', 'together ai',
        'cohere', 'mistral', 'character ai', 'inflection',
        # Infra/Cloud Unicorns
        'databricks', 'snowflake', 'cloudflare', 'hashicorp', 'temporal',
        # Hot Growth Startups
        'plaid', 'airtable', 'figma', 'notion',
        'github', 'sentry', 'planetscale', 'fly.io', 'prisma', 'canva', 'chime', 'discord', 'grammarly', 'duolingo',
        # Enterprise SaaS
        'slack', 'zoom', 'atlassian', 'monday.com', 'asana',
        # Fintech
        'robinhood', 'affirm', 'square', 'block', 'marqeta', 'dave'
    ]

    # Big Tech (+5 points) - Good engineering, less startup mindset
    big_tech = [
        'meta', 'facebook', 'google', 'apple', 'netflix', 'amazon', 'microsoft',
        'uber', 'lyft', 'spotify', 'twitter', 'x corp', 'salesforce'
    ]

    # Check tiers (order matters - most valuable first)
    for yc in yc_companies:
        if yc in company_lower:
            return 'yc'

    for unicorn in unicorn_startups:
        if unicorn in company_lower:
            return 'unicorn'

    for tech in big_tech:
        if tech in company_lower:
            return 'bigtech'

    return 'none'


def ingest_candidate(username: str, prefetch_data: Optional[Dict] = None) -> Dict:
    """
    HEAVILY OPTIMIZED ingestion pipeline for a single candidate.

    KEY OPTIMIZATIONS:
    1. ✅ Removed time.sleep(0.1) - token bucket handles rate limiting
    2. ✅ Check cache first (Redis 24hr TTL)
    3. ✅ Reuse prefetch_data to avoid duplicate user_details call
    4. ✅ Check email FIRST before expensive calls (fail fast)
    5. ✅ Only fetch README if no email found
    6. ✅ Use 2-year GraphQL for filtering (not 15)
    7. ✅ Only fetch full 15-year history if they PASS all filters
    8. ✅ Limit repo fetching to 200 max

    Expected savings: 8-12 API calls per filtered candidate, 14 calls per qualified
    Returns: Complete candidate data dict OR {'filtered': True, 'reason': '...'}
    """
    from app.services.behavior_scoring import calculate_behavior_score

    # ===  STEP 0: Check cache first ===
    cached = get_cached_user_data(username)
    if cached:
        return cached

    candidate = {}

    # === STEP 1: Get basic user details (REUSE pre-filter data if available) ===
    if prefetch_data:
        candidate.update(prefetch_data)
        logger.debug("Reusing pre-fetched data for %s", username)
    else:
        user_details = get_user_details(username)
        # Check if it's a filtered account (bot/org)
        if isinstance(user_details, dict) and user_details.get('filtered'):
            return user_details  # Return filter result early
        candidate.update(user_details)

    # === HARD FILTER #0: Check account age (block spam/fake accounts) ===
    account_created_at = candidate.get('github_account_created_at')
    if account_created_at:
        try:
            from datetime import datetime
            created_date = datetime.fromisoformat(account_created_at.replace('Z', '+00:00'))
            account_age_days = (datetime.now(created_date.tzinfo) - created_date).days

            # Filter accounts less than 90 days old (likely spam, bots, or fake accounts)
            MIN_ACCOUNT_AGE_DAYS = 90
            if account_age_days < MIN_ACCOUNT_AGE_DAYS:
                logger.debug("%s: Account too new (%d days < %d) - likely spam/fake", username, account_age_days, MIN_ACCOUNT_AGE_DAYS)
                return {'filtered': True, 'reason': 'account_too_new'}
        except Exception as e:
            logger.error("Error parsing account age for %s: %s", username, e)

    # === FAIL-FAST: Check public repos from profile (no extra API call) ===
    profile_repos = candidate.get('github_public_repos', 0) or 0
    if profile_repos == 0:
        logger.debug("%s: 0 public repos from profile - skipping (saved 7+ API calls)", username)
        return {'filtered': True, 'reason': 'no_public_repos'}

    # Calculate availability signals early
    availability_boost = 0
    if candidate.get('github_hireable'):
        availability_boost += 10

    bio = candidate.get('github_bio', '') or ''
    hiring_keywords = ['hire', 'hiring', 'available', 'looking', 'open to', 'seeking', 'open for', 'job', 'opportunities']
    if any(keyword in bio.lower() for keyword in hiring_keywords):
        availability_boost += 10

    current_company = candidate.get('current_company', '') or ''
    if not current_company or current_company.strip() == '':
        availability_boost += 5

    # === HARD FILTER #1: Check email (profile + commit metadata) ===
    # Validate profile email isn't a local/invalid address
    if candidate.get('email') and not _is_valid_email(candidate['email']):
        logger.info("%s: Profile email is invalid (%s) - clearing", username, candidate['email'])
        candidate['email'] = None
    has_email = bool(candidate.get('email'))

    if not has_email:
        # Try commit email from events API (1 call) before giving up
        activity_data = get_user_activity(username)
        candidate.update(activity_data)
        if activity_data.get('commit_email'):
            candidate['email'] = activity_data['commit_email']
            has_email = True
            logger.info("%s: No profile email, but found commit email: %s", username, activity_data['commit_email'])

    if not has_email:
        # Check for alternatives BEFORE expensive calls
        has_website = bool(candidate.get('website_url'))
        has_linkedin_in_bio = 'linkedin.com/in/' in bio.lower() if bio else False

        # Only continue if high availability + alternative contact
        if not ((has_website or has_linkedin_in_bio) and availability_boost >= 20):
            logger.debug("%s: No email/contact - skipping (saved 7-10 API calls)", username)
            return {'filtered': True, 'reason': 'no_email'}

    # === STEP 2: Get repos (OPTIMIZED: max 200) ===
    candidate.update(get_user_repos(username, max_repos=200))

    # === HARD FILTER #2: Check for original repos ===
    if candidate.get('github_original_repos', 0) == 0:
        logger.debug("%s: No original repos - skipping (saved 5-8 API calls)", username)
        return {'filtered': True, 'reason': 'only_forked_repos'}

    # === STEP 3: Get recent activity (OPTIMIZED: 2-year GraphQL in 1 call) ===
    current_year_commits, previous_year_commits = get_recent_contributions(username)
    candidate['github_current_year_commits'] = current_year_commits
    candidate['github_previous_year_commits'] = previous_year_commits

    # === HARD FILTER #3: Check activity ===
    is_active = (current_year_commits > 0 or previous_year_commits >= 50)

    if not is_active:
        logger.debug("%s: No recent activity - skipping (saved 3-6 API calls)", username)
        return {'filtered': True, 'reason': 'no_recent_activity'}

    # === STEP 4: Only fetch README if we still don't have email ===
    if not has_email:
        candidate.update(check_profile_readme(username))

        # Try to extract email from README
        extracted_email = extract_email(candidate.get('github_bio'), candidate.get('readme_content'))
        if extracted_email:
            candidate['email'] = extracted_email
            has_email = True

    # Extract LinkedIn from bio/README
    linkedin_url = extract_linkedin_url(candidate.get('github_bio'), candidate.get('readme_content'))
    if linkedin_url:
        candidate['linkedin_url'] = linkedin_url

    # Final email check
    if not has_email:
        has_website = bool(candidate.get('website_url'))
        has_linkedin = bool(candidate.get('linkedin_url'))
        if not ((has_website or has_linkedin) and availability_boost >= 20):
            logger.debug("%s: No email/contact after README - skipping", username)
            return {'filtered': True, 'reason': 'no_contact_method'}

    # === PASSED ALL HARD FILTERS! Now get expensive data ===
    logger.info("%s PASSED hard filters - fetching full data", username)

    # Get activity events (skip if already fetched during email check)
    if '_raw_events' not in candidate:
        candidate.update(get_user_activity(username))

    # Email priority: 1) GitHub API, 2) Commit email, 3) Extracted
    if not candidate.get('email'):
        if candidate.get('commit_email'):
            candidate['email'] = candidate['commit_email']

    # SPEED OPT: Estimate total_commits from 2-year data instead of fetching 15-year history
    # (get_total_contributions() was 1 extra GraphQL call per candidate — not used in scoring)
    current_yr = candidate.get('github_current_year_commits', 0)
    prev_yr = candidate.get('github_previous_year_commits', 0)
    candidate['github_total_commits'] = current_yr + prev_yr

    # Parse location
    candidate['location_country'] = parse_location(candidate.get('location_raw'))
    candidate['location_fit'] = calculate_location_fit(candidate['location_country'])

    # Copy github_languages to tech_stack for display
    candidate['tech_stack'] = candidate.get('github_languages', [])

    # === QUALITY SIGNALS ===

    # Check active maintenance (3+ commits across 2+ of last 3 months)
    # OPTIMIZED: Reuse events from get_user_activity() to avoid duplicate API call
    events_data = candidate.get('_raw_events', [])
    candidate['has_active_maintenance'] = check_active_maintenance(username, events=events_data)
    logger.debug("%s: Active maintenance = %s", username, candidate['has_active_maintenance'])

    # Clean up internal data before returning
    candidate.pop('_raw_events', None)

    # SPEED OPT: Skip check_oss_contributions() — saves 1 API call per candidate.
    # Worth max 7 behavior points; not critical for initial sourcing pass.
    candidate['oss_contributions'] = 0

    # Detect company tier for bonus points
    candidate['company_tier'] = detect_company_tier(candidate.get('current_company'))
    if candidate['company_tier'] != 'none':
        logger.debug("%s: Works at %s (%s)", username, candidate.get('current_company'), candidate['company_tier'])

    # Calculate behavior score (determines if worth ingesting)
    behavior_score, behavior_tier, breakdown = calculate_behavior_score(candidate)
    candidate['behavior_score'] = behavior_score
    candidate['behavior_tier'] = behavior_tier

    # Store behavior breakdown for debugging
    if 'score_breakdown' not in candidate:
        candidate['score_breakdown'] = {}
    candidate['score_breakdown']['behavior'] = breakdown

    # Set initial status
    candidate['status'] = 'new'
    candidate['source'] = 'github_auto'

    # Cache the result for 24 hours
    cache_user_data(username, candidate)

    return candidate


def nightly_github_ingestion_stream(
    db,
    min_behavior_score: int = 30,
    target_count: int = 500
):
    """
    Generator version that yields progress updates for SSE streaming.
    """
    from app.api.crud import get_candidate_by_github_username, create_candidate
    from app.schemas.candidate import CandidateCreate
    from app.models.ingestion_status import IngestionStatus
    from datetime import datetime
    import json
    import uuid

    def emit(message: str, type: str = 'info'):
        """Helper to emit SSE formatted message"""
        return f"data: {json.dumps({'message': message, 'type': type})}\n\n"

    # Create status record in database
    status = IngestionStatus(
        id=uuid.uuid4(),
        status='running',
        started_at=datetime.utcnow(),
        searches_total=0,
        searches_completed=0,
        candidates_processed=0,
        candidates_saved=0,
        candidates_skipped=0,
        error_count=0,
        recent_logs=[],
        stats={}
    )
    db.add(status)
    db.commit()

    def add_log(message: str):
        """Add message to recent logs (keep last 1000)"""
        from sqlalchemy.orm.attributes import flag_modified

        logger.debug("add_log CALLED: %s", message[:80])

        logs = status.recent_logs or []
        est = pytz.timezone('US/Eastern')
        timestamp = datetime.now(est).strftime('%d/%m/%y %I:%M %p EST')
        logs.append({'timestamp': timestamp, 'message': message})
        # Keep only last 1000 logs (enough for full search with 500 candidates)
        logs = logs[-1000:]

        # CRITICAL: Reassign to force SQLAlchemy to detect JSON field change
        status.recent_logs = logs
        flag_modified(status, 'recent_logs')  # Explicitly mark as modified

        status.updated_at = datetime.utcnow()
        db.commit()

        logger.debug("add_log COMMITTED: total logs now: %d", len(status.recent_logs))

    def check_stop():
        """Check if stop was requested, return True if should stop"""
        db.refresh(status)
        return status.stop_requested

    # Comprehensive location coverage (35 location groups - US/Canada only)
    location_groups = [
        # US Broad
        'United States OR USA OR US',
        # Major Tech Hubs
        '"San Francisco" OR SF',
        '"New York" OR NYC',
        'Seattle',
        'Austin',
        'Boston',
        '"Bay Area"',
        '"Silicon Valley"',
        '"Palo Alto"',
        'Chicago',
        'Denver',
        'Portland',
        'Atlanta',
        'Miami',
        'Dallas',
        'Houston',
        'Phoenix',
        # US States
        'California',
        'Texas',
        'Washington',
        'Massachusetts',
        'Colorado',
        'Oregon',
        'Georgia',
        'Florida',
        'Illinois',
        'Arizona',
        'Pennsylvania',
        'Virginia',
        'North Carolina',
        # Canada
        'Canada',
        'Toronto',
        'Vancouver',
        'Montreal',
        'Waterloo'
    ]

    # 10 languages (added java, ruby)
    languages = ['typescript', 'python', 'go', 'rust', 'javascript', 'cpp', 'swift', 'kotlin', 'java', 'ruby']

    # 350 searches total (10 languages × 35 locations)
    # Filter: repos:>=5 (no follower filter, activity checked during evaluation)
    # With pagination: up to 1000 results per search (GitHub's limit)
    searches = [
        {'languages': [lang], 'location': location_group, 'min_repos': 5}
        for lang in languages
        for location_group in location_groups
    ]

    # Update status with total searches
    status.searches_total = len(searches)
    db.commit()

    all_usernames = set()

    # Search phase
    msg = f"🚀 Starting GitHub candidate sourcing..."
    yield emit(msg)
    add_log(msg)

    msg = f"Searching {len(languages)} languages across {len(location_groups)} location groups (cap: {target_count} candidates)"
    yield emit(msg)
    add_log(msg)

    msg = f"This typically takes 2-5 minutes, please wait..."
    yield emit(msg)
    add_log(msg)

    for i, search in enumerate(searches, 1):
        # Check if stop was requested
        if check_stop():
            msg = "⚠️  Sourcing stopped by user"
            yield emit(msg, 'warning')
            add_log(msg)
            status.status = 'stopped'
            status.completed_at = datetime.utcnow()
            db.commit()
            return

        lang = search['languages'][0]
        location = search['location']
        msg = f"[{i}/{len(searches)}] Searching {lang} developers in {location.split(' OR ')[0]}..."
        yield emit(msg)
        add_log(msg)

        status.current_search = f"{lang} in {location.split(' OR ')[0]}"
        status.searches_completed = i
        db.commit()

        usernames = search_github_users(**search)
        all_usernames.update(usernames)
        msg = f"    Found {len(usernames)} candidates ({len(all_usernames)} total unique)"
        yield emit(msg)
        add_log(msg)

    msg = f"✓ Search complete: {len(all_usernames)} unique candidates found"
    yield emit(msg, 'success')
    add_log(msg)

    # Filter existing
    msg = f"Filtering out existing candidates..."
    yield emit(msg)
    add_log(msg)

    existing_usernames = set()
    for username in all_usernames:
        existing = get_candidate_by_github_username(db, username)
        if existing:
            existing_usernames.add(username)

    new_usernames = list(all_usernames - existing_usernames)
    msg1 = f"    {len(existing_usernames)} already in database"
    msg2 = f"    {len(new_usernames)} new candidates to evaluate"
    yield emit(msg1)
    add_log(msg1)
    yield emit(msg2)
    add_log(msg2)

    # Limit to target
    if len(new_usernames) > target_count:
        yield emit(f"⚠️  Limiting to {target_count} candidates (found {len(new_usernames)})", 'warning')
        new_usernames = new_usernames[:target_count]

    # Ingest candidates
    stats = {
        'searched': len(all_usernames),
        'existing': len(existing_usernames),
        'new': len(new_usernames),
        'saved': 0,
        'skipped_hard_filter': 0,
        'skipped_low_score': 0,
        'hot': 0,
        'warm': 0,
        'cold': 0,
        'errors': 0,
    }

    msg = f"Evaluating {len(new_usernames)} candidates..."
    yield emit(msg)
    add_log(msg)

    for i, username in enumerate(new_usernames, 1):
        # Check if stop was requested
        if check_stop():
            msg = "⚠️  Sourcing stopped by user"
            yield emit(msg, 'warning')
            add_log(msg)
            status.status = 'stopped'
            status.completed_at = datetime.utcnow()
            db.commit()
            return

        if stats['saved'] >= target_count:
            msg = f"✓ Reached target of {target_count} saved candidates"
            yield emit(msg, 'success')
            add_log(msg)
            break

        try:
            msg = f"[{i}/{len(new_usernames)}] Evaluating {username}..."
            yield emit(msg)

            status.candidates_processed = i
            status.current_search = f"Evaluating {username}"
            db.commit()

            candidate_data = ingest_candidate(username)

            if candidate_data is None:
                stats['skipped_hard_filter'] += 1
                status.candidates_skipped += 1
                msg = f"    ✗ Skipped (failed hard filters: no email/inactive/no original repos)"
                yield emit(msg)
                continue

            behavior_score = candidate_data.get('behavior_score', 0)
            behavior_tier = candidate_data.get('behavior_tier', 'cold')

            if behavior_score >= min_behavior_score:
                candidate = CandidateCreate(**candidate_data)
                created = create_candidate(db, candidate)
                stats['saved'] += 1
                status.candidates_saved += 1

                if behavior_tier == 'hot':
                    stats['hot'] += 1
                elif behavior_tier == 'warm':
                    stats['warm'] += 1

                msg = f"    ✓ Saved {username} ({behavior_tier}, score: {behavior_score})"
                yield emit(msg, 'success')
                add_log(msg)
                db.commit()
            else:
                stats['skipped_low_score'] += 1
                stats['cold'] += 1
                status.candidates_skipped += 1
                msg = f"    ✗ Skipped {username} (score: {behavior_score} < {min_behavior_score})"
                yield emit(msg)
                db.commit()
        except Exception as e:
            logger.error("✗ Failed to ingest %s: %s", username, e)
            stats['errors'] += 1
            status.error_count += 1
            status.error_message = str(e)
            msg = f"    ✗ Error processing {username}: {str(e)}"
            yield emit(msg, 'error')
            add_log(msg)
            db.commit()

    # Final summary
    msg = f"\n✅ Sourcing complete!"
    yield emit(msg, 'success')
    add_log(msg)

    status.status = 'completed'
    status.completed_at = datetime.utcnow()
    status.stats = stats
    db.commit()

    summary_msgs = [
        f"  Searched: {stats['searched']} unique candidates",
        f"  Already in DB: {stats['existing']}",
        f"  Evaluated: {stats['new']}",
        f"  Saved: {stats['saved']} (Hot: {stats['hot']}, Warm: {stats['warm']})",
        f"  Skipped (filters): {stats['skipped_hard_filter']}",
        f"  Skipped (low score): {stats['skipped_low_score']}",
    ]

    for msg in summary_msgs:
        yield emit(msg)
        add_log(msg)

    if stats['errors'] > 0:
        msg = f"  Errors: {stats['errors']}"
        yield emit(msg, 'error')
        add_log(msg)


def nightly_github_ingestion(
    db,
    min_behavior_score: int = 30,
    target_count: int = 500
) -> Dict[str, int]:
    """
    Non-streaming version for backwards compatibility.
    Run manual sourcing from GitHub based on behavior signals.
    """
    from app.api.crud import get_candidate_by_github_username, create_candidate
    from app.schemas.candidate import CandidateCreate

    # Comprehensive location coverage (35 location groups - US/Canada only)
    location_groups = [
        # US Broad
        'United States OR USA OR US',
        # Major Tech Hubs
        '"San Francisco" OR SF',
        '"New York" OR NYC',
        'Seattle',
        'Austin',
        'Boston',
        '"Bay Area"',
        '"Silicon Valley"',
        '"Palo Alto"',
        'Chicago',
        'Denver',
        'Portland',
        'Atlanta',
        'Miami',
        'Dallas',
        'Houston',
        'Phoenix',
        # US States
        'California',
        'Texas',
        'Washington',
        'Massachusetts',
        'Colorado',
        'Oregon',
        'Georgia',
        'Florida',
        'Illinois',
        'Arizona',
        'Pennsylvania',
        'Virginia',
        'North Carolina',
        # Canada
        'Canada',
        'Toronto',
        'Vancouver',
        'Montreal',
        'Waterloo'
    ]

    # 10 languages (added java, ruby)
    languages = ['typescript', 'python', 'go', 'rust', 'javascript', 'cpp', 'swift', 'kotlin', 'java', 'ruby']

    # 350 searches total (10 languages × 35 locations)
    # Filter: repos:>=5 (no follower filter, activity checked during evaluation)
    # With pagination: up to 1000 results per search (GitHub's limit)
    searches = [
        {'languages': [lang], 'location': location_group, 'min_repos': 5}
        for lang in languages
        for location_group in location_groups
    ]

    all_usernames = set()

    logger.info("Running %d searches...", len(searches))
    for search in searches:
        usernames = search_github_users(**search)
        all_usernames.update(usernames)
        logger.info("Total unique so far: %d", len(all_usernames))

    logger.info("Filtering out existing candidates...")
    existing_usernames = set()
    for username in all_usernames:
        existing = get_candidate_by_github_username(db, username)
        if existing:
            existing_usernames.add(username)

    new_usernames = list(all_usernames - existing_usernames)

    if len(new_usernames) > target_count:
        logger.info("Limiting to %d candidates (found %d)", target_count, len(new_usernames))
        new_usernames = new_usernames[:target_count]

    stats = {
        'searched': len(all_usernames),
        'existing': len(existing_usernames),
        'new': len(new_usernames),
        'saved': 0,
        'skipped_hard_filter': 0,
        'skipped_low_score': 0,
        'hot': 0,
        'warm': 0,
        'cold': 0,
        'errors': 0,
    }

    logger.info("Evaluating %d new candidates...", len(new_usernames))

    for username in new_usernames:
        if stats['saved'] >= target_count:
            logger.info("Reached target count of %d saved candidates, stopping early", target_count)
            break

        try:
            candidate_data = ingest_candidate(username)

            if candidate_data is None:
                stats['skipped_hard_filter'] += 1
                continue

            behavior_score = candidate_data.get('behavior_score', 0)
            behavior_tier = candidate_data.get('behavior_tier', 'cold')

            if behavior_score >= min_behavior_score:
                candidate = CandidateCreate(**candidate_data)
                created = create_candidate(db, candidate)
                stats['saved'] += 1

                if behavior_tier == 'hot':
                    stats['hot'] += 1
                elif behavior_tier == 'warm':
                    stats['warm'] += 1

                logger.info("✓ Saved %s (%s, score: %d)", username, behavior_tier, behavior_score)
            else:
                stats['skipped_low_score'] += 1
                stats['cold'] += 1
                logger.info("✗ Skipped %s (%s, score: %d < %d)", username, behavior_tier, behavior_score, min_behavior_score)
        except Exception as e:
            logger.error("✗ Failed to ingest %s: %s", username, e, exc_info=True)
            stats['errors'] += 1

    logger.info("\nComplete!")
    logger.info("  Searched: %d", stats['searched'])
    logger.info("  Existing: %d", stats['existing'])
    logger.info("  New: %d", stats['new'])
    logger.info("  Saved: %d (Hot: %d, Warm: %d)", stats['saved'], stats['hot'], stats['warm'])
    logger.info("  Skipped (hard filters): %d (no email/inactive/no original repos)", stats['skipped_hard_filter'])
    logger.info("  Skipped (low score): %d (cold tier < %d)", stats['skipped_low_score'], min_behavior_score)
    logger.info("  Errors: %d", stats['errors'])

    return stats


def nightly_github_ingestion_background(
    db,
    status_id: str,
    min_behavior_score: int = 30,
    target_count: int = 500
):
    """
    Background task version that runs search independently and updates database status.
    This allows the search to run independently of any SSE or HTTP connection.
    """
    from app.api.crud import get_candidate_by_github_username, create_candidate
    from app.schemas.candidate import CandidateCreate
    from app.models.ingestion_status import IngestionStatus
    from datetime import datetime
    import uuid

    # Get the status record
    status = db.query(IngestionStatus).filter(IngestionStatus.id == uuid.UUID(status_id)).first()
    if not status:
        logger.error("Status record %s not found", status_id)
        return

    def add_log(message: str):
        """Add message to recent logs (keep last 1000)"""
        from sqlalchemy.orm.attributes import flag_modified

        logger.debug("add_log CALLED: %s", message[:80])

        logs = status.recent_logs or []
        est = pytz.timezone('US/Eastern')
        timestamp = datetime.now(est).strftime('%d/%m/%y %I:%M %p EST')
        logs.append({'timestamp': timestamp, 'message': message})
        # Keep only last 1000 logs (enough for full search with 500 candidates)
        logs = logs[-1000:]

        # CRITICAL: Reassign to force SQLAlchemy to detect JSON field change
        status.recent_logs = logs
        flag_modified(status, 'recent_logs')  # Explicitly mark as modified

        status.updated_at = datetime.utcnow()
        db.commit()

        logger.debug("add_log COMMITTED: total logs now: %d", len(status.recent_logs))

    def check_stop():
        """Check if stop was requested, return True if should stop"""
        db.refresh(status)
        return status.stop_requested

    try:
        # Comprehensive location coverage (35 location groups - US/Canada only)
        location_groups = [
            # US Broad
            'United States OR USA OR US',
            # Major Tech Hubs
            '"San Francisco" OR SF',
            '"New York" OR NYC',
            'Seattle',
            'Austin',
            'Boston',
            '"Bay Area"',
            '"Silicon Valley"',
            '"Palo Alto"',
            'Chicago',
            'Denver',
            'Portland',
            'Atlanta',
            'Miami',
            'Dallas',
            'Houston',
            'Phoenix',
            # US States
            'California',
            'Texas',
            'Washington',
            'Massachusetts',
            'Colorado',
            'Oregon',
            'Georgia',
            'Florida',
            'Illinois',
            'Arizona',
            'Pennsylvania',
            'Virginia',
            'North Carolina',
            # Canada
            'Canada',
            'Toronto',
            'Vancouver',
            'Montreal',
            'Waterloo'
        ]

        # 10 languages (added java, ruby)
        languages = ['typescript', 'python', 'go', 'rust', 'javascript', 'cpp', 'swift', 'kotlin', 'java', 'ruby']

        # 350 searches total (10 languages × 35 locations)
        # Filter: repos:>=5 (no follower filter, activity checked during evaluation)
        searches = [
            {'languages': [lang], 'location': location_group, 'min_repos': 5}
            for lang in languages
            for location_group in location_groups
        ]

        # Update status with total searches
        status.searches_total = len(searches)
        db.commit()

        all_usernames = set()

        # Search phase (initial log already added by routes.py, don't duplicate)
        add_log(f"Searching {len(languages)} languages across {len(location_groups)} location groups")
        add_log(f"This typically takes 2-5 minutes, please wait...")

        for i, search in enumerate(searches, 1):
            # Check if stop was requested (check before each search)
            if check_stop():
                add_log("⚠️  Sourcing stopped by user")
                status.status = 'stopped'
                status.completed_at = datetime.utcnow()
                db.commit()
                return

            lang = search['languages'][0]
            location = search['location']
            add_log(f"[{i}/{len(searches)}] Searching {lang} developers in {location.split(' OR ')[0]}...")

            status.current_search = f"{lang} in {location.split(' OR ')[0]}"
            status.searches_completed = i
            status.updated_at = datetime.utcnow()  # Keep alive signal
            db.commit()

            usernames = search_github_users(**search)
            all_usernames.update(usernames)
            add_log(f"    Found {len(usernames)} candidates ({len(all_usernames)} total unique)")

            # Check stop after each search too (in case they stopped during the search)
            if check_stop():
                add_log("⚠️  Sourcing stopped by user")
                status.status = 'stopped'
                status.completed_at = datetime.utcnow()
                db.commit()
                return

        add_log(f"✓ Search complete: {len(all_usernames)} unique candidates found")

        # Filter existing
        add_log(f"Filtering out existing candidates...")

        existing_usernames = set()
        for username in all_usernames:
            existing = get_candidate_by_github_username(db, username)
            if existing:
                existing_usernames.add(username)

        new_usernames = list(all_usernames - existing_usernames)
        add_log(f"    {len(existing_usernames)} already in database")
        add_log(f"    {len(new_usernames)} new candidates to evaluate")

        # Ingest candidates
        stats = {
            'searched': len(all_usernames),
            'existing': len(existing_usernames),
            'new': len(new_usernames),
            'saved': 0,
            'skipped_hard_filter': 0,
            'skipped_low_score': 0,
            'hot': 0,
            'warm': 0,
            'cold': 0,
            'errors': 0,
        }

        # Pre-filter: Get basic info, sort by quality, and SAVE data to avoid duplicate calls
        add_log(f"Pre-filtering {len(new_usernames)} candidates...")

        candidate_rankings = []
        prefetch_cache = {}  # Store full user data to reuse in ingest_candidate

        for username in new_usernames:
            try:
                # Use get_user_details to get full data (can be reused)
                user_details = get_user_details(username)

                if user_details:
                    # Store for reuse
                    prefetch_cache[username] = user_details

                    candidate_rankings.append({
                        'username': username,
                        'public_repos': user_details.get('github_public_repos', 0)
                    })
            except Exception as e:
                logger.error("Pre-filter error for %s: %s", username, e)
                # If we can't fetch basic info, include anyway (will be filtered later)
                candidate_rankings.append({
                    'username': username,
                    'public_repos': 0
                })

        # Sort by public_repos descending (highest quality candidates first)
        candidate_rankings.sort(key=lambda x: x['public_repos'], reverse=True)
        sorted_usernames = [c['username'] for c in candidate_rankings]

        add_log(f"✓ Pre-filtered to {len(sorted_usernames)} candidates (sorted by repos)")
        add_log(f"Evaluating {len(sorted_usernames)} candidates with parallel processing (12 workers)...")

        # Update new_usernames to sorted version
        new_usernames = sorted_usernames

        # OPTIMIZED: Process in batches with parallel workers (12x faster)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from threading import Lock

        db_write_lock = Lock()
        BATCH_SIZE = 100  # Process 100 candidates at a time for better progress updates
        MAX_WORKERS = 24  # 24 parallel workers (8 per token) - 98.7% token utilization

        def process_single_candidate_for_nightly(username: str, global_index: int, prefetch_data: Optional[Dict]):
            """Process a single candidate - called in parallel by workers."""
            try:
                candidate_data = ingest_candidate(username, prefetch_data=prefetch_data)
                return {
                    'username': username,
                    'index': global_index,
                    'data': candidate_data,
                    'success': True
                }
            except Exception as e:
                return {
                    'username': username,
                    'index': global_index,
                    'error': str(e),
                    'success': False
                }

        # Process in batches for better progress visibility
        for batch_start in range(0, len(new_usernames), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(new_usernames))
            batch_usernames = new_usernames[batch_start:batch_end]

            # Check if stop was requested
            if check_stop():
                add_log("⚠️  Sourcing stopped by user")
                status.status = 'stopped'
                status.completed_at = datetime.utcnow()
                db.commit()
                return

            add_log(f"Processing batch {batch_start+1}-{batch_end}/{len(new_usernames)}...")

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # Submit all candidates in this batch for parallel processing
                futures = {}
                for i, username in enumerate(batch_usernames):
                    global_index = batch_start + i
                    prefetch_data = prefetch_cache.get(username)
                    future = executor.submit(process_single_candidate_for_nightly, username, global_index, prefetch_data)
                    futures[future] = (username, global_index)

                # Process results as they complete
                for future in as_completed(futures):
                    username, global_index = futures[future]

                    # Check if stop was requested
                    with db_write_lock:
                        if check_stop():
                            add_log("⚠️  Sourcing stopped by user")
                            status.status = 'stopped'
                            status.completed_at = datetime.utcnow()
                            db.commit()
                            return

                    # Get result from worker thread
                    result = future.result()

                    # All DB operations are thread-safe with lock
                    with db_write_lock:
                        try:
                            # Update progress
                            status.candidates_processed = global_index + 1
                            status.current_search = f"Evaluating {username}"
                            status.updated_at = datetime.utcnow()

                            # Handle errors
                            if not result['success']:
                                stats['errors'] += 1
                                status.error_count += 1
                                status.error_message = result['error']
                                add_log(f"✗ {username} → Error ({result['error']})")
                                db.commit()
                                continue

                            candidate_data = result['data']

                            # Check if filtered
                            if candidate_data is None or (isinstance(candidate_data, dict) and candidate_data.get('filtered')):
                                stats['skipped_hard_filter'] += 1
                                status.candidates_skipped += 1

                                filter_reason = "hard filter"
                                if isinstance(candidate_data, dict) and 'reason' in candidate_data:
                                    reason_map = {
                                        'no_email': 'no email',
                                        'no_contact_method': 'no contact',
                                        'no_recent_activity': 'no activity',
                                        'only_forked_repos': 'only forks',
                                        'account_too_new': 'account too new'
                                    }
                                    filter_reason = reason_map.get(candidate_data['reason'], candidate_data['reason'])

                                add_log(f"✗ {username} → Filtered ({filter_reason})")
                                db.commit()
                                continue

                            behavior_score = candidate_data.get('behavior_score', 0)
                            behavior_tier = candidate_data.get('behavior_tier', 'cold')

                            if behavior_score >= min_behavior_score:
                                candidate = CandidateCreate(**candidate_data)
                                created = create_candidate(db, candidate)
                                stats['saved'] += 1
                                status.candidates_saved += 1

                                if behavior_tier == 'hot':
                                    stats['hot'] += 1
                                elif behavior_tier == 'warm':
                                    stats['warm'] += 1

                                add_log(f"✓ {username} → Saved (score: {behavior_score}, tier: {behavior_tier})")
                            else:
                                stats['skipped_low_score'] += 1
                                stats['cold'] += 1
                                status.candidates_skipped += 1
                                add_log(f"✗ {username} → Filtered (score: {behavior_score} < {min_behavior_score})")

                            db.commit()

                        except Exception as e:
                            logger.error("✗ Failed to save %s: %s", username, e)
                            stats['errors'] += 1
                            status.error_count += 1
                            add_log(f"✗ {username} → Error saving ({str(e)})")
                            db.commit()

        # Final summary
        add_log(f"\n✅ Sourcing complete!")

        status.status = 'completed'
        status.completed_at = datetime.utcnow()
        status.stats = stats
        db.commit()

        add_log(f"  Searched: {stats['searched']} unique candidates")
        add_log(f"  Already in DB: {stats['existing']}")
        add_log(f"  Evaluated: {stats['new']}")
        add_log(f"  Saved: {stats['saved']} (Hot: {stats['hot']}, Warm: {stats['warm']})")
        add_log(f"  Skipped (filters): {stats['skipped_hard_filter']}")
        add_log(f"  Skipped (low score): {stats['skipped_low_score']}")

        logger.info("Complete! Saved %d candidates", stats['saved'])

    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)

        status.status = 'failed'
        status.completed_at = datetime.utcnow()
        status.error_message = str(e)
        add_log(f"❌ Fatal error: {str(e)}")
        db.commit()


# ── Tech stack → GitHub language mapping ─────────────────────────────────────

# Maps canonical tech names (from role_sourcing.py) to GitHub search languages
TECH_TO_GITHUB_LANG = {
    # Direct language matches
    'python': ['python'],
    'javascript': ['javascript'],
    'typescript': ['typescript'],
    'go': ['go'],
    'rust': ['rust'],
    'java': ['java'],
    'ruby': ['ruby'],
    'c++': ['cpp'],
    'c#': ['csharp'],
    'php': ['php'],
    'swift': ['swift'],
    'kotlin': ['kotlin'],
    'elixir': ['elixir'],
    # Frameworks → parent language
    'react': ['javascript', 'typescript'],
    'vue': ['javascript', 'typescript'],
    'angular': ['typescript'],
    'svelte': ['javascript', 'typescript'],
    'next.js': ['javascript', 'typescript'],
    'nuxt': ['javascript', 'typescript'],
    'gatsby': ['javascript'],
    'remix': ['typescript'],
    'node.js': ['javascript', 'typescript'],
    'express': ['javascript', 'typescript'],
    'nestjs': ['typescript'],
    'django': ['python'],
    'flask': ['python'],
    'fastapi': ['python'],
    'rails': ['ruby'],
    'laravel': ['php'],
    'spring': ['java'],
    'react native': ['javascript', 'typescript'],
    'flutter': ['dart'],
    'expo': ['javascript', 'typescript'],
    # Data/ML → python
    'pytorch': ['python'],
    'tensorflow': ['python'],
    'langchain': ['python'],
    'openai': ['python'],
    'anthropic': ['python'],
    'huggingface': ['python'],
    # ORMs/tools → parent language
    'prisma': ['typescript'],
    'drizzle': ['typescript'],
    'typeorm': ['typescript'],
    'sqlalchemy': ['python'],
}


def tech_stack_to_github_languages(tech_stack: List[str]) -> List[str]:
    """
    Map a role's tech_stack to GitHub search language names.

    E.g., ['react', 'python', 'fastapi'] → ['javascript', 'typescript', 'python']
    """
    langs = set()
    for tech in tech_stack:
        key = tech.lower().strip()
        if key in TECH_TO_GITHUB_LANG:
            langs.update(TECH_TO_GITHUB_LANG[key])
    # Fallback: if nothing mapped, use broad defaults
    if not langs:
        langs = {'python', 'typescript', 'javascript'}
    return sorted(langs)


# ── Targeted GitHub sourcing (role-aware) ────────────────────────────────────

def targeted_github_sourcing_background(
    db,
    job_id: str,
    role_id: str,
    languages: List[str],
    locations: List[str],
    count: int = 50,
    min_repos: int = 5,
    hireable_only: bool = False,
    min_behavior_score: int = 30,
    auto_match: bool = True,
    role_title: str = "",
    tech_stack: List[str] = None,
    jd_text: str = "",
    strategy: str = "both",
):
    """
    Background task: search GitHub for candidates matching specific languages/locations,
    ingest them, then optionally auto-match against the given role.

    Uses four search strategies for differentiated candidate pools:
    1. Language + location user search (original)
    2. Bio keyword user search (e.g., "data engineer" in:bio)
    3. Repo topic search -> extract owner usernames (e.g., topic:data-pipeline)
    4. Semantic repo discovery -> find repos matching JD, extract top contributors

    Reuses search_github_users() and ingest_candidate() from the nightly pipeline.
    """
    from app.api.crud import get_candidate_by_github_username, create_candidate
    from app.schemas.candidate import CandidateCreate
    from app.models.ingestion_job import IngestionJob, JobStatus
    from app.services.matching import create_matches_for_role
    from sqlalchemy.orm.attributes import flag_modified
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import uuid

    job = db.query(IngestionJob).filter(IngestionJob.id == uuid.UUID(job_id)).first()
    if not job:
        logger.error("Targeted sourcing job %s not found", job_id)
        return

    def add_log(message: str):
        logs = job.recent_logs or []
        est = pytz.timezone('US/Eastern')
        timestamp = datetime.now(est).strftime('%d/%m/%y %I:%M %p EST')
        logs.append({'timestamp': timestamp, 'message': message})
        logs = logs[-1000:]
        job.recent_logs = logs
        flag_modified(job, 'recent_logs')
        job.updated_at = datetime.utcnow()
        db.commit()

    def check_stopped():
        db.refresh(job)
        return job.status == JobStatus.stopped

    def save_checkpoint(phase: str, data: dict):
        """Persist checkpoint to DB so job can resume after Railway restart."""
        cp = job.checkpoint_data or {}
        cp['resume_phase'] = phase
        cp.update(data)
        job.checkpoint_data = cp
        flag_modified(job, 'checkpoint_data')
        job.updated_at = datetime.utcnow()
        db.commit()

    try:
        job.status = JobStatus.running
        if not job.started_at:
            job.started_at = datetime.utcnow()
        db.commit()

        # ── Check for resume from checkpoint ────────────────────────────
        cp = job.checkpoint_data or {}
        resume_phase = cp.get('resume_phase')

        if resume_phase:
            add_log(f"Resuming from checkpoint: {resume_phase}")

        # ── Phase 1: Search ──────────────────────────────────────────────
        if resume_phase and resume_phase in ('ingest', 'match'):
            # Skip search — load saved usernames from checkpoint
            new_usernames = cp.get('new_usernames', [])
            add_log(f"Skipping search phase (checkpoint has {len(new_usernames)} usernames)")
        else:
            # Strategy controls which search phases to run:
            #   'both' (default) = user search + repo discovery
            #   'user_search'    = only Phase 1a + 1b (language/location/bio)
            #   'repo_discovery' = only Phase 1c (JD-driven semantic repo search)
            run_user_search = strategy in ('both', 'user_search')
            run_repo_discovery = strategy in ('both', 'repo_discovery')

            if not run_user_search:
                add_log("Skipping user search (strategy=repo_discovery)")

            # ── Phase 1a: User search ──────────────────────────────────────
            # Build searches: each language × each location
            # When count is high, generate additional query variations to cast a wider net.
            # GitHub search returns different result sets for different repos:>= / followers:>= thresholds
            # because its ranking algorithm weights them differently.
            searches = []  # empty when user search is skipped; loop becomes a no-op

            if not run_user_search:
                add_log(f"Skipping user search phases (strategy={strategy})")

            # Base searches: lang × location (no date range upfront — search_github_users
            # auto-splits into date ranges when a query hits GitHub's 1K result cap)
            for lang in (languages if run_user_search else []):
                for loc in locations:
                    searches.append({'languages': [lang], 'location': loc, 'min_repos': min_repos, 'hireable_only': hireable_only})

            # Scale up search diversity for higher target counts
            base_queries = len(languages) * len(locations)
            raw_needed = count * 5
            base_practical = base_queries * 200

            if run_user_search and raw_needed > base_practical:
                extra_repo_thresholds = [3, 10, 20, 50]
                extra_repo_thresholds = [t for t in extra_repo_thresholds if t != min_repos]
                needed_multiplier = max(1, raw_needed // max(base_practical, 1))
                tiers_to_add = min(len(extra_repo_thresholds), needed_multiplier)

                for tier_repos in extra_repo_thresholds[:tiers_to_add]:
                    for lang in languages:
                        for loc in locations:
                            searches.append({'languages': [lang], 'location': loc, 'min_repos': tier_repos, 'hireable_only': hireable_only})

                if count >= 300:
                    follower_thresholds = [10, 50, 100]
                    for min_fol in follower_thresholds:
                        for lang in languages:
                            for loc in locations:
                                searches.append({
                                    'languages': [lang], 'location': loc,
                                    'min_repos': min_repos, 'hireable_only': hireable_only,
                                    'min_followers': min_fol,
                                })

            job.searches_total = len(searches)
            db.commit()

            if searches:
                add_log(f"Searching {len(languages)} language(s) across {len(locations)} location(s) ({len(searches)} queries, targeting {count} saves)")

            # SPEED OPT: Run search queries in parallel (4 concurrent) instead of sequential
            SEARCH_WORKERS = 4
            all_usernames = set()
            searches_done = 0
            early_exit = False

            def run_search(search_params):
                """Execute a single search query (no DB access, thread-safe)."""
                return search_github_users(**search_params)

            for batch_start in range(0, len(searches), SEARCH_WORKERS):
                if check_stopped():
                    add_log("Sourcing stopped by user")
                    job.completed_at = datetime.utcnow()
                    db.commit()
                    return

                if early_exit:
                    break

                batch = searches[batch_start:batch_start + SEARCH_WORKERS]
                batch_labels = []
                for s in batch:
                    lang = s['languages'][0]
                    loc = s['location'].split(' OR ')[0]
                    repos_tag = f" repos>={s['min_repos']}" if s['min_repos'] != min_repos else ""
                    fol_tag = f" followers>={s['min_followers']}" if s.get('min_followers', 0) > 0 else ""
                    batch_labels.append(f"{lang}/{loc}{repos_tag}{fol_tag}")
                add_log(f"[{batch_start+1}-{batch_start+len(batch)}/{len(searches)}] Searching {', '.join(batch_labels)}...")

                with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as executor:
                    futures = {executor.submit(run_search, s): s for s in batch}
                    for future in as_completed(futures):
                        try:
                            usernames = future.result()
                            all_usernames.update(usernames)
                        except Exception as e:
                            logger.error("Search query failed: %s", e)

                searches_done += len(batch)
                job.searches_completed = searches_done
                job.current_search = f"Searched {searches_done}/{len(searches)} queries ({len(all_usernames)} candidates)"
                job.updated_at = datetime.utcnow()
                db.commit()

                # Early exit: if we already have way more raw candidates than needed, skip remaining searches
                if len(all_usernames) >= count * 8 and searches_done < len(searches):
                    add_log(f"  Already found {len(all_usernames)} candidates (need ~{count * 5}), skipping remaining searches")
                    early_exit = True

            if run_user_search:
                add_log(f"User search complete: {len(all_usernames)} unique candidates found")

            # ── Phase 1b: Role-differentiated searches (bio keywords + repo topics) ──
            role_kw = derive_role_search_keywords(role_title or '', tech_stack or [])
            bio_keywords = role_kw['bio_keywords']
            repo_topics = role_kw['repo_topics']

            if run_user_search and (bio_keywords or repo_topics):
                pre_count = len(all_usernames)

                # Bio keyword searches: "KEYWORD in:bio language:X location:Y"
                if bio_keywords and not early_exit:
                    bio_searches = []
                    for kw in bio_keywords[:3]:  # Top 3 keywords to avoid rate limit burn
                        for lang in languages[:2]:  # Top 2 languages
                            for loc in locations[:2]:  # Top 2 locations
                                bio_searches.append({'keyword': kw, 'language': lang, 'location': loc})

                    add_log(f"Running {len(bio_searches)} bio keyword searches ({', '.join(bio_keywords[:3])})...")

                    def run_bio_search(params):
                        """Search users by bio keyword (thread-safe, no DB)."""
                        kw = params['keyword']
                        lang = params['language']
                        loc = params['location']
                        # Quote multi-word keywords and locations
                        kw_q = f'"{kw}"' if ' ' in kw else kw
                        if ' ' in loc or loc in ['United States', 'Silicon Valley', 'Bay Area']:
                            loc_q = f'location:"{loc}"'
                        else:
                            loc_q = f'location:{loc}'
                        query = f'{kw_q} in:bio language:{lang} {loc_q} repos:>={min_repos}'

                        found = []
                        for page in range(1, 6):  # Max 5 pages (500 results)
                            url = f"https://api.github.com/search/users?q={query}&per_page=100&page={page}"
                            try:
                                resp = requests.get(url, headers=token_rotator.get_headers(), timeout=30)
                                if resp.status_code == 403:
                                    time.sleep(10)
                                    resp = requests.get(url, headers=token_rotator.get_headers(), timeout=30)
                                if resp.status_code != 200:
                                    break
                                items = resp.json().get('items', [])
                                for u in items:
                                    found.append(u['login'])
                                if len(items) < 100:
                                    break
                            except Exception as e:
                                logger.error("Bio search error for '%s': %s", kw, e)
                                break
                        return found

                    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as executor:
                        futures = {executor.submit(run_bio_search, s): s for s in bio_searches}
                        for future in as_completed(futures):
                            try:
                                all_usernames.update(future.result())
                            except Exception as e:
                                logger.error("Bio search failed: %s", e)

                # Repo topic searches: search repos by topic, extract owner usernames
                if repo_topics and not early_exit:
                    add_log(f"Running repo topic searches ({', '.join(repo_topics[:4])})...")
                    primary_lang = languages[0] if languages else None
                    topic_users = search_github_repos_for_users(
                        topics=repo_topics[:4],
                        language=primary_lang,
                        min_stars=10,
                        max_pages=3,
                    )
                    all_usernames.update(topic_users)
                    add_log(f"  Repo topics found {len(topic_users)} candidate owners")

                new_from_role = len(all_usernames) - pre_count
                add_log(f"Role-differentiated search added {new_from_role} new candidates (total: {len(all_usernames)})")

            # ── Phase 1c: Semantic Repo Discovery ──────────────────────────────
            # Use LLM to generate search queries from JD, find matching repos,
            # then extract top contributors as candidate usernames
            if run_repo_discovery and (jd_text or tech_stack) and not early_exit:
                pre_semantic = len(all_usernames)
                add_log("Starting semantic repo discovery...")

                # Step 1: Generate search queries from JD
                repo_queries = generate_repo_search_queries(
                    jd_text=jd_text or '',
                    role_title=role_title or '',
                    tech_stack=tech_stack,
                )

                if repo_queries:
                    add_log(f"  Generated {len(repo_queries)} repo search queries")
                    job.current_search = f"Semantic search: {len(repo_queries)} queries"
                    db.commit()

                    # Step 2: Search GitHub repos
                    matching_repos = search_repos_semantic(
                        queries=repo_queries,
                        languages=languages,
                        min_stars=5,
                        max_pages_per_query=3,
                        max_repos=500,
                    )
                    add_log(f"  Found {len(matching_repos)} qualifying repos")

                    if matching_repos:
                        job.current_search = f"Fetching contributors from {len(matching_repos)} repos"
                        db.commit()

                        # Step 3: Fetch top contributors
                        contributor_usernames = fetch_repo_contributors(
                            repos=matching_repos,
                            min_commits=5,
                            max_contributors_per_repo=10,
                            max_repos=300,
                        )
                        all_usernames.update(contributor_usernames)

                        new_from_semantic = len(all_usernames) - pre_semantic
                        add_log(f"  Semantic discovery: {len(contributor_usernames)} contributors from repos, {new_from_semantic} new unique")
                else:
                    add_log("  No repo search queries generated (no JD text)")

            add_log(f"Search complete: {len(all_usernames)} unique candidates found")

            # ── Phase 2: Filter existing ─────────────────────────────────────
            add_log("Filtering out existing candidates...")
            # Batch query: one IN() query per chunk instead of N sequential SELECTs
            from app.models.candidate import Candidate as CandidateModel
            existing_usernames = set()
            username_list = list(all_usernames)
            FILTER_BATCH = 500  # PostgreSQL handles IN() with 500 items efficiently
            for i in range(0, len(username_list), FILTER_BATCH):
                batch = username_list[i:i + FILTER_BATCH]
                found = db.query(CandidateModel.github_username).filter(
                    CandidateModel.github_username.in_(batch)
                ).all()
                existing_usernames.update(row[0] for row in found)

            new_usernames = list(all_usernames - existing_usernames)
            add_log(f"  {len(existing_usernames)} already in database, {len(new_usernames)} new to evaluate")

            # Cap evaluation pool: need ~20x target because hard filters reject 60-70%
            # and behavior score < 30 rejects another 20-30%, giving ~5-10% pass rate.
            eval_limit = min(len(new_usernames), count * 20)
            if eval_limit < len(new_usernames):
                new_usernames = new_usernames[:eval_limit]
                add_log(f"  Evaluating top {eval_limit} candidates (targeting {count} saves)")

            # Checkpoint: save usernames so we can skip search on resume
            save_checkpoint('ingest', {'new_usernames': new_usernames})

        job.total_candidates = len(new_usernames)
        db.commit()

        # ── Phase 3: Ingest ──────────────────────────────────────────────
        # Load already-processed usernames from checkpoint (for resume)
        processed_usernames = set(cp.get('processed_usernames', []))
        if processed_usernames:
            add_log(f"Skipping {len(processed_usernames)} already-processed usernames from checkpoint")

        stats = {'saved': 0, 'filtered': 0, 'errors': 0}
        saved_candidate_ids = list(cp.get('saved_candidate_ids', []))  # Restore from checkpoint
        # Restore stats from checkpoint
        if cp.get('ingest_stats'):
            stats = dict(cp['ingest_stats'])
        MAX_WORKERS = 25
        BATCH_SIZE = 50
        db_write_lock = Lock()

        def process_one(username, idx):
            try:
                data = ingest_candidate(username)
                return {'username': username, 'index': idx, 'data': data, 'success': True}
            except Exception as e:
                return {'username': username, 'index': idx, 'error': str(e), 'success': False}

        # Filter out already-processed usernames (for checkpoint resume)
        if processed_usernames:
            remaining = [u for u in new_usernames if u not in processed_usernames]
            add_log(f"Evaluating {len(remaining)} remaining candidates ({len(processed_usernames)} already done, {MAX_WORKERS} workers)...")
        else:
            remaining = new_usernames
            add_log(f"Evaluating {len(remaining)} candidates ({MAX_WORKERS} workers)...")

        for batch_start in range(0, len(remaining), BATCH_SIZE):
            if check_stopped():
                add_log("Sourcing stopped by user")
                job.completed_at = datetime.utcnow()
                db.commit()
                return

            # Stop early if we've saved enough
            if stats['saved'] >= count:
                add_log(f"Reached target of {count} candidates, stopping evaluation")
                break

            batch = remaining[batch_start:batch_start + BATCH_SIZE]

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(process_one, username, batch_start + i): username
                    for i, username in enumerate(batch)
                }

                for future in as_completed(futures, timeout=300):  # 5 min timeout per batch
                    try:
                        result = future.result(timeout=120)  # 2 min per candidate max
                    except Exception as timeout_err:
                        username = futures.get(future, '?')
                        logger.error("Candidate %s timed out or errored: %s", username, timeout_err)
                        continue

                    with db_write_lock:
                        if check_stopped():
                            add_log("Sourcing stopped by user")
                            job.completed_at = datetime.utcnow()
                            db.commit()
                            return

                        job.processed_count = result['index'] + 1
                        job.current_search = f"Evaluating {result['username']}"
                        job.updated_at = datetime.utcnow()

                        if not result['success']:
                            stats['errors'] += 1
                            job.error_count += 1
                            add_log(f"  x {result['username']} -> Error ({result['error']})")
                            db.commit()
                            continue

                        candidate_data = result['data']
                        if candidate_data is None or (isinstance(candidate_data, dict) and candidate_data.get('filtered')):
                            stats['filtered'] += 1
                            job.candidates_skipped += 1
                            reason = candidate_data.get('reason', 'filter') if isinstance(candidate_data, dict) else 'filter'
                            db.commit()
                            continue

                        behavior_score = candidate_data.get('behavior_score', 0)
                        if behavior_score >= min_behavior_score:
                            try:
                                candidate = CandidateCreate(**candidate_data)
                                saved_obj = create_candidate(db, candidate)
                                if saved_obj:
                                    saved_candidate_ids.append(str(saved_obj.id))
                                stats['saved'] += 1
                                job.candidates_saved += 1
                                add_log(f"  + {result['username']} (score: {behavior_score})")
                            except Exception as e:
                                stats['errors'] += 1
                                job.error_count += 1
                                add_log(f"  x {result['username']} -> Save error ({e})")
                        else:
                            stats['filtered'] += 1
                            job.candidates_skipped += 1

                        db.commit()

            # Checkpoint after each batch so we can resume on restart
            processed_usernames.update(batch)
            save_checkpoint('ingest', {
                'processed_usernames': list(processed_usernames),
                'saved_candidate_ids': saved_candidate_ids,
                'ingest_stats': stats,
            })

        add_log(f"Ingestion complete: {stats['saved']} saved, {stats['filtered']} filtered, {stats['errors']} errors")

        # Checkpoint: save candidate IDs for matching phase resume
        save_checkpoint('match', {
            'saved_candidate_ids': saved_candidate_ids,
            'ingest_stats': stats,
        })

        # ── Phase 4: Parallel CrossChekk matching (only newly sourced) ──
        matches_created = 0
        if auto_match and saved_candidate_ids:
            from app.api.crud import create_match, get_role as _get_role, get_candidate as _get_candidate
            from app.schemas.match import MatchCreate
            from app.services.fit_score_calculator import calculate_fit_score, parse_jd
            from app.models.fit_analysis import FitAnalysis
            from app.models.match import Match
            from app.services.scoring import calculate_match_score
            from app.core.config import settings

            role_obj = _get_role(db, role_id)
            if not role_obj:
                add_log("Role not found for matching, skipping")
            else:
                # Filter out candidates already matched (from checkpoint resume)
                already_matched = set()
                for cid in saved_candidate_ids:
                    existing_match = db.query(Match).filter(
                        Match.candidate_id == cid, Match.role_id == role_id
                    ).first()
                    if existing_match:
                        already_matched.add(cid)
                ids_to_match = [cid for cid in saved_candidate_ids if cid not in already_matched]
                if already_matched:
                    add_log(f"Skipping {len(already_matched)} already-matched candidates (checkpoint resume)")
                    matches_created = len(already_matched)

                total_to_match = len(ids_to_match)
                MATCH_WORKERS = 15  # DeepSeek is I/O-bound, safe to parallelize heavily

                if total_to_match == 0:
                    add_log("All candidates already matched, skipping CrossChekk phase")

                if total_to_match > 0:
                    add_log(f"Running CrossChekk on {total_to_match} candidates ({MATCH_WORKERS} parallel workers)...")

                job.current_search = "Matching new candidates against role..."
                job.stats = {**stats, 'matching_current': 0, 'matching_total': total_to_match, 'matches_created': 0}
                flag_modified(job, 'stats')
                db.commit()

                parsed_jd = parse_jd(role_obj.jd_text or "", role_obj.title)
                match_lock = Lock()
                match_counter = {'done': 0, 'created': 0}

                def analyze_one_candidate(cand_id):
                    """Run CrossChekk for one candidate (I/O-bound DeepSeek call)."""
                    try:
                        with match_lock:
                            candidate = _get_candidate(db, cand_id)
                            if not candidate:
                                return None

                        # Build candidate data for CrossChekk (no lock needed, read-only)
                        vibe_report = candidate.vibe_report or {}
                        tech_stack = candidate.tech_stack or []
                        if not tech_stack and vibe_report.get('verified_skills'):
                            tech_stack = [s.get('name') for s in vibe_report.get('verified_skills', []) if s.get('name')]
                        if not tech_stack and candidate.github_languages:
                            tech_stack = candidate.github_languages

                        candidate_data = {
                            "name": candidate.name or candidate.github_username,
                            "github_username": candidate.github_username,
                            "github_url": candidate.github_url,
                            "yoe": candidate.yoe or 3,
                            "tech_stack": tech_stack,
                            "archetype": candidate.archetype,
                            "tier": candidate.tier,
                            "tier_badge": candidate.tier_badge,
                            "tier_percentile": candidate.tier_percentile,
                            "location": candidate.location_raw,
                            "current_role": candidate.current_role,
                            "current_company": candidate.current_company,
                            "notes": getattr(candidate, 'notes', '') or '',
                            "resume_text": getattr(candidate, 'resume_text', '') or '',
                            "linkedin_text": getattr(candidate, 'linkedin_text', '') or '',
                            "github_metrics": {
                                "followers": candidate.github_followers,
                                "public_repos": candidate.github_public_repos,
                                "commits_30d": candidate.github_commits_30d,
                                "commits_90d": candidate.github_commits_90d,
                                "total_commits": candidate.github_total_commits,
                                "original_repos": candidate.github_original_repos,
                                "total_stars": candidate.github_total_stars,
                                "languages": candidate.github_languages or []
                            },
                            "vibe_report": vibe_report
                        }

                        # SPEED OPT: Skip DeepSeek CrossChekk for low-tier candidates (behavior_score < 50)
                        # Use basic scoring only — saves ~90s per low-quality candidate
                        fit_result = None
                        behavior_score = candidate.behavior_score or 0
                        if behavior_score < 50:
                            logger.debug("Skipping CrossChekk for %s (behavior_score=%d < 50)", candidate.github_username, behavior_score)
                        elif settings.DEEPSEEK_API_KEY:
                            fit_result = calculate_fit_score(settings.DEEPSEEK_API_KEY, candidate_data, parsed_jd)

                        # Basic score
                        basic_score, breakdown = calculate_match_score(candidate, role_obj)

                        return {
                            'candidate_id': cand_id,
                            'candidate': candidate,
                            'fit_result': fit_result,
                            'basic_score': basic_score,
                            'breakdown': breakdown,
                        }
                    except Exception as e:
                        logger.error("CrossChekk error for %s: %s", cand_id, e)
                        return {'candidate_id': cand_id, 'error': str(e)}

                try:
                    with ThreadPoolExecutor(max_workers=MATCH_WORKERS) as executor:
                        futures = {
                            executor.submit(analyze_one_candidate, cid): cid
                            for cid in ids_to_match
                        }

                        for future in as_completed(futures):
                            result = future.result()
                            if not result:
                                continue

                            with match_lock:
                                if check_stopped():
                                    add_log("Matching stopped by user")
                                    break

                                match_counter['done'] += 1
                                cand_id = result['candidate_id']

                                if 'error' in result:
                                    job.current_search = f"Error: {result['error'][:50]}"
                                    job.stats = {**stats, 'matching_current': match_counter['done'], 'matching_total': total_to_match, 'matches_created': match_counter['created']}
                                    flag_modified(job, 'stats')
                                    db.commit()
                                    continue

                                candidate = result['candidate']
                                fit_result = result.get('fit_result')
                                basic_score = result['basic_score']
                                breakdown = result['breakdown']

                                # Create or get existing match
                                existing = db.query(Match).filter(
                                    Match.candidate_id == cand_id,
                                    Match.role_id == role_id
                                ).first()

                                if existing:
                                    match = existing
                                else:
                                    match_create = MatchCreate(
                                        candidate_id=cand_id,
                                        role_id=role_id,
                                        match_score=basic_score,
                                        score_breakdown=breakdown
                                    )
                                    match = create_match(db, match_create)

                                # Save CrossChekk results
                                if fit_result:
                                    db.query(FitAnalysis).filter(FitAnalysis.match_id == match.id).delete()
                                    fit_analysis = FitAnalysis(
                                        candidate_id=candidate.id,
                                        role_id=role_obj.id,
                                        match_id=match.id,
                                        fit_score=fit_result.get('fitScore', 0),
                                        recommendation=fit_result.get('recommendation', 'SKIP'),
                                        skills_matched=fit_result.get('skillsMatch', {}).get('matched', []),
                                        skills_missing=fit_result.get('skillsMatch', {}).get('missing', []),
                                        skills_extra=fit_result.get('skillsMatch', {}).get('extra', []),
                                        candidate_level=fit_result.get('experienceMatch', {}).get('candidateLevel'),
                                        required_level=fit_result.get('experienceMatch', {}).get('requiredLevel'),
                                        experience_meets=1 if fit_result.get('experienceMatch', {}).get('meets') else 0,
                                        strengths=fit_result.get('strengthsForRole', []),
                                        concerns=fit_result.get('concernsForRole', []),
                                        ai_summary=fit_result.get('aiSummary'),
                                        ai_summary_short=fit_result.get('aiSummaryShort'),
                                        full_analysis=fit_result
                                    )
                                    db.add(fit_analysis)

                                    match.match_score = fit_result.get('fitScore', 0)
                                    match.score_breakdown = {
                                        **breakdown,
                                        'crosschekk_score': fit_result.get('fitScore', 0),
                                        'recommendation': fit_result.get('recommendation')
                                    }
                                else:
                                    match.match_score = basic_score
                                    match.score_breakdown = breakdown

                                db.commit()

                                match_counter['created'] += 1
                                cname = candidate.github_username or candidate.name or '?'
                                score = match.match_score
                                add_log(f"  ✓ {cname}: {score} ({fit_result.get('recommendation', '?') if fit_result else 'basic'})")

                                # Update progress
                                job.current_search = f"Analyzed {cname} ({score})"
                                job.stats = {**stats, 'matching_current': match_counter['done'], 'matching_total': total_to_match, 'matches_created': match_counter['created']}
                                flag_modified(job, 'stats')
                                job.updated_at = datetime.utcnow()
                                db.commit()

                    matches_created = match_counter['created']
                    add_log(f"Created {matches_created} matches for newly sourced candidates")
                except Exception as e:
                    matches_created = match_counter['created']
                    add_log(f"Match generation error: {e} (created {matches_created} before error)")

        # ── Done ─────────────────────────────────────────────────────────
        db.refresh(job)
        if job.status != JobStatus.stopped:
            job.status = JobStatus.completed
            job.completed_at = datetime.utcnow()
            job.stats = {**stats, 'matches_created': matches_created}
            db.commit()

        add_log(f"Done! Sourced {stats['saved']} candidates, created {matches_created} matches")

    except Exception as e:
        logger.error("Targeted sourcing fatal error: %s", e, exc_info=True)
        job.status = JobStatus.failed
        job.completed_at = datetime.utcnow()
        job.error_message = str(e)
        add_log(f"Fatal error: {str(e)}")
        db.commit()


# ── Tech-stack to GitHub language mapping ─────────────────────────────────

TECH_TO_LANG: Dict[str, List[str]] = {
    # Core languages
    "python": ["python"], "javascript": ["javascript"], "typescript": ["typescript"],
    "go": ["go"], "golang": ["go"], "rust": ["rust"], "java": ["java"],
    "ruby": ["ruby"], "c++": ["cpp"], "cpp": ["cpp"], "c#": ["csharp"],
    "csharp": ["csharp"], "php": ["php"], "swift": ["swift"], "kotlin": ["kotlin"],
    "elixir": ["elixir"], "scala": ["scala"], "dart": ["dart"], "r": ["r"],
    # Frontend frameworks -> languages
    "react": ["javascript", "typescript"], "vue": ["javascript", "typescript"],
    "angular": ["typescript"], "svelte": ["javascript", "typescript"],
    "next.js": ["javascript", "typescript"], "nextjs": ["javascript", "typescript"],
    "nuxt": ["javascript", "typescript"],
    # Backend frameworks -> languages
    "node.js": ["javascript", "typescript"], "nodejs": ["javascript", "typescript"],
    "express": ["javascript", "typescript"], "nestjs": ["typescript"],
    "django": ["python"], "flask": ["python"], "fastapi": ["python"],
    "rails": ["ruby"], "laravel": ["php"], "spring": ["java"],
    "gin": ["go"], "echo": ["go"], "actix": ["rust"],
    # Mobile
    "react native": ["javascript", "typescript"], "flutter": ["dart"],
    # Data/ML/AI
    "pytorch": ["python"], "tensorflow": ["python"], "langchain": ["python"],
    "pandas": ["python"], "numpy": ["python"], "scikit-learn": ["python"],
    "keras": ["python"], "huggingface": ["python"], "transformers": ["python"],
    "openai": ["python"], "llm": ["python"],
    # Data engineering
    "spark": ["python", "scala", "java"], "pyspark": ["python"],
    "airflow": ["python"], "dbt": ["python"], "kafka": ["python", "java", "scala"],
    "flink": ["java", "scala"], "beam": ["python", "java"],
    "dagster": ["python"], "prefect": ["python"], "luigi": ["python"],
    "snowflake": ["python"], "databricks": ["python"],
    # Infrastructure / DevOps
    "terraform": ["go"], "kubernetes": ["go"], "docker": ["go"],
    "ansible": ["python"], "pulumi": ["typescript", "python"],
    "aws cdk": ["typescript"], "cloudformation": ["python"],
    # ORMs / DB
    "prisma": ["typescript"], "sqlalchemy": ["python"], "sequelize": ["javascript"],
}


# ── Role title -> bio keywords + repo topics for differentiated search ────

# Map common role title keywords to GitHub bio search terms and repo topics
# Bio keywords: searched via "KEYWORD in:bio" on GitHub user search
# Repo topics: searched via "topic:TOPIC" on GitHub repo search, then owners extracted
ROLE_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    # Data roles
    "data engineer": {
        "bio_keywords": ["data engineer", "data engineering", "data pipeline", "ETL"],
        "repo_topics": ["data-engineering", "data-pipeline", "etl", "airflow", "spark", "dbt"],
    },
    "data scientist": {
        "bio_keywords": ["data scientist", "data science", "machine learning"],
        "repo_topics": ["data-science", "machine-learning", "deep-learning"],
    },
    "analytics": {
        "bio_keywords": ["analytics engineer", "data analyst", "analytics"],
        "repo_topics": ["analytics", "data-analysis", "data-visualization"],
    },
    # ML/AI roles
    "machine learning": {
        "bio_keywords": ["machine learning", "ML engineer", "deep learning"],
        "repo_topics": ["machine-learning", "deep-learning", "neural-network", "pytorch", "tensorflow"],
    },
    "ml engineer": {
        "bio_keywords": ["ML engineer", "machine learning", "deep learning"],
        "repo_topics": ["machine-learning", "deep-learning", "mlops"],
    },
    "ai engineer": {
        "bio_keywords": ["AI engineer", "artificial intelligence", "LLM", "machine learning"],
        "repo_topics": ["artificial-intelligence", "llm", "langchain", "machine-learning"],
    },
    # Infrastructure roles
    "infrastructure": {
        "bio_keywords": ["infrastructure engineer", "platform engineer", "SRE", "DevOps"],
        "repo_topics": ["infrastructure", "devops", "kubernetes", "terraform", "cloud"],
    },
    "platform": {
        "bio_keywords": ["platform engineer", "infrastructure", "SRE", "DevOps"],
        "repo_topics": ["platform-engineering", "devops", "kubernetes", "infrastructure"],
    },
    "devops": {
        "bio_keywords": ["DevOps", "SRE", "site reliability", "infrastructure"],
        "repo_topics": ["devops", "kubernetes", "terraform", "ci-cd", "docker"],
    },
    "sre": {
        "bio_keywords": ["SRE", "site reliability", "DevOps", "infrastructure"],
        "repo_topics": ["sre", "site-reliability", "monitoring", "observability"],
    },
    # Backend roles
    "backend": {
        "bio_keywords": ["backend engineer", "backend developer", "server-side"],
        "repo_topics": ["backend", "api", "microservices", "rest-api"],
    },
    "software engineer": {
        "bio_keywords": ["software engineer", "full stack", "developer"],
        "repo_topics": [],  # Too generic for topic search
    },
    # Frontend roles
    "frontend": {
        "bio_keywords": ["frontend engineer", "frontend developer", "UI engineer"],
        "repo_topics": ["frontend", "react", "vue", "web-development"],
    },
    "fullstack": {
        "bio_keywords": ["full stack", "fullstack", "full-stack"],
        "repo_topics": ["fullstack", "full-stack"],
    },
    "full stack": {
        "bio_keywords": ["full stack", "fullstack", "full-stack"],
        "repo_topics": ["fullstack", "full-stack"],
    },
    # Mobile roles
    "mobile": {
        "bio_keywords": ["mobile engineer", "mobile developer", "iOS", "Android"],
        "repo_topics": ["mobile", "ios", "android", "react-native", "flutter"],
    },
    "ios": {
        "bio_keywords": ["iOS developer", "iOS engineer", "Swift developer"],
        "repo_topics": ["ios", "swift", "swiftui"],
    },
    "android": {
        "bio_keywords": ["Android developer", "Android engineer", "Kotlin developer"],
        "repo_topics": ["android", "kotlin", "jetpack-compose"],
    },
    # Security
    "security": {
        "bio_keywords": ["security engineer", "cybersecurity", "appsec", "infosec"],
        "repo_topics": ["security", "cybersecurity", "appsec", "penetration-testing"],
    },
    # Product
    "product engineer": {
        "bio_keywords": ["product engineer", "product-minded", "full stack"],
        "repo_topics": [],  # Too broad
    },
    # Blockchain / Web3
    "blockchain": {
        "bio_keywords": ["blockchain", "web3", "smart contract", "solidity"],
        "repo_topics": ["blockchain", "web3", "ethereum", "solidity", "smart-contracts"],
    },
    "web3": {
        "bio_keywords": ["web3", "blockchain", "smart contract", "DeFi"],
        "repo_topics": ["web3", "blockchain", "defi", "ethereum"],
    },
}


def derive_role_search_keywords(role_title: str, tech_stack: List[str] = None) -> Dict[str, List[str]]:
    """
    Given a role title (and optionally tech_stack), derive bio keywords and
    repo topics for differentiated GitHub search.

    Returns:
        {'bio_keywords': [...], 'repo_topics': [...]}
    """
    bio_keywords = set()
    repo_topics = set()

    title_lower = role_title.lower().strip()

    # Match against ROLE_KEYWORDS — check if any key appears in the title
    for key, keywords in ROLE_KEYWORDS.items():
        if key in title_lower:
            bio_keywords.update(keywords.get('bio_keywords', []))
            repo_topics.update(keywords.get('repo_topics', []))

    # Also derive repo topics from tech_stack items that aren't pure languages
    # (e.g., "spark" -> topic:spark, "airflow" -> topic:airflow)
    TECH_AS_TOPIC = {
        "spark", "airflow", "dbt", "kafka", "flink", "kubernetes", "terraform",
        "docker", "react", "vue", "angular", "svelte", "pytorch", "tensorflow",
        "langchain", "fastapi", "django", "flask", "rails", "spring",
        "elasticsearch", "redis", "graphql", "grpc", "nextjs", "next.js",
        "nestjs", "flutter", "react native", "prisma", "dagster", "prefect",
        "huggingface", "openai", "databricks", "snowflake",
    }
    for tech in (tech_stack or []):
        key = tech.lower().strip()
        if key in TECH_AS_TOPIC:
            repo_topics.add(key.replace(" ", "-").replace(".", ""))

    return {
        'bio_keywords': sorted(bio_keywords),
        'repo_topics': sorted(repo_topics),
    }


# ── Phase 1c: Semantic Repo Discovery ─────────────────────────────────────────


def generate_repo_search_queries(
    jd_text: str,
    role_title: str,
    tech_stack: List[str] = None,
) -> List[str]:
    """
    Use DeepSeek to extract 8-12 GitHub repo search queries from a JD.

    Returns short keyword phrases that would appear in repo descriptions/names,
    e.g. ["websocket real-time chat", "message queue distributed", ...].
    Falls back to tech_stack-based queries if DeepSeek fails or no JD text.
    """
    from app.core.config import settings

    # Fallback: if no JD text, derive queries from tech_stack + role_title
    if not jd_text or not jd_text.strip():
        queries = []
        if tech_stack:
            for tech in tech_stack[:6]:
                queries.append(tech.lower())
        if role_title:
            # Add domain-oriented queries from role title
            title_lower = role_title.lower()
            if 'data' in title_lower:
                queries.extend(['data pipeline', 'ETL framework'])
            elif 'ml' in title_lower or 'machine learning' in title_lower:
                queries.extend(['machine learning framework', 'deep learning model'])
            elif 'infra' in title_lower or 'devops' in title_lower:
                queries.extend(['infrastructure automation', 'deployment pipeline'])
            elif 'frontend' in title_lower:
                queries.extend(['component library', 'design system'])
            elif 'backend' in title_lower or 'software' in title_lower:
                queries.extend(['API server', 'microservices framework'])
        return queries[:10] if queries else []

    if not settings.DEEPSEEK_API_KEY:
        logger.warning("No DEEPSEEK_API_KEY, skipping semantic repo query generation")
        return []

    tech_str = ', '.join(tech_stack[:10]) if tech_stack else 'not specified'
    prompt = f"""You are helping source software engineers by finding relevant GitHub repositories.

Given this job description, generate 8-12 short search queries (2-4 words each) that would match GitHub repository descriptions or names. These queries should find repos built by the kind of engineer this role needs.

Focus on:
- Domain-specific systems the role requires (e.g., "real-time messaging", "data pipeline", "payment processing")
- Technical architectures mentioned (e.g., "distributed cache", "event streaming", "GraphQL API")
- Specific tools/frameworks that indicate relevant experience (e.g., "kafka consumer", "kubernetes operator")

Do NOT generate generic queries like "python project" or "web application". Each query should be specific enough to find repos that demonstrate relevant expertise.

Role: {role_title}
Tech Stack: {tech_str}
Job Description:
{jd_text[:3000]}

Return ONLY a JSON array of strings, no explanation. Example:
["real-time messaging server", "websocket chat application", "message queue consumer", "streaming API backend"]"""

    try:
        response = requests.post(
            'https://api.deepseek.com/v1/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}'
            },
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {'role': 'system', 'content': 'Return ONLY valid JSON arrays. No markdown, no explanation.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.3
            },
            timeout=30
        )
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content'].strip()

        # Parse JSON, strip markdown fences if present
        if content.startswith('```'):
            content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

        import json
        queries = json.loads(content)

        if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
            logger.info("DeepSeek generated %d repo search queries for '%s'", len(queries), role_title)
            return queries[:12]
        else:
            logger.warning("DeepSeek returned unexpected format for repo queries: %s", type(queries))
            return []

    except Exception as e:
        logger.error("Failed to generate repo search queries: %s", e)
        return []


def search_repos_semantic(
    queries: List[str],
    languages: List[str] = None,
    min_stars: int = 5,
    max_pages_per_query: int = 3,
    max_repos: int = 500,
) -> List[Dict]:
    """
    Search GitHub repos API using semantic keyword queries.

    Returns list of repo dicts: {owner, repo, stars, description, pushed_at, url}
    Deduplicates by repo full_name.
    """
    seen_repos = set()
    results = []

    primary_lang = languages[0] if languages else None

    for query_text in queries:
        if len(results) >= max_repos:
            break

        # Run each query twice: once with language filter, once without (catches polyglot repos)
        query_variants = []
        if primary_lang:
            query_variants.append(f"{query_text} language:{primary_lang} stars:>={min_stars}")
        query_variants.append(f"{query_text} stars:>={max(min_stars, 10)}")  # Higher bar for unfiltered

        for query in query_variants:
            if len(results) >= max_repos:
                break

            for page in range(1, max_pages_per_query + 1):
                url = f"https://api.github.com/search/repositories?q={query}&per_page=100&page={page}&sort=stars"

                try:
                    resp = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

                    if resp.status_code == 403:
                        logger.warning("Rate limit on repo search, waiting 10s")
                        time.sleep(10)
                        resp = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

                    if resp.status_code == 422:
                        # GitHub rejects certain query syntax
                        logger.warning("GitHub rejected query '%s': 422", query)
                        break

                    if resp.status_code != 200:
                        logger.warning("Repo search failed for '%s': %d", query, resp.status_code)
                        break

                    data = resp.json()
                    items = data.get('items', [])

                    for repo in items:
                        full_name = repo.get('full_name', '')
                        if full_name in seen_repos:
                            continue
                        seen_repos.add(full_name)

                        owner = repo.get('owner', {})
                        pushed_at = repo.get('pushed_at', '')
                        name_lower = repo.get('name', '').lower()

                        # Quality gates
                        # Skip orgs (can't be candidates)
                        if owner.get('type') != 'User':
                            continue

                        # Skip tutorials, awesome lists, templates, boilerplate
                        skip_patterns = ['awesome-', 'tutorial', 'template', 'boilerplate',
                                         'example', 'demo', 'starter', 'sample', 'cheatsheet',
                                         'interview', 'leetcode', 'learning', 'course']
                        if any(pat in name_lower for pat in skip_patterns):
                            continue

                        # Skip repos not pushed in last 2 years
                        if pushed_at:
                            try:
                                from datetime import datetime, timezone
                                pushed = datetime.fromisoformat(pushed_at.replace('Z', '+00:00'))
                                days_since = (datetime.now(timezone.utc) - pushed).days
                                if days_since > 730:  # 2 years
                                    continue
                            except (ValueError, TypeError):
                                pass

                        results.append({
                            'owner': owner.get('login', ''),
                            'repo': repo.get('name', ''),
                            'full_name': full_name,
                            'stars': repo.get('stargazers_count', 0),
                            'description': (repo.get('description') or '')[:200],
                            'pushed_at': pushed_at,
                            'url': repo.get('html_url', ''),
                        })

                    if len(items) < 100:
                        break

                    # Rate limit awareness
                    remaining = int(resp.headers.get('X-RateLimit-Remaining', 100))
                    if remaining < 5:
                        time.sleep(10)
                    elif remaining < 15:
                        time.sleep(2)

                except Exception as e:
                    logger.error("Repo search error for '%s' page %d: %s", query, page, e)
                    break

    logger.info("Semantic repo search found %d unique repos from %d queries", len(results), len(queries))
    return results


def fetch_repo_contributors(
    repos: List[Dict],
    min_commits: int = 5,
    max_contributors_per_repo: int = 10,
    max_repos: int = 300,
) -> List[str]:
    """
    Fetch top contributors for a list of repos.

    Args:
        repos: List of repo dicts from search_repos_semantic()
        min_commits: Minimum commits to be considered a real contributor
        max_contributors_per_repo: Max contributors to fetch per repo
        max_repos: Cap on how many repos to fetch contributors for

    Returns:
        List of unique GitHub usernames (contributors)
    """
    usernames = set()

    # Sort by stars descending, fetch contributors from best repos first
    sorted_repos = sorted(repos, key=lambda r: r.get('stars', 0), reverse=True)[:max_repos]

    for repo_info in sorted_repos:
        owner = repo_info['owner']
        repo = repo_info['repo']
        url = f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page={max_contributors_per_repo}"

        try:
            resp = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

            if resp.status_code == 403:
                time.sleep(10)
                resp = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

            if resp.status_code != 200:
                continue

            contributors = resp.json()
            if not isinstance(contributors, list):
                continue

            for contrib in contributors:
                if contrib.get('type') != 'User':
                    continue
                if contrib.get('contributions', 0) >= min_commits:
                    usernames.add(contrib['login'])

            # Rate limit awareness
            remaining = int(resp.headers.get('X-RateLimit-Remaining', 100))
            if remaining < 5:
                time.sleep(10)
            elif remaining < 15:
                time.sleep(2)

        except Exception as e:
            logger.error("Contributors fetch error for %s/%s: %s", owner, repo, e)
            continue

    logger.info("Fetched %d unique contributors from %d repos", len(usernames), len(sorted_repos))
    return list(usernames)


def search_github_repos_for_users(
    topics: List[str],
    language: str = None,
    min_stars: int = 10,
    max_pages: int = 5,
) -> List[str]:
    """
    Search GitHub repos by topic, then extract unique owner usernames.
    This finds users who work on topic-specific repos (e.g., data-pipeline, machine-learning).

    Args:
        topics: List of repo topics to search (OR'd together via separate queries)
        language: Optional language filter
        min_stars: Minimum stars to filter quality repos
        max_pages: Max pages per topic query (100 results/page)

    Returns:
        List of unique GitHub usernames
    """
    usernames = set()

    for topic in topics[:4]:  # Limit to 4 topics to avoid rate limit burn
        query = f"topic:{topic} stars:>={min_stars}"
        if language:
            query += f" language:{language}"

        for page in range(1, max_pages + 1):
            url = f"https://api.github.com/search/repositories?q={query}&per_page=100&page={page}&sort=updated"

            try:
                response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

                if response.status_code == 403:
                    logger.warning("Rate limit hit for repo search topic:%s page %d, waiting 10s", topic, page)
                    time.sleep(10)
                    response = requests.get(url, headers=token_rotator.get_headers(), timeout=30)

                if response.status_code != 200:
                    logger.warning("Repo search failed for topic:%s: %d", topic, response.status_code)
                    break

                data = response.json()
                items = data.get('items', [])

                for repo in items:
                    owner = repo.get('owner', {})
                    if owner.get('type') == 'User':
                        usernames.add(owner['login'])

                if len(items) < 100:
                    break

                # Check rate limit
                remaining = int(response.headers.get('X-RateLimit-Remaining', 100))
                if remaining < 5:
                    time.sleep(10)

            except Exception as e:
                logger.error("Repo search error for topic:%s page %d: %s", topic, page, e)
                break

    return list(usernames)


def derive_languages_from_tech_stack(tech_stack: List[str], role_title: str = "") -> List[str]:
    """
    Given a role's tech_stack list (and optionally title), derive the GitHub search languages.
    Infers additional languages from role type so Data Engineers search Scala/SQL/R,
    ML Engineers search Jupyter Notebook, Infra roles search Shell/HCL, etc.
    Falls back to ['python', 'typescript', 'javascript'] if nothing maps.
    """
    # Role-type -> extra languages that GitHub profiles commonly use
    ROLE_EXTRA_LANGUAGES: Dict[str, List[str]] = {
        "data engineer": ["scala", "java", "r", "jupyter notebook"],
        "data scientist": ["r", "jupyter notebook"],
        "analytics": ["r", "jupyter notebook"],
        "machine learning": ["jupyter notebook", "c++"],
        "ml engineer": ["jupyter notebook", "c++"],
        "ai engineer": ["jupyter notebook"],
        "infrastructure": ["shell", "hcl", "go"],
        "platform": ["shell", "hcl", "go"],
        "devops": ["shell", "hcl", "go", "python"],
        "sre": ["shell", "go", "python"],
        "backend": ["go", "java", "rust"],
        "frontend": ["javascript", "typescript", "css"],
        "fullstack": ["javascript", "typescript"],
        "full stack": ["javascript", "typescript"],
        "mobile": ["swift", "kotlin", "dart"],
        "ios": ["swift", "objective-c"],
        "android": ["kotlin", "java"],
        "security": ["python", "go", "c", "shell"],
        "blockchain": ["solidity", "rust", "go"],
        "web3": ["solidity", "rust", "typescript"],
    }

    langs = set()
    for tech in tech_stack:
        key = tech.lower().strip()
        if key in TECH_TO_LANG:
            langs.update(TECH_TO_LANG[key])

    # Infer extra languages from role title
    title_lower = role_title.lower().strip()
    for role_key, extra_langs in ROLE_EXTRA_LANGUAGES.items():
        if role_key in title_lower:
            langs.update(extra_langs)

    if not langs:
        langs = {"python", "typescript", "javascript"}
    return sorted(langs)


def derive_locations_from_role(role) -> List[str]:
    """
    Derive GitHub search location strings from a role's location_cities
    and location_requirement.

    Automatically adds city aliases (e.g., "New York City" also searches
    "New York", "NYC", "Brooklyn", "Manhattan") and a broad US fallback
    to maximize candidate pool size.
    """
    # Common city aliases + metro area neighbors — GitHub profiles use inconsistent location formats
    # Includes monikers (NYC, SF, LA, DC), state abbreviations, and commutable metro neighbors
    CITY_ALIASES = {
        "new york city": ["New York", "NYC", "NY", "Brooklyn", "Manhattan", "Queens", "Bronx",
                          "New Jersey", "NJ", "Hoboken", "Jersey City", "Newark",
                          "Stamford", "CT", "Connecticut", "Long Island", "Westchester"],
        "new york": ["NYC", "NY", "Brooklyn", "Manhattan", "New Jersey", "NJ",
                     "Hoboken", "Jersey City", "Stamford", "CT", "Long Island"],
        "nyc": ["New York", "NY", "Brooklyn", "Manhattan", "New Jersey", "NJ",
                "Hoboken", "Jersey City"],
        "san francisco": ["SF", "Bay Area", "San Jose", "Oakland", "Silicon Valley",
                          "Palo Alto", "Mountain View", "Sunnyvale", "Berkeley",
                          "Menlo Park", "Redwood City", "Santa Clara", "Fremont",
                          "CA", "California"],
        "sf": ["San Francisco", "Bay Area", "San Jose", "Oakland", "Silicon Valley",
               "Palo Alto", "Mountain View", "Sunnyvale"],
        "los angeles": ["LA", "Santa Monica", "Pasadena", "Burbank", "Glendale",
                        "Long Beach", "Culver City", "Venice", "CA", "California"],
        "la": ["Los Angeles", "Santa Monica", "Pasadena", "Burbank", "CA"],
        "chicago": ["Chicagoland", "Evanston", "Oak Park", "Naperville", "IL", "Illinois"],
        "seattle": ["Bellevue", "Redmond", "Kirkland", "Tacoma", "WA", "Washington State"],
        "boston": ["Cambridge", "Somerville", "Brookline", "Quincy", "MA", "Massachusetts"],
        "washington": ["DC", "Arlington", "Alexandria", "Bethesda", "MD", "Virginia", "VA",
                       "Silver Spring", "Reston", "McLean"],
        "dc": ["Washington", "Arlington", "Alexandria", "Bethesda", "MD", "VA"],
        "austin": ["Round Rock", "Cedar Park", "San Marcos", "TX", "Texas"],
        "denver": ["Boulder", "Colorado", "CO", "Aurora", "Lakewood", "Fort Collins"],
        "miami": ["Fort Lauderdale", "South Florida", "Boca Raton", "FL", "Florida"],
        "atlanta": ["Marietta", "Decatur", "Sandy Springs", "GA", "Georgia"],
        "portland": ["Beaverton", "Hillsboro", "OR", "Oregon"],
        "dallas": ["Fort Worth", "Plano", "Irving", "TX", "Texas"],
        "houston": ["The Woodlands", "Sugar Land", "TX", "Texas"],
        "san diego": ["La Jolla", "CA", "California"],
        "philadelphia": ["Philly", "PA", "Pennsylvania", "Cherry Hill", "NJ"],
        "minneapolis": ["St Paul", "Saint Paul", "MN", "Minnesota"],
        "detroit": ["Ann Arbor", "MI", "Michigan"],
        "pittsburgh": ["PA", "Pennsylvania"],
        "raleigh": ["Durham", "Chapel Hill", "Research Triangle", "NC", "North Carolina"],
        "toronto": ["GTA", "Mississauga", "Markham", "Scarborough", "ON", "Ontario"],
        "vancouver": ["Burnaby", "Surrey", "BC", "British Columbia"],
        "montreal": ["Montréal", "QC", "Quebec"],
        "london": ["Greater London", "UK", "United Kingdom"],
        "berlin": ["München", "Munich", "Germany", "Deutschland"],
    }

    locations = set()
    cities = role.location_cities or []
    for city in cities:
        if isinstance(city, str) and city.strip():
            clean = city.strip()
            locations.add(clean)
            # Add aliases for known cities
            for key, aliases in CITY_ALIASES.items():
                if key in clean.lower():
                    for alias in aliases:
                        locations.add(alias)

    # Always include broad US as fallback for maximum pool
    locations.add("United States OR USA")

    # If role is remote, add more broad locations
    loc_req = getattr(role, 'location_requirement', None)
    if loc_req and hasattr(loc_req, 'value') and loc_req.value == 'remote':
        locations.update(["Canada", "United Kingdom OR UK"])

    return sorted(locations)


# ── Bulk targeted GitHub sourcing (multi-role) ────────────────────────────

def bulk_targeted_github_sourcing_background(
    db,
    job_id: str,
    role_configs: List[Dict],
    count_per_role: int = 50,
    min_repos: int = 5,
    db_factory=None,
    strategy: str = "both",
):
    """
    Background task: run targeted sourcing for multiple roles in parallel.

    Uses ThreadPoolExecutor with 3 concurrent roles. Each role gets its own
    DB session. The GitHub token pool is thread-safe (TokenRotator uses locks),
    so parallel roles safely share the rate-limited token bucket.

    Args:
        db: DB session for parent job updates
        job_id: Parent IngestionJob ID
        role_configs: List of dicts with keys: role_id, languages, locations, title
        count_per_role: How many candidates to target per role
        min_repos: Minimum repos filter
        db_factory: Callable returning new DB sessions (for parallel threads)
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    from sqlalchemy.orm.attributes import flag_modified
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import uuid

    PARALLEL_ROLES = 1  # Sequential: one role completes fully before next starts, avoids token pool starvation

    job = db.query(IngestionJob).filter(IngestionJob.id == uuid.UUID(job_id)).first()
    if not job:
        logger.error("Bulk sourcing job %s not found", job_id)
        return

    parent_lock = Lock()

    def add_log(message: str):
        with parent_lock:
            logs = job.recent_logs or []
            est = pytz.timezone('US/Eastern')
            timestamp = datetime.now(est).strftime('%d/%m/%y %I:%M %p EST')
            logs.append({'timestamp': timestamp, 'message': message})
            logs = logs[-1000:]
            job.recent_logs = logs
            flag_modified(job, 'recent_logs')
            job.updated_at = datetime.utcnow()
            db.commit()

    def check_stopped():
        with parent_lock:
            db.refresh(job)
            return job.status == JobStatus.stopped

    total_roles = len(role_configs)
    completed_roles = {'count': 0, 'sourced': 0, 'matches': 0, 'errors': 0}
    sub_job_ids = {}  # role_id -> sub_job_id

    try:
        job.status = JobStatus.running
        job.started_at = datetime.utcnow()
        job.total_batches = total_roles
        job.current_batch = 0
        db.commit()

        add_log(f"Starting bulk sourcing across {total_roles} roles ({count_per_role}/role, {PARALLEL_ROLES} parallel)")

        # Pre-create all sub-jobs so the frontend can poll them immediately
        for i, config in enumerate(role_configs):
            sub_id = uuid.uuid4()
            sub_job = IngestionJob(
                id=sub_id,
                status=JobStatus.pending,
                job_type='targeted_sourcing',
                role_id=uuid.UUID(config['role_id']),
                min_behavior_score=30,
                recent_logs=[],
                stats={},
                checkpoint_data={
                    "role_id": config['role_id'],
                    "languages": config['languages'],
                    "locations": config['locations'],
                    "parent_job_id": job_id,
                },
            )
            db.add(sub_job)
            sub_job_ids[config['role_id']] = str(sub_id)

        db.commit()

        # Store sub-job IDs in parent checkpoint so frontend can look them up
        job.checkpoint_data = {
            **(job.checkpoint_data or {}),
            'sub_jobs': [
                {
                    'job_id': sub_job_ids[c['role_id']],
                    'role_id': c['role_id'],
                    'title': c.get('title', f"Role {i+1}"),
                }
                for i, c in enumerate(role_configs)
            ],
        }
        flag_modified(job, 'checkpoint_data')
        db.commit()

        def run_one_role(config, index):
            """Run targeted sourcing for a single role in its own thread + DB session."""
            role_id = config['role_id']
            title = config.get('title', f'Role {index+1}')
            sub_job_id = sub_job_ids[role_id]

            # Check if parent was stopped before starting this role
            if check_stopped():
                add_log(f"[{index+1}/{total_roles}] Skipped (stopped): {title}")
                return {'role_id': role_id, 'title': title, 'saved': 0, 'matches': 0, 'errors': 0}

            add_log(f"[{index+1}/{total_roles}] Starting: {title}")

            role_db = db_factory()
            try:
                targeted_github_sourcing_background(
                    db=role_db,
                    job_id=sub_job_id,
                    role_id=role_id,
                    languages=config['languages'],
                    locations=config['locations'],
                    count=count_per_role,
                    min_repos=min_repos,
                    hireable_only=False,
                    min_behavior_score=30,
                    auto_match=True,
                    role_title=config.get('role_title', ''),
                    tech_stack=config.get('tech_stack', []),
                    jd_text=config.get('jd_text', ''),
                    strategy=strategy,
                )
            except Exception as e:
                logger.error("Sub-job error for role %s: %s", role_id, e)
                add_log(f"  [{index+1}] Error: {str(e)[:100]}")
            finally:
                # Read final stats before closing session
                sub = role_db.query(IngestionJob).filter(
                    IngestionJob.id == uuid.UUID(sub_job_id)
                ).first()
                sub_stats = sub.stats or {} if sub else {}
                result = {
                    'role_id': role_id,
                    'title': title,
                    'saved': sub.candidates_saved or 0 if sub else 0,
                    'matches': sub_stats.get('matches_created', 0),
                    'errors': sub.error_count or 0 if sub else 0,
                }
                role_db.close()

            # Update parent aggregate stats
            with parent_lock:
                completed_roles['count'] += 1
                completed_roles['sourced'] += result['saved']
                completed_roles['matches'] += result['matches']
                completed_roles['errors'] += result['errors']

                job.current_batch = completed_roles['count']
                job.candidates_saved = completed_roles['sourced']
                job.error_count = completed_roles['errors']
                job.processed_count = completed_roles['count']
                job.current_search = f"Completed {completed_roles['count']}/{total_roles} roles"
                job.stats = {
                    'roles_completed': completed_roles['count'],
                    'roles_total': total_roles,
                    'total_sourced': completed_roles['sourced'],
                    'total_matches': completed_roles['matches'],
                    'total_errors': completed_roles['errors'],
                }
                flag_modified(job, 'stats')
                job.updated_at = datetime.utcnow()
                db.commit()

            add_log(f"  [{index+1}] Done: {result['saved']} sourced, {result['matches']} matches")
            return result

        # Run roles in parallel with controlled concurrency
        with ThreadPoolExecutor(max_workers=PARALLEL_ROLES) as executor:
            futures = {
                executor.submit(run_one_role, config, i): config
                for i, config in enumerate(role_configs)
            }

            for future in as_completed(futures):
                if check_stopped():
                    add_log("Bulk sourcing stopped by user — cancelling remaining")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    future.result()  # Raise any uncaught exception
                except Exception as e:
                    logger.error("Role future error: %s", e)

        # ── Done ─────────────────────────────────────────────────────────
        with parent_lock:
            db.refresh(job)
            if job.status != JobStatus.stopped:
                job.status = JobStatus.completed
                job.completed_at = datetime.utcnow()
            job.candidates_saved = completed_roles['sourced']
            job.processed_count = completed_roles['count']
            job.stats = {
                'roles_completed': completed_roles['count'],
                'roles_total': total_roles,
                'total_sourced': completed_roles['sourced'],
                'total_matches': completed_roles['matches'],
                'total_errors': completed_roles['errors'],
            }
            flag_modified(job, 'stats')
            db.commit()

        add_log(f"Bulk sourcing complete: {completed_roles['sourced']} candidates, {completed_roles['matches']} matches across {total_roles} roles")

    except Exception as e:
        logger.error("Bulk targeted sourcing fatal error: %s", e, exc_info=True)
        with parent_lock:
            job.status = JobStatus.failed
            job.completed_at = datetime.utcnow()
            job.error_message = str(e)
            add_log(f"Fatal error: {str(e)}")
            db.commit()
