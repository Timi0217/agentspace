"""
Job processor for long-running ingestion jobs with checkpointing and batch processing.

This module handles processing IngestionJob records in batches, with:
- Batch processing (2000 candidates per batch)
- Checkpointing after each batch (survives crashes)
- Memory cleanup between batches (garbage collection, session recreation)
- Resume capability (picks up from last completed batch)
"""

import gc
import time
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Semaphore

from sqlalchemy.orm import Session
from app.models.ingestion_job import IngestionJob, JobStatus
from app.services.github_ingestion import (
    search_github_users,
    ingest_candidate,
)
from app.services.parallel_processor import process_batch_parallel
from app.api.crud import get_candidate_by_github_username, create_candidate
from app.schemas.candidate import CandidateCreate
from app.core.logging import get_logger

logger = get_logger(__name__)


# Batch configuration
BATCH_SIZE = 2000  # Process 2000 candidates per batch
CHECKPOINT_FREQUENCY = 100  # Save checkpoint every 100 candidates within batch
MAX_WORKERS = 12  # Parallel workers for candidate processing (supports 2-6 GitHub tokens)

# Global locks for thread-safe operations
db_write_lock = Lock()
stats_lock = Lock()


def process_job(db: Session, job_id: UUID) -> Dict:
    """
    Process a single ingestion job in batches with checkpointing.

    Args:
        db: Database session
        job_id: UUID of the IngestionJob to process

    Returns:
        Dict with final stats
    """
    # Get job
    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
    if not job:
        raise ValueError(f"Job {job_id} not found")

    # Mark as running
    job.status = JobStatus.running
    job.started_at = datetime.utcnow()
    db.commit()

    try:
        # Check if resuming from checkpoint
        if job.checkpoint_data and job.checkpoint_data.get('all_usernames'):
            add_log(job, db, "📥 Resuming from checkpoint...")
            result = resume_from_checkpoint(db, job)
        else:
            add_log(job, db, "🚀 Starting new job...")
            result = run_full_job(db, job)

        # Refresh to get latest status (might have been stopped during processing)
        db.refresh(job)

        # Only mark as completed if not already stopped/paused
        if job.status not in [JobStatus.stopped, JobStatus.paused]:
            job.status = JobStatus.completed
            add_log(job, db, f"✅ Job completed! Saved {result['saved']} candidates")

        job.completed_at = datetime.utcnow()
        job.stats = result
        db.commit()

        return result

    except Exception as e:
        # Mark as failed
        job.status = JobStatus.failed
        job.completed_at = datetime.utcnow()
        job.error_message = str(e)
        db.commit()

        add_log(job, db, f"❌ Job failed: {str(e)}")

        raise


