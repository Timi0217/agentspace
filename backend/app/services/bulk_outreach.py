"""
Bulk Outreach Service

Handles batch generation and scheduled sending of warm-up outreach emails.
Uses ThreadPoolExecutor for parallel DeepSeek generation and a background
loop for scheduled sends.
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Optional, Dict
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.candidate import Candidate, OutreachStatus
from app.services.outreach_generator import generate_outreach_template
from app.services.email_sender import send_outreach_email
from app.services.github_ingestion import token_rotator

logger = get_logger(__name__)


def _build_role_context(db, role_id: str) -> Optional[Dict]:
    """Build role_context dict for outreach generation. Returns None if role not found."""
    from app.models.role import Role
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        return None
    comp_str = ''
    if role.comp_max:
        comp_str = f"up to ${role.comp_max // 1000}K"
    elif role.comp_min:
        comp_str = f"${role.comp_min // 1000}K+"
    equity_str = 'significant equity' if comp_str else ''
    loc_req = role.location_requirement.value if role.location_requirement else ''
    loc_cities = ', '.join(role.location_cities) if role.location_cities else ''
    if loc_req == 'remote':
        location_str = 'Remote'
    elif loc_req == 'onsite' and loc_cities:
        location_str = f"{loc_cities} (onsite)"
    elif loc_req == 'hybrid' and loc_cities:
        location_str = f"{loc_cities} (hybrid)"
    elif loc_cities:
        location_str = loc_cities
    elif loc_req:
        location_str = loc_req.capitalize()
    else:
        location_str = 'Flexible'
    return {
        'company': role.company_name,
        'title': role.title,
        'description': role.jd_text or '',
        'tech_stack': role.tech_stack or [],
        'comp': comp_str,
        'equity': equity_str,
        'location': location_str,
        'stage': role.company_stage.value.replace('_', ' ') if role.company_stage else '',
        'investors': role.notable_investors or [],
    }


def _build_fit_analysis(db, candidate_id: str, role_id: str) -> Optional[Dict]:
    """Build fit_analysis dict for outreach generation."""
    from app.models.fit_analysis import FitAnalysis
    fit = db.query(FitAnalysis).filter(
        FitAnalysis.candidate_id == candidate_id,
        FitAnalysis.role_id == role_id,
    ).order_by(FitAnalysis.created_at.desc()).first()
    if not fit:
        return None
    return {
        'fit_score': fit.fit_score,
        'recommendation': fit.recommendation,
        'strengths': fit.strengths or [],
        'concerns': fit.concerns or [],
        'ai_summary': fit.ai_summary,
    }


def generate_single_outreach(candidate_id: str, db_factory, role_id: Optional[str] = None) -> Dict:
    """
    Generate outreach for a single candidate. Designed to run in a thread.

    Args:
        candidate_id: UUID string of the candidate
        db_factory: Callable that returns a new DB session
        role_id: Optional role UUID string for role-specific outreach

    Returns:
        Dict with candidate_id, success, and error (if any)
    """
    db = db_factory()
    try:
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            return {"candidate_id": candidate_id, "success": False, "error": "Not found"}

        if not candidate.vibe_report:
            # Auto-analyze: run VibeChekk inline before generating outreach
            try:
                from app.services.candidate_analysis import run_candidate_analysis
                run_candidate_analysis(candidate.id, db)
                db.refresh(candidate)
            except Exception as e:
                logger.error("Auto-analyze failed for %s: %s", candidate_id, e)
                return {"candidate_id": candidate_id, "success": False, "error": f"Auto-analyze failed: {str(e)[:100]}"}

        if not candidate.email:
            return {"candidate_id": candidate_id, "success": False, "error": "No email"}

        # Build candidate dict for outreach generator
        candidate_data = {
            "github_username": candidate.github_username,
            "name": candidate.name or candidate.github_username,
            "archetype": candidate.archetype,
            "tier": candidate.tier,
            "vibe_report": candidate.vibe_report or {},
            "github_languages": candidate.github_languages or [],
        }

        # Build role context if role_id provided
        role_context = None
        fit_analysis_data = None
        if role_id:
            role_context = _build_role_context(db, role_id)
            fit_analysis_data = _build_fit_analysis(db, candidate_id, role_id)

        github_token = token_rotator.get_token()

        result = generate_outreach_template(
            api_key=settings.DEEPSEEK_API_KEY,
            candidate=candidate_data,
            github_token=github_token,
            role_context=role_context,
            fit_analysis=fit_analysis_data,
        )

        if result.get("success"):
            candidate.outreach_subject = result["subject"]
            candidate.outreach_body = result["body"]
            candidate.outreach_status = OutreachStatus.drafted
            candidate.outreach_type = "role_specific" if role_id else "generic"
            candidate.outreach_scheduled_for = None

            # Store role label for outreach queue display
            if role_id and role_context:
                title = role_context.get('title', '')
                company = role_context.get('company', '')
                candidate.outreach_role_title = f"{title} @ {company}" if title and company else (title or company or None)

            # Also persist draft on the match record
            if role_id:
                from app.models.match import Match
                match = db.query(Match).filter(
                    Match.candidate_id == candidate_id,
                    Match.role_id == role_id,
                ).first()
                if match:
                    match.draft_subject = result["subject"]
                    match.draft_body = result["body"]

            db.commit()
            return {
                "candidate_id": candidate_id,
                "success": True,
                "subject": result["subject"],
            }
        else:
            return {"candidate_id": candidate_id, "success": False, "error": "Generation failed"}

    except Exception as e:
        db.rollback()
        logger.error("Outreach generation failed for %s: %s", candidate_id, e)
        return {"candidate_id": candidate_id, "success": False, "error": str(e)}
    finally:
        db.close()


def bulk_generate_outreach(
    db: Session,
    candidate_ids: List[str],
    job_id: str,
    db_factory,
    max_workers: int = 40,
    role_id: Optional[str] = None,
):
    """
    Generate outreach emails for multiple candidates in parallel.
    Updates an IngestionJob for progress tracking.

    Args:
        db: DB session for job updates
        candidate_ids: List of candidate UUID strings
        job_id: IngestionJob ID for progress tracking
        db_factory: Callable that returns a new DB session
        max_workers: Number of parallel DeepSeek workers
        role_id: Optional role UUID string for role-specific outreach
    """
    from app.models.ingestion_job import IngestionJob, JobStatus

    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
    if not job:
        logger.error("Job %s not found", job_id)
        return

    total = len(candidate_ids)
    generated = 0
    failed = 0
    recent_logs = []

    def add_log(msg: str):
        recent_logs.append(msg)
        if len(recent_logs) > 50:
            recent_logs.pop(0)

    logger.info("Starting bulk outreach generation: %d candidates, %d workers, role_id=%s", total, max_workers, role_id)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(generate_single_outreach, cid, db_factory, role_id): cid
            for cid in candidate_ids
        }

        for future in as_completed(futures):
            cid = futures[future]
            try:
                result = future.result(timeout=60)
                if result["success"]:
                    generated += 1
                    add_log(f"Generated: {result.get('subject', '?')[:50]}")
                else:
                    failed += 1
                    add_log(f"Failed {cid[:8]}: {result.get('error', 'unknown')}")
            except Exception as e:
                failed += 1
                add_log(f"Error {cid[:8]}: {str(e)[:80]}")

            # Update job progress every 5 candidates
            if (generated + failed) % 5 == 0 or (generated + failed) == total:
                try:
                    db.refresh(job)
                    if job.status == JobStatus.stopped:
                        logger.info("Job %s stopped by user", job_id)
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    job.processed_count = generated + failed
                    job.candidates_saved = generated
                    job.error_count = failed
                    job.recent_logs = list(recent_logs)
                    job.updated_at = datetime.utcnow()
                    db.commit()
                except Exception:
                    db.rollback()

    # Final update
    try:
        db.refresh(job)
        if job.status != JobStatus.stopped:
            job.status = JobStatus.completed
        job.processed_count = generated + failed
        job.candidates_saved = generated
        job.error_count = failed
        job.recent_logs = list(recent_logs)
        job.updated_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()

    logger.info("Bulk outreach complete: %d generated, %d failed out of %d", generated, failed, total)


def send_single_outreach(candidate_id: str, db_factory) -> Dict:
    """
    Send the drafted outreach email for a single candidate.

    Args:
        candidate_id: UUID string
        db_factory: Callable that returns a new DB session

    Returns:
        Dict with success status
    """
    db = db_factory()
    try:
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            return {"candidate_id": candidate_id, "success": False, "error": "Not found"}

        if not candidate.outreach_subject or not candidate.outreach_body:
            return {"candidate_id": candidate_id, "success": False, "error": "No draft"}

        if not candidate.email:
            return {"candidate_id": candidate_id, "success": False, "error": "No email"}

        result = send_outreach_email(
            to_email=candidate.email,
            subject=candidate.outreach_subject,
            body=candidate.outreach_body,
            candidate_name=candidate.name,
        )

        # Snapshot the sent email so regeneration can't overwrite history
        candidate.sent_outreach_subject = candidate.outreach_subject
        candidate.sent_outreach_body = candidate.outreach_body
        candidate.outreach_status = OutreachStatus.sent
        candidate.warmup_email_sent_at = datetime.utcnow()
        candidate.warmup_email_id = result.get("email_id")
        candidate.warmup_message_id = result.get("message_id")
        candidate.warmup_email_opened_at = None  # Reset so timeline reflects THIS warm-up
        candidate.warmup_replied_at = None
        candidate.status = "contacted"
        candidate.last_contact_date = datetime.utcnow().date()
        candidate.last_contact_method = "email"
        db.commit()

        logger.info("Sent outreach to %s (%s)", candidate.name, candidate.email)
        return {"candidate_id": candidate_id, "success": True}

    except Exception as e:
        db.rollback()
        logger.error("Failed to send outreach to %s: %s", candidate_id, e)
        return {"candidate_id": candidate_id, "success": False, "error": str(e)}
    finally:
        db.close()


def bulk_send_outreach(
    candidate_ids: List[str],
    db_factory,
    max_workers: int = 4,
) -> Dict:
    """
    Send outreach emails for multiple candidates.
    Sends sequentially with small delays to avoid spam triggers.

    Returns:
        Dict with sent/failed counts
    """
    import time

    sent = 0
    failed = 0
    errors = []

    for cid in candidate_ids:
        result = send_single_outreach(cid, db_factory)
        if result["success"]:
            sent += 1
        else:
            failed += 1
            errors.append({"candidate_id": cid, "error": result.get("error")})

        # 2-second delay between sends to avoid spam triggers
        if sent + failed < len(candidate_ids):
            time.sleep(2)

    logger.info("Bulk send complete: %d sent, %d failed", sent, failed)
    return {"sent": sent, "failed": failed, "errors": errors[:10]}


# --- Scheduled Send Background Loop ---

_scheduler_running = False


def start_outreach_scheduler(db_factory):
    """
    Start a background thread that checks for scheduled outreach emails
    and sends them when their scheduled_for time has passed.

    Runs every 10 minutes. Safe to call multiple times (idempotent).
    """
    global _scheduler_running
    if _scheduler_running:
        return

    _scheduler_running = True

    def scheduler_loop():
        import time
        global _scheduler_running

        logger.info("Outreach scheduler started")

        while _scheduler_running:
            try:
                db = db_factory()
                try:
                    now = datetime.utcnow()
                    due_candidates = (
                        db.query(Candidate)
                        .filter(
                            Candidate.outreach_status == OutreachStatus.scheduled,
                            Candidate.outreach_scheduled_for <= now,
                            Candidate.outreach_subject.isnot(None),
                            Candidate.email.isnot(None),
                        )
                        .limit(100)
                        .all()
                    )

                    if due_candidates:
                        logger.info("Found %d scheduled outreach emails due for sending", len(due_candidates))
                        ids = [str(c.id) for c in due_candidates]
                        bulk_send_outreach(ids, db_factory, max_workers=1)
                        # More emails may be waiting — short pause then loop again
                        time.sleep(5)
                        continue

                finally:
                    db.close()

            except Exception as e:
                logger.error("Scheduler error: %s", e)

            time.sleep(60)  # Check every minute when queue is empty

    thread = threading.Thread(target=scheduler_loop, daemon=True, name="outreach-scheduler")
    thread.start()


def stop_outreach_scheduler():
    """Stop the background scheduler loop."""
    global _scheduler_running
    _scheduler_running = False
