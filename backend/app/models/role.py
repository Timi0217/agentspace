from sqlalchemy import Column, String, Integer, Text, Date, DateTime, Enum, JSON, Numeric, Boolean
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.db.base import Base


class CompanyStage(str, enum.Enum):
    pre_seed = "pre_seed"
    seed = "seed"
    series_a = "series_a"
    series_b = "series_b"
    growth = "growth"


class LocationRequirement(str, enum.Enum):
    remote = "remote"
    hybrid = "hybrid"
    onsite = "onsite"


class RoleStatus(str, enum.Enum):
    sourced = "sourced"
    contacted = "contacted"
    intro_call = "intro_call"
    contract_signed = "contract_signed"
    searching = "searching"
    placed = "placed"
    lost = "lost"


class Urgency(str, enum.Enum):
    asap = "asap"
    one_month = "1_month"
    three_months = "3_months"
    flexible = "flexible"


class Role(Base):
    __tablename__ = "roles"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Company
    company_name = Column(String, nullable=False)
    company_website = Column(String, nullable=True)
    company_stage = Column(Enum(CompanyStage), nullable=True)
    funding_amount = Column(Integer, nullable=True)
    last_raise_date = Column(Date, nullable=True)
    notable_investors = Column(JSON, nullable=True)

    # Contact
    contact_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_linkedin = Column(String, nullable=True)

    # Job Details
    title = Column(String, nullable=False)
    jd_text = Column(Text, nullable=True)
    jd_url = Column(String, nullable=True)
    tech_stack = Column(JSON, nullable=True)
    required_skills = Column(JSON, nullable=True)
    required_skills_priority = Column(JSON, nullable=True)  # {"Python": "must_have", "MLOps": "nice_to_have"}
    yoe_min = Column(Integer, nullable=True)
    yoe_max = Column(Integer, nullable=True)
    location_requirement = Column(Enum(LocationRequirement), nullable=True)
    location_cities = Column(JSON, nullable=True)
    posted_at = Column(DateTime, nullable=True)  # When the job was originally posted
    posted_ago_text = Column(String, nullable=True)  # Human-readable like "2 days ago"

    # Compensation
    comp_min = Column(Integer, nullable=True)
    comp_max = Column(Integer, nullable=True)
    equity_min = Column(Numeric(5, 2), nullable=True)
    equity_max = Column(Numeric(5, 2), nullable=True)

    # Ordering
    position = Column(Integer, nullable=True)  # manual sort order (lower = higher in list)

    # Pipeline
    status = Column(Enum(RoleStatus), default=RoleStatus.sourced)
    source = Column(String, nullable=True)
    fee_percentage = Column(Numeric(5, 2), nullable=True)
    fee_flat = Column(Integer, nullable=True)
    placement_fee = Column(Text, nullable=True)  # Raw placement fee string (e.g., "20%", "$25k", "15% first year")
    urgency = Column(Enum(Urgency), nullable=True)
    seniority_level = Column(String, nullable=True)  # e.g., "Junior", "Mid", "Senior", "Principal", "Flexible"
    notes = Column(Text, nullable=True)
    hide_from_company_page = Column(Boolean, default=False, server_default='false')  # Hide from "sourcing in progress" for clients
    company_page_notes = Column(Text, nullable=True)  # Admin notes shown on the public company page
