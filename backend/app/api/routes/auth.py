"""Authentication and authorization routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.core.config import settings
from app.gateway_models import GatewayUser
import os
import base64
import httpx
import json
import secrets
from urllib.parse import urlencode, quote

router = APIRouter(prefix="/auth", tags=["auth"])

# GitHub OAuth configuration
# These env vars must be set in Railway: GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET
# The container reads these at startup via os.getenv()
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
# Callback URL GitHub redirects back to. Must match the OAuth app's registered
# callback. Defaults to the agentspace backend; override via env if needed.
GITHUB_REDIRECT_URI = os.getenv(
    "GITHUB_REDIRECT_URI",
    "https://agentspace-production-5279.up.railway.app/api/v1/auth/callback",
)


def _generate_session_token(user_id: str) -> str:
    """Mint a session token in the same format gateway_auth.get_current_user expects.

    Format: base64(json({"user_id": ..., "exp": <unix ts>})).
    """
    payload = {
        "user_id": str(user_id),
        "exp": (datetime.utcnow() + timedelta(days=30)).timestamp(),
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()




@router.get("/login")
def github_oauth_login():
    """
    Initiate GitHub OAuth flow.

    Redirects user to GitHub's authorization page. After user authorizes,
    GitHub redirects back to /callback with an authorization code.
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET."
        )

    # Generate a random state token for CSRF protection
    state = secrets.token_urlsafe(32)

    # Construct GitHub OAuth authorization URL
    github_auth_url = "https://github.com/login/oauth/authorize"
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_REDIRECT_URI,
        "scope": "user:email",  # Request email scope to get user email
        "state": state,
    }

    auth_url = f"{github_auth_url}?{urlencode(params)}"
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def github_oauth_callback(
    code: str = Query(...),
    state: str = Query(None),
    db: Session = Depends(get_db),
):
    """
    GitHub OAuth callback endpoint.

    Exchanges the authorization code for a GitHub access token, looks up the
    GitHub user, finds-or-creates a GatewayUser account, mints a session token,
    and redirects back to the frontend with the session in the URL hash:

        {FRONTEND_URL}/auth/callback#auth=<url-encoded JSON {token, login, name, avatar_url}>

    The frontend stores this session; that same token then authenticates the
    user when they provision agent registration tokens, linking agents to the
    account.
    """
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        async with httpx.AsyncClient() as client:
            # 1. Exchange code for a GitHub access token
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": GITHUB_REDIRECT_URI,
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_data = token_response.json()

            if "error" in token_data:
                raise HTTPException(
                    status_code=400,
                    detail=token_data.get("error_description", "OAuth failed"),
                )

            access_token = token_data.get("access_token")
            if not access_token:
                raise HTTPException(status_code=400, detail="Failed to get access token")

            # 2. Get the GitHub user profile
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_response.raise_for_status()
            github_user = user_response.json()

        github_login = github_user.get("login", "")
        github_name = github_user.get("name") or github_login
        avatar_url = github_user.get("avatar_url")
        # GitHub may hide the email; fall back to the stable noreply address.
        email = github_user.get("email") or f"{github_login}@users.noreply.github.com"

        # 3. Find or create the user account
        user = (
            db.query(GatewayUser)
            .filter(
                (GatewayUser.github_username == github_login)
                | (GatewayUser.email == email)
            )
            .first()
        )
        if not user:
            user = GatewayUser(
                email=email,
                username=github_login,
                github_username=github_login,
                avatar_url=avatar_url,
            )
            db.add(user)
        else:
            # Keep profile fresh on each login
            user.github_username = github_login
            if avatar_url:
                user.avatar_url = avatar_url

        user.last_login = datetime.utcnow()
        db.commit()
        db.refresh(user)

        # 4. Mint a session token the gateway auth layer understands
        session_token = _generate_session_token(str(user.id))

        # 5. Redirect back to the frontend with the session in the hash
        payload = {
            "token": session_token,
            "login": github_login,
            "name": github_name,
            "avatar_url": avatar_url,
        }
        frontend = settings.FRONTEND_URL.rstrip("/")
        redirect_url = f"{frontend}/auth/callback#auth={quote(json.dumps(payload))}"
        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"GitHub API error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

