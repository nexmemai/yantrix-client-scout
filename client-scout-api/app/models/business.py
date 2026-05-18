"""
models/business.py — ORM model for discovered business leads.
Synced with migrations/001_initial_schema.sql :: businesses table.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    NUMERIC,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    niche: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(50), nullable=False, default="India")
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    website_url: Mapped[str | None] = mapped_column(Text)
    google_maps_url: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[float | None] = mapped_column(NUMERIC(2, 1))
    review_count: Mapped[int | None] = mapped_column(Integer)

    # Best-effort person-level enrichment
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_title: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    contact_linkedin_url: Mapped[str | None] = mapped_column(Text)
    contact_confidence: Mapped[int | None] = mapped_column(Integer)

    # Ability-to-pay / reliability signals
    primary_language: Mapped[str | None] = mapped_column(String(20))
    domain_age_years: Mapped[float | None] = mapped_column(NUMERIC(5, 2))
    has_recent_updates: Mapped[bool | None] = mapped_column(Boolean)
    budget_tier: Mapped[str | None] = mapped_column(String(20))
    reliability: Mapped[str | None] = mapped_column(String(20))

    source: Mapped[str] = mapped_column(String(50), nullable=False, default="google_maps")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    discovery_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("discovery_jobs.id", ondelete="SET NULL"),
    )
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    webhook_url: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(255))

    # Lightweight sales workflow / mini-CRM
    lead_status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contact_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sales_notes: Mapped[str | None] = mapped_column(Text)
    priority_rank: Mapped[int | None] = mapped_column(Integer)
    assigned_to: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("name", "city", "address", name="uq_business_identity"),
        Index("idx_businesses_niche_city", "niche", "city"),
        Index("idx_businesses_created", "created_at"),
        Index("idx_businesses_stage", "stage"),
        Index("idx_businesses_job_id", "discovery_job_id"),
        Index("idx_businesses_lead_status", "lead_status"),
        Index("idx_businesses_follow_up_at", "follow_up_at"),
        Index("idx_businesses_priority_rank", "priority_rank"),
        Index("idx_businesses_budget_reliability", "budget_tier", "reliability"),
        CheckConstraint("rating >= 0 AND rating <= 5", name="chk_business_rating"),
        CheckConstraint("review_count >= 0", name="chk_business_review_count"),
        CheckConstraint(
            "contact_confidence IS NULL OR contact_confidence BETWEEN 0 AND 100",
            name="chk_business_contact_confidence",
        ),
        CheckConstraint("contact_attempts >= 0", name="chk_business_contact_attempts"),
        CheckConstraint(
            "lead_status IN ('new', 'contacted', 'replied', 'meeting_set', "
            "'proposal_sent', 'won', 'lost', 'ignored')",
            name="chk_business_lead_status",
        ),
        CheckConstraint(
            "budget_tier IS NULL OR budget_tier IN ('low', 'medium', 'high')",
            name="chk_business_budget_tier",
        ),
        CheckConstraint(
            "reliability IS NULL OR reliability IN ('low', 'medium', 'high')",
            name="chk_business_reliability",
        ),
    )

    # Relationships
    job = relationship("DiscoveryJob", back_populates="businesses")
    audit = relationship("Audit", back_populates="business", uselist=False)
    score = relationship("Score", back_populates="business", uselist=False)
    pitches = relationship("Pitch", back_populates="business", order_by="Pitch.generated_at.desc()")

    def __repr__(self) -> str:
        return f"<Business id={self.id} name={self.name!r} city={self.city!r}>"
