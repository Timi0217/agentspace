from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class DeployRequest(BaseModel):
    github_url: str
    title: Optional[str] = None
    description: Optional[str] = None
    env_vars: Optional[dict[str, str]] = None
    root_directory: Optional[str] = None  # subdirectory to deploy from (monorepo support)


class EnvVarSubmission(BaseModel):
    env_vars: dict[str, str]


class RedeployRequest(BaseModel):
    env_vars: Optional[dict[str, str]] = None


class DeploymentResponse(BaseModel):
    id: UUID
    github_owner: str
    github_repo: str
    github_url: str
    status: str
    framework: Optional[str] = None
    deploy_target: Optional[str] = None
    deployed_url: Optional[str] = None
    error_message: Optional[str] = None
    missing_env_vars: list[str] = []
    detected_env_keys: list = []  # list of str or {key, hint, required, optional} dicts
    root_directory: Optional[str] = None
    is_fullstack: bool = False
    backend_url: Optional[str] = None
    backend_framework: Optional[str] = None
    build_log: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    builder_github_username: Optional[str] = None
    builder_display_name: Optional[str] = None
    is_claimed: bool = False
    claimed_at: Optional[datetime] = None
    comment_count: int = 0
    view_count: int = 0
    like_count: int = 0
    dislike_count: int = 0
    star_count: int = 0
    remix_count: int = 0
    agent_call_count: int = 0
    is_featured: Optional[str] = None
    llms_txt: Optional[str] = None
    detected_routes: Optional[list] = None
    llms_txt_generated_at: Optional[datetime] = None
    is_healthy: bool = True
    last_health_check: Optional[datetime] = None
    health_check_count: int = 0
    health_check_successes: int = 0
    last_response_time_ms: Optional[int] = None
    avg_response_time_ms: Optional[int] = None
    stripe_payments_enabled: bool = False
    has_dockerfile: bool = False
    agent_manifest: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeployUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


ALLOWED_TAGS = {"bug_report", "feature_request", "praise", "question"}

class CommentCreate(BaseModel):
    body: str
    page_url: Optional[str] = None
    tag: Optional[str] = None  # bug_report, feature_request, praise, question
    screenshot_url: Optional[str] = None
    pin_x: Optional[int] = None
    pin_y: Optional[int] = None
    agent_message_id: Optional[str] = None

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Comment body cannot be empty")
        if len(v) > 5000:
            raise ValueError("Comment body cannot exceed 5000 characters")
        return v

    @field_validator("tag")
    @classmethod
    def tag_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALLOWED_TAGS:
            raise ValueError(f"Invalid tag. Must be one of: {', '.join(ALLOWED_TAGS)}")
        return v

    @field_validator("screenshot_url")
    @classmethod
    def screenshot_url_must_be_safe(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("https://api.microlink.io/"):
            raise ValueError("Invalid screenshot URL")
        return v

    @field_validator("pin_x", "pin_y")
    @classmethod
    def pin_coords_in_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > 100):
            raise ValueError("Pin coordinates must be between 0 and 100")
        return v


class CommentResponse(BaseModel):
    id: UUID
    deployment_id: UUID
    author_name: str
    body: str
    page_url: Optional[str] = None
    github_username: Optional[str] = None
    github_avatar_url: Optional[str] = None
    github_display_name: Optional[str] = None
    tag: Optional[str] = None
    screenshot_url: Optional[str] = None
    pin_x: Optional[int] = None
    pin_y: Optional[int] = None
    agent_message_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class GitHubUser(BaseModel):
    login: str
    name: Optional[str] = None
    avatar_url: str
    access_token: str


# ── Profile Schemas ──────────────────────────────────────────


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    website_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    pinned_project_ids: Optional[list[str]] = None  # up to 6 deployment IDs
    currently_building: Optional[str] = None
    # Agent Highway: Base wallet for receiving USDC payouts. Empty string clears it.
    base_payout_address: Optional[str] = None


