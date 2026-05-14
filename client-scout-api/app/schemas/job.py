"""
schemas/job.py — Pydantic schemas for DiscoveryJob.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobCreate(BaseModel):
    query: str
    source: str = "google_maps"  # google_maps | justdial | csv
    niche: str | None = None
    auto_audit: bool = True
    auto_score: bool = True


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query: str
    source: str
    niche: str | None = None
    status: str
    result_count: int
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
