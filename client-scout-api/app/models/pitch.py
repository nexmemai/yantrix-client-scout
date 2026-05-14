"""
models/pitch.py — ORM model for AI-generated outreach pitches.
Separated from scores so pitches can be regenerated independently per campaign.
Synced with migrations/001_initial_schema.sql :: pitches table.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Pitch(Base):
    __tablename__ = "pitches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    score_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scores.id", ondelete="SET NULL"),
    )

    # Generated content
    pitch_notes: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_services: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    objection_handlers: Mapped[str | None] = mapped_column(Text)
    subject_line: Mapped[str | None] = mapped_column(String(255))

    # Campaign context
    tone: Mapped[str] = mapped_column(String(50), nullable=False, default="professional")
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    # Provider metadata
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    llm_model: Mapped[str | None] = mapped_column(String(100))
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    prompt_version: Mapped[str | None] = mapped_column(String(20))

    # CRM sync
    exported_to_hubspot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exported_to_zoho: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("tokens_used >= 0", name="chk_pitch_tokens"),
        Index("idx_pitches_business_id", "business_id", "generated_at"),
        Index("idx_pitches_hubspot_export", "exported_to_hubspot", "generated_at"),
        Index("idx_pitches_zoho_export", "exported_to_zoho", "generated_at"),
    )

    # Relationships
    business = relationship("Business", back_populates="pitches")

    def __repr__(self) -> str:
        return f"<Pitch id={self.id} business_id={self.business_id} tone={self.tone!r}>"
