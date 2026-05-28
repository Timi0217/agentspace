from sqlalchemy import Column, String, Integer, Boolean, Text, Date, DateTime, Enum, JSON, LargeBinary
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.db.base import Base


class LocationFit(str, enum.Enum):
    strong = "strong"
    medium = "medium"
    weak = "weak"


class Timeline(str, enum.Enum):
    now = "now"
    one_month = "1_month"
    three_months = "3_months"
    passive = "passive"


class OutreachStatus(str, enum.Enum):
    drafted = "drafted"
    scheduled = "scheduled"
    sent = "sent"


class CandidateStatus(str, enum.Enum):
    new = "new"
    reviewed = "reviewed"
    contacted = "contacted"
    warm = "warm"
    ready = "ready"
    placed = "placed"
    rejected = "rejected"


class Candidate(Base):
    __tablename__ = "candidates"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Identity
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    github_url = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    twitter_url = Column(String, nullable=True)
    website_url = Column(String, nullable=True)
    other_urls = Column(JSON, nullable=True)

    # Location
    location_raw = Column(String, nullable=True)
    location_country = Column(String, nullable=True)
    location_fit = Column(Enum(LocationFit), nullable=True)
    timezone = Column(String, nullable=True)

    # Experience
    yoe = Column(Integer, nullable=True)
    current_role = Column(String, nullable=True)
    current_company = Column(String, nullable=True)
    tech_stack = Column(JSON, nullable=True)

    # GitHub Signals
    github_username = Column(String, nullable=True, unique=True)
    github_hireable = Column(Boolean, nullable=True)
    github_bio = Column(Text, nullable=True)
    github_followers = Column(Integer, nullable=True)
    github_public_repos = Column(Integer, nullable=True)
    github_commits_30d = Column(Integer, nullable=True)
    github_commits_90d = Column(Integer, nullable=True)
    github_total_commits = Column(Integer, nullable=True)  # Total lifetime commits
    github_current_year_commits = Column(Integer, nullable=True)  # Commits in current year
    github_previous_year_commits = Column(Integer, nullable=True)  # Commits in previous year
    github_total_stars = Column(Integer, nullable=True)  # Total stars across all repos
    github_original_repos = Column(Integer, nullable=True)
    github_languages = Column(JSON, nullable=True)
    github_has_readme = Column(Boolean, nullable=True)
    github_last_active = Column(Date, nullable=True)

    # Scoring
    fit_score = Column(Integer, nullable=True)
    score_breakdown = Column(JSON, nullable=True)
    behavior_score = Column(Integer, nullable=True)  # GitHub behavior score (0-100)
    behavior_tier = Column(String, nullable=True)  # hot/warm/cold based on activity signals

    # VibeChekk Analysis (DeepSeek)
    archetype = Column(String, nullable=True)  # e.g., "THE BUILDER", "THE ARCHITECT"
    tier = Column(String, nullable=True)  # e.g., "LEGENDARY", "ULTRA RARE", "RARE", "UNCOMMON", "COMMON"
    tier_badge = Column(String, nullable=True)  # e.g., "🌟🌟🌟", "🌟🌟", "⭐", "◆", "●"
    tier_percentile = Column(String, nullable=True)  # e.g., "Top 1%", "Top 5%"
    vibe_report = Column(JSON, nullable=True)  # Full DeepSeek analysis output

    # Pipeline
    status = Column(Enum(CandidateStatus), default=CandidateStatus.new)
    dormant = Column(Boolean, default=False, nullable=False, server_default='false')
    dormant_reason = Column(String, nullable=True)  # "manual" | "auto_no_reply" — distinguishes how candidate became dormant
    star_count = Column(Integer, default=0, nullable=False, server_default='0')
    source = Column(String, nullable=True)
    desired_comp_min = Column(Integer, nullable=True)
    desired_comp_max = Column(Integer, nullable=True)
    timeline = Column(Enum(Timeline), nullable=True)
    notes = Column(Text, nullable=True)
    resume_text = Column(Text, nullable=True)  # Resume text for enriched analysis
    resume_pdf = Column(LargeBinary, nullable=True)  # Raw PDF file bytes
    linkedin_text = Column(Text, nullable=True)  # Pasted LinkedIn profile text
    linkedin_data = Column(Text, nullable=True)  # Pulled LinkedIn profile data (from CaptainData)
    last_contact_date = Column(Date, nullable=True)
    last_contact_method = Column(String, nullable=True)

    # AI Screening (VAPI)
    screening_status = Column(String, nullable=True)  # pending/completed/failed
    screening_call_id = Column(String, nullable=True)  # VAPI call ID
    screening_transcript = Column(Text, nullable=True)  # Full conversation
    screening_summary = Column(Text, nullable=True)  # AI-generated highlights
    screening_data = Column(JSON, nullable=True)  # Structured extraction
    screening_completed_at = Column(DateTime, nullable=True)
    screening_audio_url = Column(String, nullable=True)  # Recording URL
    screening_scheduled_at = Column(DateTime, nullable=True)
    warmup_replied_at = Column(DateTime, nullable=True)  # When candidate replied to warmup
    warmup_reply_text = Column(Text, nullable=True)  # Content of candidate's reply
    screening_link_sent_at = Column(DateTime, nullable=True)  # When we sent screening link

    # Screening Email Tracking
    screening_email_id = Column(String, nullable=True)  # Resend email ID for screening email
    screening_email_opened_at = Column(DateTime, nullable=True)  # When candidate opened screening email
    screening_link_clicked_at = Column(DateTime, nullable=True)  # When candidate clicked screening link

    # Warmup Email Tracking
    warmup_email_sent_at = Column(DateTime, nullable=True)  # When warm-up email was sent
    warmup_email_opened_at = Column(DateTime, nullable=True)  # When candidate opened warm-up email
    warmup_email_id = Column(String, nullable=True)  # Resend email ID for tracking
    warmup_message_id = Column(String, nullable=True)  # SMTP Message-ID for email threading

    # Follow-up Tracking (separate from initial warm-up)
    followup_sent_at = Column(DateTime, nullable=True)  # When follow-up nudge was sent
    followup_email_id = Column(String, nullable=True)  # Resend email ID for follow-up
    followup_body = Column(Text, nullable=True)  # Body of manual follow-up sent via Write Follow-up

    # Screening Questions Body (auto-sent after candidate replies)
    screening_body = Column(Text, nullable=True)  # Body of auto-generated screening questions email

    # Bulk Outreach
    outreach_status = Column(Enum(OutreachStatus), nullable=True)  # drafted / scheduled / sent
    outreach_type = Column(String, nullable=True)  # "generic" or "role_specific" — set at generation time
    outreach_subject = Column(String, nullable=True)  # Current draft email subject (may be overwritten by regeneration)
    outreach_body = Column(Text, nullable=True)  # Current draft email body (may be overwritten by regeneration)
    sent_outreach_subject = Column(String, nullable=True)  # Snapshot of subject at send time (never overwritten)
    sent_outreach_body = Column(Text, nullable=True)  # Snapshot of body at send time (never overwritten)
    outreach_scheduled_for = Column(DateTime, nullable=True)  # When to send (null = manual)
    outreach_cohort = Column(String, nullable=True)  # Cohort batch label e.g. "Feb 12 #1"
    outreach_role_title = Column(String, nullable=True)  # Denormalized "Role @ Company" for display in outreach queue

    # Unread reply flag — set True on any inbound reply, cleared on approve/dismiss
    has_unread_reply = Column(Boolean, default=False, server_default="false")

    # Manually warmed — set by admin via warm toggle (distinct from ingestion-scored behavior_tier)
    manually_warmed = Column(Boolean, default=False, server_default="false")

    # Bookmark flag — manually set by recruiter to flag high-intent outreach replies
    bookmarked = Column(Boolean, default=False, server_default="false")

    # Disable public /r/company/candidate pages for this candidate
    role_pages_disabled = Column(Boolean, default=False, server_default="false")

    # Voice Form Screening (per-question recorded answers)
    voice_answers = Column(JSON, nullable=True)  # [{question, audio_url, transcript, duration_sec}, ...]

    # ETags for Conditional Requests (Rate Limit Optimization)
    user_etag = Column(String, nullable=True)  # ETag for GitHub user info endpoint
    repos_etag = Column(String, nullable=True)  # ETag for GitHub repos endpoint
