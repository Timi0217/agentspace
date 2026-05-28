"""
Parallel candidate processor - processes candidates with 12 workers for maximum speed
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from datetime import datetime
import pytz

from sqlalchemy.orm import Session
from app.models.ingestion_job import IngestionJob, JobStatus
from app.services.github_ingestion import ingest_candidate
from app.api.crud import create_candidate
from app.schemas.candidate import CandidateCreate
from app.core.logging import get_logger

logger = get_logger(__name__)


# Global locks for thread-safe operations
db_write_lock = Lock()
stats_lock = Lock()


def process_single_candidate(username: str, global_index: int):
    """
    Process a single candidate - called in parallel by workers.
    This is the slow part (API calls) that we parallelize.
    """
    try:
        candidate_data = ingest_candidate(username)
        return {
            'username': username,
            'index': global_index,
            'data': candidate_data,
            'success': True
        }
    except Exception as e:
        return {
            'username': username,
            'index': global_index,
            'error': str(e),
            'success': False
        }


def process_batch_parallel(
    db: Session,
    job: IngestionJob,
    batch_usernames: list,
    batch_start_index: int,
    current_threshold: int,
    stats: dict,
    max_workers: int = 12
):
    """
    Process a batch of candidates in parallel.

    API calls happen in parallel (fast), DB writes are sequential (thread-safe).
    """

    def add_log(job_obj, db_session, message):
        """Helper to add log entry"""
        from sqlalchemy.orm.attributes import flag_modified

        if not job_obj.recent_logs:
            job_obj.recent_logs = []
        est = pytz.timezone('US/Eastern')
        timestamp = datetime.now(est).strftime('%d/%m/%y %I:%M %p EST')
        job_obj.recent_logs.append({'timestamp': timestamp, 'message': message})
        # Keep only last 1000 logs
        if len(job_obj.recent_logs) > 1000:
            job_obj.recent_logs = job_obj.recent_logs[-1000:]

        # CRITICAL: Mark JSON field as modified so SQLAlchemy detects the change
        flag_modified(job_obj, 'recent_logs')

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all candidates for parallel processing
        futures = {}
        for i, username in enumerate(batch_usernames):
            global_index = batch_start_index + i
            future = executor.submit(process_single_candidate, username, global_index)
            futures[future] = (username, global_index)

        # Process results as they complete
        for future in as_completed(futures):
            username, global_index = futures[future]

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
                    job.processed_count = global_index + 1
                    job.updated_at = datetime.utcnow()

                    # Handle errors
                    if not result['success']:
                        with stats_lock:
                            stats['errors'] += 1
                        job.error_count += 1
                        job.error_message = result['error']
                        add_log(job, db, f"✗ {username} → Error ({result['error']})")
                        db.commit()
                        continue

                    candidate_data = result['data']

                    # Check if filtered
                    if candidate_data is None or (isinstance(candidate_data, dict) and candidate_data.get('filtered')):
                        with stats_lock:
                            stats['skipped_hard_filter'] += 1
                        job.candidates_skipped += 1

                        # Get filter reason
                        filter_reason = "hard filter"
                        if isinstance(candidate_data, dict) and 'reason' in candidate_data:
                            reason_map = {
                                'no_email': 'no email',
                                'no_contact_method': 'no contact',
                                'no_recent_activity': 'no activity',
                                'only_forked_repos': 'only forks',
                                'account_too_new': 'account too new'
                            }
                            filter_reason = reason_map.get(candidate_data['reason'], candidate_data['reason'])

                        add_log(job, db, f"✗ {username} → Filtered ({filter_reason})")
                        db.commit()
                        continue

                    behavior_score = candidate_data.get('behavior_score', 0)
                    behavior_tier = candidate_data.get('behavior_tier', 'cold')

                    # Check threshold
                    if behavior_score >= current_threshold:
                        candidate = CandidateCreate(**candidate_data)
                        created = create_candidate(db, candidate)

                        with stats_lock:
                            stats['saved'] += 1
                            if behavior_tier == 'hot':
                                stats['hot'] += 1
                            elif behavior_tier == 'warm':
                                stats['warm'] += 1

                        job.candidates_saved += 1
                        add_log(job, db, f"✓ {username} → Saved (score: {behavior_score}, tier: {behavior_tier})")
                    else:
                        with stats_lock:
                            stats['skipped_low_score'] += 1
                            stats['cold'] += 1
                        job.candidates_skipped += 1
                        add_log(job, db, f"✗ {username} → Filtered (score: {behavior_score} < {current_threshold})")

                    db.commit()

                except Exception as e:
                    logger.error("Error saving %s: %s", username, e)
                    with stats_lock:
                        stats['errors'] += 1
                    job.error_count += 1
                    add_log(job, db, f"✗ {username} → Error saving ({str(e)})")
                    db.commit()
