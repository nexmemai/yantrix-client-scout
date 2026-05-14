"""
schemas/score.py — Pydantic schemas for Score / pitch notes.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    overall_score: int
    website_quality: int | None = None
    online_presence: int | None = None
    conversion_readiness: int | None = None
    urgency: int | None = None
    pitch_notes: str | None = None
    recommended_services: list[str] | None = None
    objection_handlers: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    scored_at: datetime
