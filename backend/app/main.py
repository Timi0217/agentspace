import asyncio
import logging
import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool

from app.api.routes import router
from app.api.mcp_routes import router as mcp_router
from app.api.routes.auth import router as auth_router
from app.core.config import settings
from app.core.auth import require_api_key
from app.core.logging import setup_logging, get_logger
from app.database import SessionLocal

# Import models to ensure they're registered with SQLAlchemy
from app.models.ingestion_job import IngestionJob
from app.models.registration_token import RegistrationToken

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
    logger.info("Chekk API startup complete - ready for requests")


@app.get("/")
def root():
    return {"message": "Chekk API is running", "version": "1.0.0"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}

