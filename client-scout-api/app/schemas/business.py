"""
schemas/business.py — Pydantic schemas for Business CRUD operations.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class BusinessBase(BaseModel):
    name: str
    category: str | None = None
    niche: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str = "India"
    phone: str | None = None
    email: str | None = None
    website_url: str | None = None
    google_maps_url: str | None = None
    rating: float | None = None
    review_count: int | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    contact_linkedin_url: str | None = None
    contact_confidence: int | None = None
    primary_language: str | None = None
    domain_age_years: float | None = None
    has_recent_updates: bool | None = None
    budget_tier: str | None = None
    reliability: str | None = None
    source: str
    lead_status: str = "new"
    follow_up_at: datetime | None = None
    last_contacted_at: datetime | None = None
    contact_attempts: int = 0
    sales_notes: str | None = None
    priority_rank: int | None = None
    assigned_to: str | None = None


class BusinessCreate(BusinessBase):
    discovery_job_id: uuid.UUID | None = None
    raw_data: dict[str, Any] | None = None


class BusinessRead(BusinessBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    discovery_job_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    # Nested relations (populated when joined)
    audit: "AuditRead | None" = None
    score: "ScoreRead | None" = None


class BusinessListItem(BaseModel):
    """Lightweight shape for table/list views — no nested relations."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str | None = None
    city: str | None = None
    website_url: str | None = None
    source: str
    overall_score: int | None = None   # joined from scores table
    agency_fit_score: int | None = None
    agency_fit_bucket: str | None = None
    estimated_deal_value: int | None = None
    has_website: bool | None = None    # joined from audits table
    rating: float | None = None
    review_count: int | None = None
    lead_status: str = "new"
    follow_up_at: datetime | None = None
    priority_rank: int | None = None
    created_at: datetime


# Forward refs resolved after AuditRead/ScoreRead are defined in their modules
from app.schemas.audit import AuditRead    # noqa: E402
from app.schemas.score import ScoreRead   # noqa: E402

BusinessRead.model_rebuild()
