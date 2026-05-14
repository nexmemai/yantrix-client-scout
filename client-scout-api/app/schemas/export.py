"""
schemas/export.py - CRM-ready export request/response contracts.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ExportDestination = Literal["hubspot", "zoho", "json", "csv"]


class ExportFilters(BaseModel):
    city: str | None = None
    niche: str | None = None
    min_score: int | None = Field(None, ge=0, le=100)
    stage: str | None = None
    unexported_only: bool = False


class ExportRequest(BaseModel):
    destination: ExportDestination
    lead_ids: list[uuid.UUID] | None = None
    filters: ExportFilters | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> "ExportRequest":
        if not self.lead_ids and self.filters is None:
            raise ValueError("Provide lead_ids or filters.")
        return self


class ExportLeadItem(BaseModel):
    business_id: uuid.UUID
    name: str
    city: str | None = None
    niche: str | None = None
    stage: str
    phone: str | None = None
    email: str | None = None
    website_url: str | None = None
    google_maps_url: str | None = None
    rating: float | None = None
    review_count: int | None = None
    has_website: bool | None = None
    overall_score: int | None = None
    score_band: str | None = None
    pitch_notes: str | None = None
    recommended_services: list[str] | None = None
    subject_line: str | None = None


class ExportResponse(BaseModel):
    destination: ExportDestination
    status: Literal["ready", "dry_run"]
    lead_count: int
    items: list[ExportLeadItem]