def run_full_job(db: Session, job: IngestionJob) -> Dict:
    """
    Run a full job from scratch (search + batch processing).

    Args:
        db: Database session
        job: IngestionJob record

    Returns:
        Dict with final stats
    """
    # Phase 1: Search GitHub
    add_log(job, db, "🔍 Phase 1: Searching GitHub...")

    all_usernames = run_github_search(db, job)

    add_log(job, db, f"✓ Found {len(all_usernames)} unique candidates")

    # Phase 2: Filter existing
    add_log(job, db, "🔎 Phase 2: Filtering existing candidates...")

    existing_usernames = set()
    for username in all_usernames:
        existing = get_candidate_by_github_username(db, username)
        if existing:
            existing_usernames.add(username)

    new_usernames = list(all_usernames - existing_usernames)

    add_log(job, db, f"    {len(existing_usernames)} already in database")
    add_log(job, db, f"    {len(new_usernames)} new candidates to evaluate")

    # Phase 3: Process in batches
    add_log(job, db, "⚙️  Phase 3: Processing candidates in batches...")

    # Initialize stats
    stats = {
        'searched': len(all_usernames),
        'existing': len(existing_usernames),
        'new': len(new_usernames),
        'saved': 0,
        'skipped_hard_filter': 0,
        'skipped_low_score': 0,
        'hot': 0,
        'warm': 0,
        'cold': 0,
        'errors': 0,
    }

    # Save initial checkpoint
    job.checkpoint_data = {
        'all_usernames': list(all_usernames),
        'existing_usernames': list(existing_usernames),
        'new_usernames': new_usernames,
        'last_processed_index': 0,
        'current_batch': 0,
        'stats': stats,
    }
    job.total_candidates = len(new_usernames)
    job.total_batches = (len(new_usernames) + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division
    db.commit()

    # Process in batches
    result = process_batches(db, job, new_usernames, stats)

    return result


def resume_from_checkpoint(db: Session, job: IngestionJob) -> Dict:
    """
    Resume a job from its last checkpoint.

    Args:
        db: Database session
        job: IngestionJob record with checkpoint_data

    Returns:
        Dict with final stats
    """
    checkpoint = job.checkpoint_data

    new_usernames = checkpoint['new_usernames']
    stats = checkpoint['stats']
    last_index = checkpoint['last_processed_index']

    add_log(job, db, f"    Resuming from candidate {last_index + 1}/{len(new_usernames)}")
    add_log(job, db, f"    Already processed: {stats['saved']} saved, {stats['skipped_hard_filter'] + stats['skipped_low_score']} skipped")

    # Continue processing from checkpoint
    result = process_batches(db, job, new_usernames, stats, start_index=last_index)

    return result


def process_batches(
    db: Session,
    job: IngestionJob,
    new_usernames: List[str],
    stats: Dict,
    start_index: int = 0
) -> Dict:
    """
    Process candidates in batches with checkpointing and memory cleanup.

    Args:
        db: Database session
        job: IngestionJob record
        new_usernames: List of usernames to process
        stats: Stats dictionary (mutable, updated in place)
        start_index: Index to start from (for resume)

    Returns:
        Dict with final stats
    """
    total_count = len(new_usernames)
    min_behavior_score = job.min_behavior_score

    # Calculate batch range
    start_batch = start_index // BATCH_SIZE
    total_batches = (total_count + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num in range(start_batch, total_batches):
        # Check if job was stopped/paused
        db.refresh(job)
        if job.status == JobStatus.stopped:
            add_log(job, db, "⚠️  Job stopped by user")
            return stats
        if job.status == JobStatus.paused:
            add_log(job, db, "⏸️  Job paused by user")
            return stats

        # Calculate batch range
        batch_start = batch_num * BATCH_SIZE
        batch_end = min((batch_num + 1) * BATCH_SIZE, total_count)

        # Skip if we're resuming and this batch is already done
        if batch_start < start_index:
            batch_start = start_index

        batch_usernames = new_usernames[batch_start:batch_end]

        add_log(job, db, f"📦 Batch {batch_num + 1}/{total_batches}: Processing candidates {batch_start + 1}-{batch_end}/{total_count}")

        # Update job progress
        job.current_batch = batch_num + 1
        db.commit()

        # Process batch in parallel (12 workers)
        process_batch_parallel(
            db=db,
            job=job,
            batch_usernames=batch_usernames,
            batch_start_index=batch_start,
            current_threshold=min_behavior_score,
            stats=stats,
            max_workers=MAX_WORKERS
        )

        # Save checkpoint after batch
        save_checkpoint(db, job, new_usernames, batch_end, batch_num + 1, stats)

        # Memory cleanup between batches
        add_log(job, db, f"🧹 Cleaning up memory after batch {batch_num + 1}...")
        cleanup_memory(db)

        add_log(job, db, f"✓ Batch {batch_num + 1}/{total_batches} complete (saved: {stats['saved']}, skipped: {stats['skipped_hard_filter'] + stats['skipped_low_score']})")

    return stats


def process_batch(
    db: Session,
    job: IngestionJob,
    batch_usernames: List[str],
    batch_start_index: int,
    min_behavior_score: int,
    stats: Dict,
):
    """
    Process a single batch of candidates sequentially.

    Args:
        db: Database session
        job: IngestionJob record
        batch_usernames: List of usernames in this batch
        batch_start_index: Global index of first candidate in batch
        min_behavior_score: Minimum score threshold (re-read from DB at checkpoints)
        stats: Stats dictionary (mutable, updated in place)
    """
    # Track current threshold (can be updated during processing)
    current_threshold = min_behavior_score

    for i, username in enumerate(batch_usernames):
        global_index = batch_start_index + i

        # Check if job was stopped
        db.refresh(job)
        if job.status == JobStatus.stopped:
            return

        try:
            # Update progress
            job.processed_count = global_index + 1
            job.updated_at = datetime.utcnow()

            # Save mini-checkpoint every 100 candidates and re-read threshold
            if (i + 1) % CHECKPOINT_FREQUENCY == 0:
                db.commit()
                # Re-read threshold from database (allows live updates)
                db.refresh(job)
                if job.min_behavior_score != current_threshold:
                    old_threshold = current_threshold
                    current_threshold = job.min_behavior_score
                    add_log(job, db, f"🔄 Threshold updated: {old_threshold} → {current_threshold}")

            # Ingest candidate
            candidate_data = ingest_candidate(username)

            # Check if filtered (returns dict with reason) or None (legacy)
            if candidate_data is None or (isinstance(candidate_data, dict) and candidate_data.get('filtered')):
                stats['skipped_hard_filter'] += 1
                job.candidates_skipped += 1

                # Get human-readable filter reason
                filter_reason = "hard filter"
                if isinstance(candidate_data, dict) and 'reason' in candidate_data:
                    reason_map = {
                        'no_email': 'no email',
                        'no_contact_method': 'no contact method',
                        'no_recent_activity': 'no recent activity',
                        'only_forked_repos': 'only forks, no original repos'
                    }
                    filter_reason = reason_map.get(candidate_data['reason'], candidate_data['reason'])

                add_log(job, db, f"    [{global_index + 1}] ⏭️  Skipped {username} ({filter_reason})")
                continue

            behavior_score = candidate_data.get('behavior_score', 0)
            behavior_tier = candidate_data.get('behavior_tier', 'cold')

            if behavior_score >= current_threshold:
                candidate = CandidateCreate(**candidate_data)
                created = create_candidate(db, candidate)
                stats['saved'] += 1
                job.candidates_saved += 1

                if behavior_tier == 'hot':
                    stats['hot'] += 1
                elif behavior_tier == 'warm':
                    stats['warm'] += 1

                add_log(job, db, f"    [{global_index + 1}] ✓ Saved {username} ({behavior_tier}, score: {behavior_score})")
            else:
                stats['skipped_low_score'] += 1
                stats['cold'] += 1
                job.candidates_skipped += 1
                add_log(job, db, f"    [{global_index + 1}] ⏭️  Skipped {username} (score: {behavior_score} < {current_threshold})")

            db.commit()

        except Exception as e:
            logger.error("Failed to ingest %s: %s", username, e)
            stats['errors'] += 1
            job.error_count += 1
            job.error_message = str(e)
            add_log(job, db, f"    [{global_index + 1}] ✗ Error processing {username}: {str(e)}")
            db.commit()


def save_checkpoint(
    db: Session,
    job: IngestionJob,
    new_usernames: List[str],
    last_processed_index: int,
    current_batch: int,
    stats: Dict,
):
    """
    Save checkpoint data to database.

    Args:
        db: Database session
        job: IngestionJob record
        new_usernames: Full list of new usernames
        last_processed_index: Index of last processed candidate
        current_batch: Current batch number
        stats: Current stats
    """
    job.checkpoint_data = {
        'all_usernames': job.checkpoint_data.get('all_usernames', []),
        'existing_usernames': job.checkpoint_data.get('existing_usernames', []),
        'new_usernames': new_usernames,
        'last_processed_index': last_processed_index,
        'current_batch': current_batch,
        'stats': stats,
    }
    job.updated_at = datetime.utcnow()
    db.commit()

    logger.info("Checkpoint saved at candidate %d/%d (batch %d)", last_processed_index, len(new_usernames), current_batch)


def cleanup_memory(db: Session):
    """
    Clean up memory between batches.

    Args:
        db: Database session
    """
    # Commit any pending changes and expire cached objects
    db.commit()
    db.expire_all()

    # Force garbage collection
    gc.collect()

    logger.debug("Memory cleaned up (gc collected, session expired)")


def run_github_search(db: Session, job: IngestionJob) -> set:
    """
    Run GitHub search across all language/location combinations in parallel.

    Args:
        db: Database session
        job: IngestionJob record

    Returns:
        Set of unique GitHub usernames
    """
    # Comprehensive location coverage (35 location groups - US/Canada only)
    location_groups = [
        # US Broad
        'United States OR USA OR US',
        # Major Tech Hubs
        '"San Francisco" OR SF',
        '"New York" OR NYC',
        'Seattle',
        'Austin',
        'Boston',
        '"Bay Area"',
        '"Silicon Valley"',
        '"Palo Alto"',
        'Chicago',
        'Denver',
        'Portland',
        'Atlanta',
        'Miami',
        'Dallas',
        'Houston',
        'Phoenix',
        # US States
        'California',
        'Texas',
        'Washington',
        'Massachusetts',
        'Colorado',
        'Oregon',
        'Georgia',
        'Florida',
        'Illinois',
        'Arizona',
        'Pennsylvania',
        'Virginia',
        'North Carolina',
        # Canada
        'Canada',
        'Toronto',
        'Vancouver',
        'Montreal',
        'Waterloo'
    ]

    # 10 languages
    languages = ['typescript', 'python', 'go', 'rust', 'javascript', 'cpp', 'swift', 'kotlin', 'java', 'ruby']

    # 350 searches total (10 languages × 35 locations)
    searches = [
        {'languages': [lang], 'location': location_group, 'min_repos': 5, 'index': i}
        for i, (lang, location_group) in enumerate(
            ((lang, loc) for lang in languages for loc in location_groups),
            start=1
        )
    ]

    # Update job with total searches
    job.searches_total = len(searches)
    db.commit()

    all_usernames = set()
    completed_count = 0
    db_lock = Lock()  # Thread-safe database access

    add_log(job, db, f"Searching {len(languages)} languages across {len(location_groups)} location groups...")
    add_log(job, db, f"🚀 Running 4 concurrent searches with staggered starts & rate limiting (3-4 min expected)")

    # Rate limiting: Track when we can make next request (shared across threads)
    rate_limiter = {'next_request_time': time.time(), 'lock': Lock()}

    def search_wrapper(search_params):
        """Wrapper to execute a single search and return results"""
        lang = search_params['languages'][0]
        location = search_params['location']
        index = search_params['index']

        try:
            # Rate limiting: Ensure minimum 0.5s between ANY requests across all threads
            with rate_limiter['lock']:
                now = time.time()
                wait_time = max(0, rate_limiter['next_request_time'] - now)
                if wait_time > 0:
                    time.sleep(wait_time)
                # Schedule next request for 0.5s from now
                rate_limiter['next_request_time'] = time.time() + 0.5

            # Execute the search
            usernames = search_github_users(**{k: v for k, v in search_params.items() if k != 'index'})
            return {
                'success': True,
                'usernames': usernames,
                'lang': lang,
                'location': location,
                'index': index
            }
        except Exception as e:
            logger.error("Search error for %s in %s: %s", lang, location, e)
            return {
                'success': False,
                'usernames': set(),
                'lang': lang,
                'location': location,
                'index': index,
                'error': str(e)
            }

    # Use ThreadPoolExecutor with 12 workers (supports 2-6 GitHub tokens)
    # With 3 tokens: 15,000 req/hour capacity (auto-detected from config)
    # 12 workers maximize throughput while token rotator handles rate limits per-token
    with ThreadPoolExecutor(max_workers=12) as executor:
        # Submit all searches
        future_to_search = {executor.submit(search_wrapper, search): search for search in searches}

        # Process results as they complete
        for future in as_completed(future_to_search):
            # Check if job was stopped
            with db_lock:
                db.refresh(job)
                if job.status == JobStatus.stopped:
                    add_log(job, db, "⚠️  Search stopped by user")
                    # Cancel remaining futures
                    for f in future_to_search:
                        f.cancel()
                    return all_usernames

            result = future.result()

            # Update progress with thread-safe database access
            with db_lock:
                completed_count += 1
                all_usernames.update(result['usernames'])

                # Log every single search (granular updates)
                add_log(job, db, f"[{completed_count}/{len(searches)}] Searching {result['lang']} in {result['location'].split(' OR ')[0]}...")
                add_log(job, db, f"    Found {len(result['usernames'])} candidates ({len(all_usernames)} total unique)")

                job.current_search = f"{result['lang']} in {result['location'].split(' OR ')[0]}"
                job.searches_completed = completed_count
                job.updated_at = datetime.utcnow()
                db.commit()

    add_log(job, db, f"✓ All searches complete: {len(all_usernames)} unique candidates")
    return all_usernames


def add_log(job: IngestionJob, db: Session, message: str):
    """
    Add log message to job's recent_logs.

    Args:
        job: IngestionJob record
        db: Database session
        message: Log message
    """
    from sqlalchemy.orm.attributes import flag_modified

    logs = job.recent_logs or []
    est = pytz.timezone('US/Eastern')
    timestamp = datetime.now(est).strftime('%d/%m/%y %I:%M %p EST')
    logs.append({'timestamp': timestamp, 'message': message})

    # Keep last 1000 logs
    logs = logs[-1000:]

    # Reassign to force SQLAlchemy to detect change
    job.recent_logs = logs
    flag_modified(job, 'recent_logs')

    job.updated_at = datetime.utcnow()
    db.commit()

    logger.info("[Job %s] %s", job.id, message)