class ProfileResponse(BaseModel):
    id: UUID
    github_username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    website_url: Optional[str] = None
    github_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    follower_count: int = 0
    following_count: int = 0
    total_stars: int = 0
    total_views: int = 0
    featured: Optional[str] = None
    pinned_project_ids: list[str] = []
    currently_building: Optional[str] = None
    base_payout_address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProfileWithProjects(ProfileResponse):
    """Profile response enriched with the user's deployments."""
    projects: list[DeploymentResponse] = []  # all projects by this builder
    built_projects: list[DeploymentResponse] = []  # repos this user owns (builder)
    pinned_projects: list[DeploymentResponse] = []  # separate list for pinned, in order
    is_following: bool = False  # whether the requesting user follows this profile
    shipping_streak: int = 0  # current consecutive days shipping


# ── Follow Schemas ───────────────────────────────────────────


class FollowResponse(BaseModel):
    follower_username: str
    following_username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class FollowersResponse(BaseModel):
    followers: list[str]
    total: int


class FollowingResponse(BaseModel):
    following: list[str]
    total: int


# ── Star Schemas ─────────────────────────────────────────────


class StarResponse(BaseModel):
    deployment_id: UUID
    github_username: str
    star_count: int
    starred: bool


# ── Remix Schemas ────────────────────────────────────────────


class RemixResponse(BaseModel):
    id: UUID
    original_deployment_id: Optional[UUID] = None
    remix_deployment_id: UUID
    remixer_username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RemixRequest(BaseModel):
    deployment_id: UUID  # the original project to remix


# ── Shipping Calendar / Streak Schemas ──────────────────────


class ShippingDay(BaseModel):
    date: str  # YYYY-MM-DD
    count: int
    projects: list[str] = []  # repo names deployed that day


class ShippingCalendarResponse(BaseModel):
    username: str
    days: list[ShippingDay]
    current_streak: int  # consecutive days with at least one deploy
    longest_streak: int
    total_deploys: int
    active_days: int  # days with at least one deploy


# ── Remix Tree Schemas ──────────────────────────────────────


class RemixTreeNode(BaseModel):
    id: str
    github_owner: str
    github_repo: str
    title: Optional[str] = None
    builder_github_username: Optional[str] = None
    star_count: int = 0
    children: list["RemixTreeNode"] = []


class RemixTreeResponse(BaseModel):
    root: RemixTreeNode
    total_remixes: int


# ── Live Feed Schemas ───────────────────────────────────────


class LiveDeployEvent(BaseModel):
    id: str
    github_owner: str
    github_repo: str
    framework: Optional[str] = None
    builder_github_username: Optional[str] = None
    builder_display_name: Optional[str] = None
    is_claimed: bool = False
    status: str
    title: Optional[str] = None
    created_at: datetime
    deploy_time_seconds: Optional[int] = None  # how long the deploy took


# ── Sidebar Data Schemas ─────────────────────────────────


class BuilderCardResponse(BaseModel):
    github_username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    follower_count: int = 0
    project_count: int = 0
    total_stars: int = 0
    is_following: bool = False


# ── Bookmark Schemas ────────────────────────────────────────


class BookmarkResponse(BaseModel):
    deployment_id: UUID
    github_username: str
    bookmarked: bool


class SidebarResponse(BaseModel):
    builder: BuilderCardResponse  # repo owner (who built the code)
    is_claimed: bool = False
    more_from_builder: list[DeploymentResponse] = []
    related_projects: list[DeploymentResponse] = []
    views_today: int = 0
    views_this_week: int = 0
    trending_in: Optional[str] = None  # e.g. "React", "FastAPI"


# ── Notification Schemas ─────────────────────────────────────


class NotificationResponse(BaseModel):
    id: UUID
    recipient_username: str
    actor_username: str
    type: str  # "star", "comment", "remix", "follow"
    deployment_id: Optional[UUID] = None
    message: Optional[str] = None
    is_read: bool = False
    created_at: datetime
    # Enriched fields (populated by the endpoint)
    actor_avatar_url: Optional[str] = None
    project_title: Optional[str] = None
    project_owner: Optional[str] = None
    project_repo: Optional[str] = None

    model_config = {"from_attributes": True}


class NotificationCountResponse(BaseModel):
    unread_count: int


# ── Root Directory Scan Schemas ────────────────────────────────


class RootCandidate(BaseModel):
    path: str  # "/" for root, or subdirectory name like "frontend"
    framework: Optional[str] = None
    recommended: bool = False
    markers: list[str] = []
    monorepo: Optional[bool] = None


class ScanRootResponse(BaseModel):
    candidates: list[RootCandidate]
    detected_env_keys: list = []  # env var keys detected in the repo (with hints)
