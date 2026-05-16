"""
schemas/export.py - CRM-ready export request/response contracts.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator


ExportDestination = Literal["hubspot", "zoho", "json", "csv"]


class ExportFilters(BaseModel):
    city: str | None = None
    niche: str | None = None
    min_score: int | None = Field(None, ge=0, le=100)
    stage: str | None = None
    unexported_only: bool = False


class ExportRequest(BaseModel):
    destination: ExportDestination | None = None
    format: Literal["csv", "json"] | None = None
    niche: str | None = None
    city: str | None = None
    bucket: str | None = None
    score_min: int | None = Field(None, ge=0, le=100)
    lead_ids: list[uuid.UUID] | None = None
    filters: ExportFilters | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> "ExportRequest":
        if self.destination is None and self.format is None:
            raise ValueError("Provide destination or format.")
        if (
            self.format is None
            and not self.lead_ids
            and self.filters is None
            and not any((self.niche, self.city, self.bucket, self.score_min is not None))
        ):
            raise ValueError("Provide lead_ids or filters.")
        return self

    @computed_field
    @property
    def resolved_destination(self) -> ExportDestination:
        if self.format is not None:
            return self.format
        return self.destination or "json"


class ExportLeadItem(BaseModel):
    business_id: uuid.UUID
    name: str
    city: str | None = None
    niche: str | None = None
    category: str | None = None
    stage: str
    source: str
    phone: str | None = None
    email: str | None = None
    website_url: str | None = None
    google_maps_url: str | None = None
    rating: float | None = None
    review_count: int | None = None
    has_website: bool | None = None
    overall_score: int | None = None
    score_band: str | None = None
    created_at: datetime
    pitch_notes: str | None = None
    recommended_services: list[str] | None = None
    subject_line: str | None = None

    @computed_field
    @property
    def bucket(self) -> str | None:
        if self.overall_score is None:
            return None
        if self.overall_score >= 60:
            return "high-fit"
        if self.overall_score >= 40:
            return "mid-fit"
        return "low-fit"


class ExportResponse(BaseModel):
    destination: ExportDestination
    status: Literal["ready", "dry_run"]
    lead_count: int
    items: list[ExportLeadItem]
