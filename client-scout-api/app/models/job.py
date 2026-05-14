"""
models/job.py — ORM model for discovery pipeline jobs.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DiscoveryJob(Base):
    __tablename__ = "discovery_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # google_maps | justdial | csv
    niche: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(20), default="queued"
    )  # queued | running | completed | failed
    total_discovered: Mapped[int] = mapped_column(Integer, default=0)
    total_audited: Mapped[int] = mapped_column(Integer, default=0)
    total_scored: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    businesses = relationship("Business", back_populates="job")

    def __repr__(self) -> str:
        return f"<DiscoveryJob id={self.id} query={self.query!r} status={self.status!r}>"
