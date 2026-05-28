"""
Debug endpoint to verify token configuration
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.base import get_db

router = APIRouter()


@router.get("/debug/tokens")
async def check_token_configuration():
    """
    Check how many GitHub tokens are loaded and configured
    """
    from app.services.github_ingestion import token_rotator

    return {
        "tokens_loaded": len(token_rotator.tokens),
        "rate_per_token": token_rotator.rate_per_token,
        "combined_rate": token_rotator.rate_per_token * len(token_rotator.tokens),
        "bucket_capacity": token_rotator.bucket_capacity,
        "expected_performance": {
            "candidates_per_minute": round((token_rotator.rate_per_token * len(token_rotator.tokens) / 8) * 60, 1),
            "estimated_hours_for_20k": round(20167 / ((token_rotator.rate_per_token * len(token_rotator.tokens) / 8) * 60 * 60), 1)
        },
        "status": "ok" if len(token_rotator.tokens) >= 3 else "warning",
        "message": f"✅ {len(token_rotator.tokens)} token(s) configured and ready" if len(token_rotator.tokens) >= 3 else f"⚠️ Only {len(token_rotator.tokens)} token(s) found, expected 3"
    }


@router.post("/debug/test-worker-logging")
async def test_worker_logging(db: Session = Depends(get_db)):
    """
    Test worker-based logging with a small batch of known GitHub users.
    Returns logs to verify worker IDs, EST timestamps, and flag_modified.
    """
    from app.models.ingestion_job import IngestionJob, JobStatus
    from app.services.parallel_processor import process_batch_parallel
    from datetime import datetime
    import uuid

    # Test with 5 well-known GitHub users
    test_usernames = ['torvalds', 'gaearon', 'tj', 'sindresorhus', 'addyosmani']

    # Create test job
    job = IngestionJob(
        id=str(uuid.uuid4()),
        status=JobStatus.running,
        searches_total=1,
        searches_completed=1,
        total_candidates=len(test_usernames),
        processed_count=0,
        candidates_saved=0,
        candidates_skipped=0,
        current_batch=1,
        recent_logs=[],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(job)
    db.commit()

    stats = {
        'saved': 0,
        'skipped_hard_filter': 0,
        'skipped_low_score': 0,
        'errors': 0,
        'hot': 0,
        'warm': 0,
        'cold': 0
    }

    # Process batch with parallel workers
    try:
        process_batch_parallel(
            db=db,
            job=job,
            batch_usernames=test_usernames,
            batch_start_index=0,
            current_threshold=30,
            stats=stats,
            max_workers=12
        )

        # Refresh to get latest logs
        db.refresh(job)

        logs = job.recent_logs or []
        worker_logs = [log for log in logs if 'Worker' in log.get('message', '')]

        result = {
            "test_status": "success",
            "candidates_tested": len(test_usernames),
            "stats": stats,
            "total_log_entries": len(logs),
            "worker_based_log_entries": len(worker_logs),
            "logs": logs,
            "verification": {
                "has_worker_format": len(worker_logs) > 0,
                "has_est_timezone": any('EST' in log.get('timestamp', '') for log in logs),
                "flag_modified_working": len(logs) > 0
            }
        }

        # Clean up test job
        db.delete(job)
        db.commit()

        return result

    except Exception as e:
        # Clean up on error
        db.delete(job)
        db.commit()
        raise
