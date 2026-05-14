"""
schemas/audit.py — Pydantic schemas for Audit results.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    url_checked: str | None = None

    # Binary checks
    has_website: bool = False
    ssl_valid: bool = False
    mobile_friendly: bool = False

    # Feature checks
    has_forms: bool = False
    has_cta: bool = False
    has_whatsapp: bool = False
    has_booking: bool = False
    has_chatbot: bool = False

    # Metrics
    load_time_ms: int | None = None
    page_speed_score: int | None = None

    # SEO
    has_title: bool = False
    has_meta_desc: bool = False
    has_h1: bool = False
    has_og_tags: bool = False

    # Social
    has_facebook: bool = False
    has_instagram: bool = False
    has_linkedin: bool = False
    has_twitter: bool = False

    # Tech
    tech_stack: list[str] | None = None
    screenshot_url: str | None = None

    # Meta
    status: str
    error_message: str | None = None
    audited_at: datetime


class AuditRequest(BaseModel):
    """Body for POST /audit-site."""
    url: str
    business_id: uuid.UUID | None = None
