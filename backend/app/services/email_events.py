"""
Append-only email event log.

Every outbound email, inbound reply, open, click, or screening answer
is recorded as a single row in the email_events table.  Nothing is
ever updated or deleted — new events are appended with an incrementing
sequence number per candidate.
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.email_event import EmailEvent, EmailEventType

logger = logging.getLogger(__name__)


def append_email_event(
    db: Session,
    candidate_id: UUID,
    event_type: EmailEventType,
    *,
    role_id: Optional[UUID] = None,
    occurred_at: Optional[datetime] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    resend_email_id: Optional[str] = None,
    message_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> EmailEvent:
    """Append a new event to a candidate's email chain.

    The sequence number is auto-incremented per candidate so events
    can be ordered deterministically even when timestamps collide.
    """
    # Get next sequence number for this candidate
    max_seq = (
        db.query(func.coalesce(func.max(EmailEvent.sequence), 0))
        .filter(EmailEvent.candidate_id == candidate_id)
        .scalar()
    )

    now = datetime.utcnow()
    event = EmailEvent(
        candidate_id=candidate_id,
        role_id=role_id,
        event_type=event_type,
        occurred_at=occurred_at or now,
        created_at=now,
        subject=subject,
        body=body,
        resend_email_id=resend_email_id,
        message_id=message_id,
        metadata_=metadata,
        sequence=max_seq + 1,
    )
    db.add(event)
    db.flush()  # assign ID immediately so callers can reference it

    logger.info(
        "EmailEvent #%d [%s] for candidate %s",
        event.sequence,
        event_type.value,
        candidate_id,
    )
    return event


def get_email_chain(db: Session, candidate_id: UUID) -> list[dict]:
    """Return the full email chain for a candidate, ordered by sequence."""
    events = (
        db.query(EmailEvent)
        .filter(EmailEvent.candidate_id == candidate_id)
        .order_by(EmailEvent.sequence.asc())
        .all()
    )
    return [
        {
            "id": str(e.id),
            "event_type": e.event_type.value,
            "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            "subject": e.subject,
            "body": e.body,
            "resend_email_id": e.resend_email_id,
            "metadata": e.metadata_,
            "sequence": e.sequence,
        }
        for e in events
    ]
