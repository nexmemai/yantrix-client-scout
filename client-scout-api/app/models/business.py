"""
models/business.py — ORM model for discovered business leads.
Synced with migrations/001_initial_schema.sql :: businesses table.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    NUMERIC,
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
        CheckConstraint("rating >= 0 AND rating <= 5", name="chk_business_rating"),
        CheckConstraint("review_count >= 0", name="chk_business_review_count"),
    )

    # Relationships
    job = relationship("DiscoveryJob", back_populates="businesses")
    audit = relationship("Audit", back_populates="business", uselist=False)
    score = relationship("Score", back_populates="business", uselist=False)
    pitches = relationship("Pitch", back_populates="business", order_by="Pitch.generated_at.desc()")

    def __repr__(self) -> str:
        return f"<Business id={self.id} name={self.name!r} city={self.city!r}>"
