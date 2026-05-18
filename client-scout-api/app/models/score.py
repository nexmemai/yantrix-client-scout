"""
models/score.py — ORM model for LLM-generated scores.
Synced with migrations/001_initial_schema.sql :: scores table.
Note: score_band is a GENERATED column in Postgres — read-only in ORM.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    audit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audits.id", ondelete="SET NULL"),
    )
    niche_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("niche_configs.id", ondelete="SET NULL"),
    )

    # Composite score (0-100)
    overall_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # Sub-scores
    website_quality: Mapped[int | None] = mapped_column(SmallInteger)
    online_presence: Mapped[int | None] = mapped_column(SmallInteger)
    conversion_readiness: Mapped[int | None] = mapped_column(SmallInteger)
    urgency: Mapped[int | None] = mapped_column(SmallInteger)

    # GENERATED column — Postgres computes this; Python reads it, never writes it
    score_band: Mapped[str | None] = mapped_column(
        String(1),
        Computed(
            "CASE WHEN overall_score >= 75 THEN 'A' "
            "WHEN overall_score >= 50 THEN 'B' "
            "WHEN overall_score >= 25 THEN 'C' "
            "ELSE 'D' END",
            persisted=True,
        ),
    )

    # Provider metadata
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    llm_model: Mapped[str | None] = mapped_column(String(100))
    tokens_used: Mapped[int | None] = mapped_column(Integer)

    # Agency-fit layer for sales prioritisation. This is additive and does not
    # replace the existing overall_score or score_band fields.
    agency_fit_score: Mapped[int | None] = mapped_column(Integer)
    agency_fit_bucket: Mapped[str | None] = mapped_column(String(20))
    opportunity_types: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    estimated_deal_value: Mapped[int | None] = mapped_column(Integer)

    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("overall_score BETWEEN 0 AND 100", name="chk_score_overall"),
        CheckConstraint("website_quality BETWEEN 0 AND 100", name="chk_score_wq"),
        CheckConstraint("online_presence BETWEEN 0 AND 100", name="chk_score_op"),
        CheckConstraint("conversion_readiness BETWEEN 0 AND 100", name="chk_score_cr"),
        CheckConstraint("urgency BETWEEN 0 AND 100", name="chk_score_urgency"),
        CheckConstraint(
            "agency_fit_score IS NULL OR agency_fit_score BETWEEN 0 AND 100",
            name="chk_score_agency_fit_score",
        ),
        CheckConstraint(
            "agency_fit_bucket IS NULL OR agency_fit_bucket IN ('hot', 'warm', 'cold', 'skip')",
            name="chk_score_agency_fit_bucket",
        ),
        CheckConstraint(
            "estimated_deal_value IS NULL OR estimated_deal_value >= 0",
            name="chk_score_estimated_deal_value",
        ),
        Index("idx_scores_band_overall", "score_band", "overall_score"),
        Index("idx_scores_business_id", "business_id"),
        Index("idx_scores_overall", "overall_score"),
        Index("idx_scores_agency_fit_bucket", "agency_fit_bucket"),
        Index("idx_scores_agency_fit_score", "agency_fit_score"),
    )

    # Relationships
    business = relationship("Business", back_populates="score")

    def __repr__(self) -> str:
        return f"<Score id={self.id} overall={self.overall_score} band={self.score_band}>"
