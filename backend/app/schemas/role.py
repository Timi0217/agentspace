from pydantic import BaseModel, EmailStr
from typing import Dict, Optional, List
from datetime import datetime, date
from uuid import UUID
from decimal import Decimal
from app.models.role import RoleStatus, CompanyStage, LocationRequirement, Urgency


class RoleBase(BaseModel):
    company_name: str
    company_website: Optional[str] = None
    company_stage: Optional[CompanyStage] = None
    funding_amount: Optional[int] = None
    last_raise_date: Optional[date] = None
    notable_investors: Optional[List[str]] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_linkedin: Optional[str] = None
    title: str
    jd_text: Optional[str] = None
    jd_url: Optional[str] = None
    tech_stack: Optional[List[str]] = None
    required_skills: Optional[List[str]] = None
    required_skills_priority: Optional[Dict[str, str]] = None
    yoe_min: Optional[int] = None
    yoe_max: Optional[int] = None
    location_requirement: Optional[LocationRequirement] = None
    location_cities: Optional[List[str]] = None
    comp_min: Optional[int] = None
    comp_max: Optional[int] = None
    equity_min: Optional[Decimal] = None
    equity_max: Optional[Decimal] = None
    status: Optional[RoleStatus] = RoleStatus.sourced
    source: Optional[str] = None
    fee_percentage: Optional[Decimal] = None
    fee_flat: Optional[int] = None
    placement_fee: Optional[str] = None
    urgency: Optional[Urgency] = None
    seniority_level: Optional[str] = None
    notes: Optional[str] = None
    posted_at: Optional[datetime] = None
    posted_ago_text: Optional[str] = None
    position: Optional[int] = None


class RoleCreate(RoleBase):
    pass


class RoleUpdate(RoleBase):
    company_name: Optional[str] = None
    title: Optional[str] = None


class RoleInDB(RoleBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
