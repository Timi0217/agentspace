"""Authentication and authorization routes."""

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from starlette.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from app.db.base import SessionLocal
from app.models.registration_token import RegistrationToken
import os
import httpx
import json
import secrets
from urllib.parse import urlencode
import threading
from typing import Optional

router = APIRouter(prefix="/auth", tags=["auth"])

# GitHub OAuth configuration
# These env vars must be set in Railway: GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET
# The container reads these at startup via os.getenv()
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
# Hardcode the callback URL - always points to /api/v1/auth/callback (not the old hybrid endpoint)
GITHUB_REDIRECT_URI = "https://chekk-production.up.railway.app/api/v1/auth/callback"






def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
    state: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    GitHub OAuth callback endpoint.

    Handles the OAuth redirect from GitHub after user authorization.
    Exchanges authorization code for access token, gets user info, and
    generates registration token.
    """
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        # Exchange code for GitHub access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                },
                headers={"Accept": "application/json"}
            )
            token_response.raise_for_status()
            token_data = token_response.json()

            if "error" in token_data:
                raise HTTPException(status_code=400, detail=token_data.get("error_description", "OAuth failed"))

            access_token = token_data.get("access_token")
            if not access_token:
                raise HTTPException(status_code=400, detail="Failed to get access token")

            # Get GitHub user info
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_response.raise_for_status()
            github_user = user_response.json()

            github_login = github_user.get("login", "")
            github_name = github_user.get("name", github_login)

            # Extract handle from request state (format: "handle:name")
            # For now, use GitHub login as handle
            handle = github_login.replace("-", "_")  # Normalize handle

            # Generate registration token by calling the token endpoint internally
            token_string = RegistrationToken.generate_token()
            expires_at = RegistrationToken.get_expiration_time(hours=1)

            # Create registration token
            reg_token = RegistrationToken(
                token=token_string,
                handle=handle,
                name=github_name,
                created_by_github=github_login,
                expires_at=expires_at,
            )

            db.add(reg_token)
            db.commit()
            db.refresh(reg_token)

            # Return token response
            return {
                "status": "success",
                "message": "Registration successful!",
                "token": token_string,
                "handle": handle,
                "name": github_name,
                "expires_at": expires_at.isoformat(),
                "next_step": "Use this token with the MCP protocol to register your agent"
            }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"GitHub API error: {str(e)}")
    except Exception as e:
        # Catch all other exceptions and return detailed error
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

