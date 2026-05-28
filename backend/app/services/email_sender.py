"""
Email sending service using Resend API

Handles sending candidate outreach emails with tracking.
"""

import resend
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def send_outreach_email(
    to_email: str,
    subject: str,
    body: str,
    candidate_name: str = None,
) -> dict:
    """
    Send an outreach email via Resend API.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        body: Email body (plain text, will be converted to HTML for tracking)
        candidate_name: Optional candidate name for personalization

    Returns:
        Dict with: email_id, status
    """
    logger.info("Sending outreach to %s", to_email)

    # Set Resend API key
    resend.api_key = settings.RESEND_API_KEY

    try:
        # Append signature to body
        signature_text = "\n\nBest,\nTimi from Chekk.dev"
        body_with_sig = body + signature_text

        # Convert plain text to simple HTML for open tracking
        # (Resend open tracking only works with HTML emails)
        # Body in black, signature in gray
        html_body_content = body.replace('\n', '<br>\n')
        html_signature = '<br>\n<br>\n<span style="color: #999999;">Best,<br>\nTimi from Chekk.dev</span>'
        html_body = html_body_content + html_signature

        # Send email via Resend
        # NOTE: We do NOT set custom Message-ID or In-Reply-To headers.
        # Amazon SES (Resend's backend) overrides Message-ID with its own,
        # so any In-Reply-To referencing our custom ID would point to a
        # non-existent message and BREAK Gmail threading. Instead, we rely
        # on Gmail's subject + participants matching for threading, using
        # "Re: {original_subject}" on follow-up emails.
        email_params = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": html_body,  # Use HTML for open tracking
            "text": body_with_sig,  # Also include plain text version
        }

        # Add reply_to if configured (for automatic reply tracking)
        if settings.RESEND_REPLY_TO_EMAIL:
            email_params["reply_to"] = settings.RESEND_REPLY_TO_EMAIL
            logger.debug("Reply-to set: %s", settings.RESEND_REPLY_TO_EMAIL)

        response = resend.Emails.send(email_params)

        logger.info("Email sent successfully. ID: %s", response.get('id'))

        return {
            "email_id": response.get("id"),
            "status": "sent",
            "to": to_email,
            "subject": subject
        }

    except Exception as e:
        logger.error("Failed to send email: %s", e)
        raise Exception(f"Failed to send email: {str(e)}")
