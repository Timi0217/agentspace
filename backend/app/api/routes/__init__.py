# Routes package - exports the main router and utilities
# Import from parent directory's routes_main module
from app.api.routes_main import router, run_candidate_analysis

__all__ = ["router", "run_candidate_analysis"]
