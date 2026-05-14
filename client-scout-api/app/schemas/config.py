"""
schemas/config.py — Pydantic schemas for ScoringConfig.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Default weights that sum to 100
DEFAULT_WEIGHTS = {
    "has_website": 5,
    "mobile_friendly": 15,
    "has_forms": 15,
    "has_cta": 10,
    "has_whatsapp": 10,
    "has_booking": 15,
    "ssl_valid": 5,
    "page_speed": 10,
    "seo_basics": 10,
    "social_presence": 5,
}


class ScoringWeights(BaseModel):
    has_website: int = Field(5, ge=0, le=100)
    mobile_friendly: int = Field(15, ge=0, le=100)
    has_forms: int = Field(15, ge=0, le=100)
    has_cta: int = Field(10, ge=0, le=100)
    has_whatsapp: int = Field(10, ge=0, le=100)
    has_booking: int = Field(15, ge=0, le=100)
    ssl_valid: int = Field(5, ge=0, le=100)
    page_speed: int = Field(10, ge=0, le=100)
    seo_basics: int = Field(10, ge=0, le=100)
    social_presence: int = Field(5, ge=0, le=100)


class ScoringConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    niche: str
    weights: dict
    prompt_template: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ScoringConfigUpdate(BaseModel):
    """Body for PUT /configs/{niche}."""
    weights: ScoringWeights
    prompt_template: str | None = None
