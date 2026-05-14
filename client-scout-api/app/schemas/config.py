"""
schemas/config.py - Pydantic schemas for niche scoring config.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_WEIGHTS = {
    "weak_website": 20,
    "lead_capture_gap": 25,
    "outdated_contact": 10,
    "high_ticket": 20,
    "trust_gap": 10,
    "automation_gap": 15,
}


class ScoringWeights(BaseModel):
    weak_website: int = Field(20, ge=0, le=100)
    lead_capture_gap: int = Field(25, ge=0, le=100)
    outdated_contact: int = Field(10, ge=0, le=100)
    high_ticket: int = Field(20, ge=0, le=100)
    trust_gap: int = Field(10, ge=0, le=100)
    automation_gap: int = Field(15, ge=0, le=100)


class ScoringConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    niche: str
    weights: dict[str, int]
    prompt_template: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ScoringConfigUpdate(BaseModel):
    """Body for PUT /configs/{niche}."""

    weights: ScoringWeights
    prompt_template: str | None = None
