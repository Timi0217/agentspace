"""
Gateway Authentication - Dependency utilities for auth
"""

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import hashlib
from typing import Optional
from app.database import get_db
from app.gateway_models import GatewayUser, GatewayAgent

security = HTTPBearer()


async def get_optional_bearer_token(request: Request) -> Optional[HTTPAuthorizationCredentials]:
    """Get Bearer token from request if present, otherwise return None."""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None

    try:
        scheme, credentials = auth_header.split()
        if scheme.lower() != "bearer":
            return None
        return HTTPAuthorizationCredentials(scheme=scheme, credentials=credentials)
    except:
        return None


async def get_current_user(credentials = Depends(security),
                          db: Session = Depends(get_db)) -> GatewayUser:
    """
    Verify JWT token and return current user.
    Token format: base64 encoded JSON with user_id and exp
    """
    try:
        import json
        import base64
        from datetime import datetime

        token = credentials.credentials
        payload = json.loads(base64.b64decode(token).decode())

        # Check expiration
        if payload.get("exp", 0) < datetime.utcnow().timestamp():
            raise HTTPException(status_code=401, detail="Token expired")

        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = db.query(GatewayUser).filter(GatewayUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return user

    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials")


async def get_current_agent(credentials = Depends(security),
                           db: Session = Depends(get_db)) -> GatewayAgent:
    """
    Verify agent API key and return current agent.
    API key format: chekk_<random_string>
    """
    try:
        api_key = credentials.credentials

        if not api_key.startswith("chekk_"):
            raise HTTPException(status_code=401, detail="Invalid API key format")

        # Hash the provided key and compare
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        agent = db.query(GatewayAgent).filter(
            GatewayAgent.api_key_hash == api_key_hash
        ).first()

        if not agent:
            raise HTTPException(status_code=401, detail="Invalid API key")

        if not agent.is_active:
            raise HTTPException(status_code=401, detail="Agent is inactive")

        return agent

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials")


async def get_optional_user(credentials = Depends(get_optional_bearer_token),
                           db: Session = Depends(get_db)) -> Optional[GatewayUser]:
    """Get current user if authenticated, otherwise None."""
    if not credentials:
        return None

    try:
        import json
        import base64
        from datetime import datetime

        token = credentials.credentials
        payload = json.loads(base64.b64decode(token).decode())

        # Check expiration
        if payload.get("exp", 0) < datetime.utcnow().timestamp():
            return None

        user_id = payload.get("user_id")
        if not user_id:
            return None

        user = db.query(GatewayUser).filter(GatewayUser.id == user_id).first()
        return user

    except:
        return None


async def get_optional_agent(credentials = Depends(get_optional_bearer_token),
                            db: Session = Depends(get_db)) -> Optional[GatewayAgent]:
    """Get current agent if authenticated, otherwise None."""
    if not credentials:
        return None

    try:
        api_key = credentials.credentials

        if not api_key.startswith("chekk_"):
            return None

        # Hash the provided key and compare
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        agent = db.query(GatewayAgent).filter(
            GatewayAgent.api_key_hash == api_key_hash
        ).first()

        if not agent or not agent.is_active:
            return None

        return agent

    except:
        return None
