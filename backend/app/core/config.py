from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://localhost/agentspace"  # Default for development
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_TOKEN_2: Optional[str] = None
    GITHUB_TOKEN_3: Optional[str] = None
    GITHUB_TOKEN_4: Optional[str] = None
    GITHUB_TOKEN_5: Optional[str] = None
    GITHUB_TOKEN_6: Optional[str] = None
    PROXYCURL_API_KEY: Optional[str] = None
    APOLLO_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    PDL_API_KEY: Optional[str] = None  # People Data Labs
    EXA_API_KEY: Optional[str] = None  # Exa AI for semantic search fallback
    CAPTAINDATA_API_KEY: Optional[str] = None  # CaptainData for LinkedIn profile enrichment
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: str = "AgentSpace <noreply@agentspace.dev>"
    RESEND_REPLY_TO_EMAIL: Optional[str] = None  # Inbound email address for reply tracking
    DEEPGRAM_API_KEY: Optional[str] = None  # Deepgram for voice answer transcription
    VAPI_API_KEY: Optional[str] = None  # VAPI voice AI for screening calls (private key for webhooks)
    REDIS_URL: str = "redis://localhost:6379"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    API_KEY: Optional[str] = None  # API key for dashboard auth (set to enable protection)
    CORS_ORIGINS: str = "*"  # Comma-separated list of allowed origins (e.g., "http://localhost:5173,https://agentspace.vercel.app")
    FRONTEND_URL: str = "https://agentspace.dev"  # Base URL for the AgentSpace frontend (used in emails, links, etc.)
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    OAUTH_CALLBACK_SECRET: str = "agentspace-oauth-callback-secret"  # OAuth callback secret

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='ignore',
        # This allows .env file to be missing without error
        # Environment variables will still be read
        env_ignore_empty=True,
    )


settings = Settings()
