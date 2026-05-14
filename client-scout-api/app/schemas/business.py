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
    source: str


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
    has_website: bool | None = None    # joined from audits table
    created_at: datetime


# Forward refs resolved after AuditRead/ScoreRead are defined in their modules
from app.schemas.audit import AuditRead    # noqa: E402
from app.schemas.score import ScoreRead   # noqa: E402

BusinessRead.model_rebuild()
