from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.engine import URL
import re

from app.config import settings

# Clean up DATABASE_URL to remove invalid PostgreSQL parameters
# Railway sometimes sets "timeout" which psycopg2 doesn't support
def _clean_database_url(url_string: str) -> str:
    """Remove invalid PostgreSQL connection parameters."""
    # Remove timeout parameter if present
    url_string = re.sub(r'[?&]timeout=[^&]*', '', url_string)
    # Clean up any double question marks or ampersands
    url_string = url_string.replace('?&', '?')
    return url_string

clean_url = _clean_database_url(settings.DATABASE_URL)

engine = create_engine(
    clean_url,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=False,  # Disabled on startup to avoid blocking; pool_timeout handles failures
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
