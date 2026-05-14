"""
schemas/job.py - Pydantic schemas for DiscoveryJob.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobCreate(BaseModel):
    query: str
    source: str = "google_maps"
    niche: str | None = None
    city: str | None = None
    auto_audit: bool = True
    auto_score: bool = True


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query: str
    city: str | None = None
    source: str
    niche: str | None = None
    status: str
    total_discovered: int
    total_audited: int
    total_scored: int
    error_message: str | None = None
    started_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
