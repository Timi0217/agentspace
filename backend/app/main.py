import asyncio
import logging
import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool

from app.api.routes import router
from app.api.mcp_routes import router as mcp_router
from app.api.routes.auth import router as auth_router
from app.gateway_routes import router as gateway_router
from app.core.config import settings
from app.core.auth import require_api_key
from app.core.logging import setup_logging, get_logger
from app.database import SessionLocal, engine, Base

# Import models to ensure they're registered with SQLAlchemy
from app.models.ingestion_job import IngestionJob
from app.models.registration_token import RegistrationToken
# Import gateway models so their tables (gateway_users, gateway_agents,
# gateway_user_agents, registration_tokens, etc.) are registered on Base.metadata
# and can be created on startup.
import app.gateway_models  # noqa: F401

# Setup logging early
setup_logging()
logger = get_logger(__name__)

app = FastAPI(
    title="Chekk API",
    description="AI-Powered Recruiting Platform for Founding Engineers + Agent Registration via MCP",
    version="1.0.9",  # Enforce GitHub OAuth-only registration
)

# CORS middleware - parse comma-separated origins from env var
origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include public MCP router without auth (agents don't have API keys during discovery)
app.include_router(mcp_router, prefix="/api/v1")

# Include auth router without auth (used for token generation after OAuth)
app.include_router(auth_router, prefix="/api/v1")

# Include gateway router (agent registration, rooms, messaging). It declares its
# own "/api/v1/gateway" prefix and enforces auth per-route via get_current_user.
app.include_router(gateway_router)

# Include API router with auth dependency
# Auth is enforced when API_KEY is set in env; disabled otherwise (backwards-compatible).
# Public endpoints (/public/*, /webhooks/*) bypass auth via their own route definitions.
app.include_router(router, prefix="/api/v1", dependencies=[Depends(require_api_key)])


@app.on_event("startup")
def startup_event():
    """Minimal startup - log that app is ready for requests.

    NOTE: Gateway workers are not started here to avoid async context issues.
    They can be started separately if needed via a background task scheduler.
    """
    # Create any missing tables (idempotent - only creates what doesn't exist,
    # never alters or drops existing tables). Ensures gateway_users and the
    # other gateway tables exist for GitHub login + agent registration.
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables ensured (create_all)")
    except Exception as e:
        logger.error(f"Failed to create database tables on startup: {e}")

    logger.info("Chekk API startup complete - ready for requests")


@app.get("/")
def root():
    return {"message": "Chekk API is running", "version": "1.0.0"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}

