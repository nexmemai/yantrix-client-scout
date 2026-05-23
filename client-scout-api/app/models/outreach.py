"""
models/outreach.py - ORM model for autonomous outreach attempts.

One row per channel per send attempt, append-only. Powers the Communication
Log timeline rendered on /leads/{id}/outreach and the per-lead summary
columns on `businesses` (email_sent_at, whatsapp_sent_at, outreach_status).

Synced with migrations/008_phase4_autonomous_outreach.sql.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OutreachAttempt(Base):
    __tablename__ = "outreach_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    pitch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pitches.id", ondelete="SET NULL"),
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("discovery_jobs.id", ondelete="SET NULL"),
    )

    # 'email' | 'whatsapp' | 'sms' (CHECK enforced)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'pending' | 'sent' | 'failed' | 'skipped'
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Backend that handled the send (e.g. 'smtp', 'ses', 'whatsapp_cloud',
    # 'dry_run'). Helps debug behaviour after provider switches.
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_message_id: Mapped[str | None] = mapped_column(Text)

    # Address actually contacted (email or normalised phone). Stored
    # separately from businesses.* so the historical record survives
    # later edits to the lead row.
    recipient: Mapped[str | None] = mapped_column(Text)

    payload_subject: Mapped[str | None] = mapped_column(Text)
    payload_body: Mapped[str | None] = mapped_column(Text)

    error_message: Mapped[str | None] = mapped_column(Text)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "channel IN ('email', 'whatsapp', 'sms')",
            name="chk_outreach_attempt_channel",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name="chk_outreach_attempt_status",
        ),
        Index(
            "idx_outreach_attempts_business_attempted",
            "business_id",
            "attempted_at",
        ),
        Index("idx_outreach_attempts_job_id", "job_id"),
        Index("idx_outreach_attempts_status", "status"),
    )

    business = relationship("Business", back_populates="outreach_attempts")

    def __repr__(self) -> str:
        return (
            f"<OutreachAttempt id={self.id} business_id={self.business_id} "
            f"channel={self.channel!r} status={self.status!r}>"
        )
