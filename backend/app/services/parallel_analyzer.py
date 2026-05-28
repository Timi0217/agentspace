"""
Parallel bulk analyzer - analyzes candidates with 12 workers for maximum speed
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from datetime import datetime
import pytz

from sqlalchemy.orm import Session
from app.models.ingestion_job import IngestionJob, JobStatus
from app.api.routes import run_candidate_analysis
from app.core.logging import get_logger

logger = get_logger(__name__)


# Global locks for thread-safe operations
db_write_lock = Lock()
stats_lock = Lock()


def analyze_single_candidate(candidate_id: str):
    """
    Analyze a single candidate - called in parallel by workers.
    Each worker creates its own database session for thread safety.
    """
    from app.db.base import SessionLocal

    # Each worker thread needs its own database session (thread-safe)
    worker_db = SessionLocal()
    try:
        result = run_candidate_analysis(candidate_id, worker_db)
        return {
            'candidate_id': candidate_id,
            'success': True,
            'archetype': result.get('archetype'),
            'tier': result.get('tier')
        }
    except Exception as e:
        return {
            'candidate_id': candidate_id,
            'success': False,
            'error': str(e)
        }
    finally:
        worker_db.close()


def analyze_batch_parallel(
    db: Session,
    job: IngestionJob,
    candidate_ids: list,
    stats: dict,
    max_workers: int = 12
):
    """
    Analyze a batch of candidates in parallel.
    
    Analysis happens in parallel (fast), DB writes are sequential (thread-safe).
    """
    
    def add_log(job_obj, message):
        """Helper to add log entry"""
        from sqlalchemy.orm.attributes import flag_modified
        
        if not job_obj.recent_logs:
            job_obj.recent_logs = []
        est = pytz.timezone('US/Eastern')
        timestamp = datetime.now(est).strftime('%d/%m/%y %I:%M %p EST')
        job_obj.recent_logs.append({'timestamp': timestamp, 'message': message})
        # Keep only last 10,000 logs (increased from 1000 to support large bulk jobs)
        if len(job_obj.recent_logs) > 10000:
            job_obj.recent_logs = job_obj.recent_logs[-10000:]

        # CRITICAL: Mark JSON field as modified so SQLAlchemy detects the change
        flag_modified(job_obj, 'recent_logs')
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all candidates for parallel analysis
        futures = {}
        for i, candidate_id in enumerate(candidate_ids):
            future = executor.submit(analyze_single_candidate, candidate_id)
            futures[future] = (candidate_id, i)
        
        # Process results as they complete
        for future in as_completed(futures):
            candidate_id, index = futures[future]

            # Check if job was stopped (thread-safe)
            with db_write_lock:
                db.refresh(job)
                if job.status == JobStatus.stopped:
                    return

            # Get result from worker thread
            result = future.result()

            # All DB operations are thread-safe with lock
            with db_write_lock:
                try:
                    # Update progress
                    job.processed_count = index + 1
                    job.updated_at = datetime.utcnow()

                    # Handle errors
                    if not result['success']:
                        with stats_lock:
                            stats['errors'] += 1
                        job.error_count += 1
                        add_log(job, f"✗ Candidate {candidate_id[:8]}... → Error ({result['error'][:50]})")
                        db.commit()
                        continue

                    # Success
                    with stats_lock:
                        stats['analyzed'] += 1
                        tier = result.get('tier', 'UNKNOWN')
                        if tier == 'RARE':
                            stats['rare'] += 1
                        elif tier == 'EPIC':
                            stats['epic'] += 1
                        elif tier == 'LEGENDARY':
                            stats['legendary'] += 1

                    archetype = result.get('archetype', 'Unknown')
                    tier = result.get('tier', 'Unknown')
                    add_log(job, f"✓ Candidate {candidate_id[:8]}... → Analyzed ({archetype}, {tier})")

                    # Commit after every candidate for real-time progress
                    db.commit()

                except Exception as e:
                    logger.error("Error processing %s: %s", candidate_id, e)
                    with stats_lock:
                        stats['errors'] += 1
                    job.error_count += 1
                    add_log(job, f"✗ Candidate {candidate_id[:8]}... → Error saving ({str(e)[:50]})")
                    db.commit()
