from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict
from datetime import datetime, date
from uuid import UUID
from app.models.candidate import CandidateStatus, LocationFit, Timeline, OutreachStatus


class CandidateBase(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    github_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_url: Optional[str] = None
    website_url: Optional[str] = None
    other_urls: Optional[List[str]] = None
    location_raw: Optional[str] = None
    location_country: Optional[str] = None
    location_fit: Optional[LocationFit] = None
    timezone: Optional[str] = None
    yoe: Optional[int] = None
    current_role: Optional[str] = None
    current_company: Optional[str] = None
    tech_stack: Optional[List[str]] = None
    github_username: Optional[str] = None
    github_hireable: Optional[bool] = None
    github_bio: Optional[str] = None
    github_followers: Optional[int] = None
    github_public_repos: Optional[int] = None
    github_commits_30d: Optional[int] = None
    github_commits_90d: Optional[int] = None
    github_total_commits: Optional[int] = None
    github_original_repos: Optional[int] = None
    github_total_stars: Optional[int] = None
    github_languages: Optional[List[str]] = None
    github_has_readme: Optional[bool] = None
    github_last_active: Optional[date] = None
    fit_score: Optional[int] = None
    score_breakdown: Optional[Dict] = None
    behavior_score: Optional[int] = None
    behavior_tier: Optional[str] = None
    archetype: Optional[str] = None
    tier: Optional[str] = None
    tier_badge: Optional[str] = None
    tier_percentile: Optional[str] = None
    vibe_report: Optional[Dict] = None
    status: Optional[CandidateStatus] = CandidateStatus.new
    dormant: Optional[bool] = False
    dormant_reason: Optional[str] = None
    star_count: Optional[int] = 0
    source: Optional[str] = None
    desired_comp_min: Optional[int] = None
    desired_comp_max: Optional[int] = None
    timeline: Optional[Timeline] = None
    notes: Optional[str] = None
    resume_text: Optional[str] = None
    linkedin_text: Optional[str] = None
    linkedin_data: Optional[str] = None
    last_contact_date: Optional[date] = None
    last_contact_method: Optional[str] = None
    screening_status: Optional[str] = None
    screening_call_id: Optional[str] = None
    screening_transcript: Optional[str] = None
    screening_summary: Optional[str] = None
    screening_data: Optional[Dict] = None
    screening_completed_at: Optional[datetime] = None
    screening_audio_url: Optional[str] = None
    screening_scheduled_at: Optional[datetime] = None
    warmup_replied_at: Optional[datetime] = None
    warmup_reply_text: Optional[str] = None
    screening_link_sent_at: Optional[datetime] = None
    screening_email_id: Optional[str] = None
    screening_email_opened_at: Optional[datetime] = None
    screening_link_clicked_at: Optional[datetime] = None
    warmup_email_sent_at: Optional[datetime] = None
    warmup_email_opened_at: Optional[datetime] = None
    warmup_email_id: Optional[str] = None
    warmup_message_id: Optional[str] = None
    followup_sent_at: Optional[datetime] = None
    followup_email_id: Optional[str] = None
    followup_body: Optional[str] = None
    screening_body: Optional[str] = None
    outreach_status: Optional[OutreachStatus] = None
    outreach_type: Optional[str] = None
    outreach_subject: Optional[str] = None
    outreach_body: Optional[str] = None
    sent_outreach_subject: Optional[str] = None
    sent_outreach_body: Optional[str] = None
    outreach_scheduled_for: Optional[datetime] = None
    outreach_role_title: Optional[str] = None
    has_unread_reply: Optional[bool] = None
    bookmarked: Optional[bool] = None
    role_pages_disabled: Optional[bool] = None
    voice_answers: Optional[List[Dict]] = None


class CandidateCreate(CandidateBase):
    pass


class CandidateUpdate(CandidateBase):
    pass


class CandidateInDB(CandidateBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
