from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, APIKeyQuery
from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)

# Paths that bypass API key auth (public profiles, webhooks, health)
PUBLIC_PATH_PREFIXES = (
    "/api/v1/public/",
    "/api/v1/webhooks/",
    "/api/v1/references/",     # Public reference form
    "/health",
    "/",
)


async def require_api_key(
    request: Request,
    header_key: str = Security(api_key_header),
    query_key: str = Security(api_key_query),
):
    """
    Dependency that enforces API key authentication.

    Checks X-API-Key header first, then api_key query param.
    If API_KEY is not configured in settings, auth is disabled (open access).
    Public paths (webhooks, public profiles) always bypass auth.
    """
    # If no API key is configured, skip auth (backwards-compatible)
    if not settings.API_KEY:
        return None

    # Allow public paths through without auth
    path = request.url.path
    if any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES):
        return None

    provided_key = header_key or query_key
    if not provided_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide via X-API-Key header or api_key query param.",
        )

    if provided_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key.")

    return provided_key
