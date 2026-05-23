"""
schemas/outreach.py - Pydantic schemas for the autonomous outreach surface.

Two response shapes are exposed here:

* ``OutreachAttemptOut`` mirrors a single row in ``outreach_attempts`` and is
  what the dashboard renders inside the Communication Log timeline.
* ``OutreachTimelineOut`` is the envelope returned by
  ``GET /api/v1/leads/{id}/outreach``: the per-lead summary copied from
  ``businesses.*`` plus the ordered list of attempts.

Keeping the timeline shape envelope-style (summary + attempts) avoids a
second round-trip from the dashboard for the per-lead status header above
the log, and lets the API evolve - e.g. add a "next attempt scheduled at"
field - without breaking older clients.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Mirror app.services.outreach_sender.OutreachStatus / channel CHECK
# constraints so callers (frontend) get exact union types instead of
# free-form strings.
OutreachChannel = Literal["email", "whatsapp", "sms"]
AttemptStatus = Literal["pending", "sent", "failed", "skipped"]
LeadOutreachStatus = Literal[
    "idle",
    "pending",
    "sent",
    "partial",
    "failed",
    "skipped",
]


class OutreachAttemptOut(BaseModel):
    """One row in the timeline."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    pitch_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None

    channel: OutreachChannel
    status: AttemptStatus

    provider: str | None = None
    provider_message_id: str | None = None

    recipient: str | None = None
    payload_subject: str | None = None
    payload_body: str | None = None

    error_message: str | None = None
    is_dry_run: bool = False

    attempted_at: datetime
    completed_at: datetime | None = None


class OutreachLeadSummary(BaseModel):
    """Header strip on the lead detail page - independent of the timeline."""

    business_id: uuid.UUID
    outreach_status: LeadOutreachStatus = "idle"
    email_sent_at: datetime | None = None
    whatsapp_sent_at: datetime | None = None
    last_outreach_at: datetime | None = None
    last_outreach_error: str | None = None
    # Whether the lead row currently has a usable contact channel. The
    # frontend uses this to grey out "Auto-send pending" hints when neither
    # email nor phone is present.
    has_email_channel: bool = False
    has_whatsapp_channel: bool = False


class OutreachTimelineOut(BaseModel):
    """Envelope returned by GET /api/v1/leads/{lead_id}/outreach."""

    summary: OutreachLeadSummary
    attempts: list[OutreachAttemptOut] = Field(default_factory=list)
