"""
models/audit.py — ORM model for website audit results.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    url_checked: Mapped[str | None] = mapped_column(Text)

    # Binary presence checks
    has_website: Mapped[bool] = mapped_column(Boolean, default=False)
    ssl_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    mobile_friendly: Mapped[bool] = mapped_column(Boolean, default=False)

    # Feature checks (weighted for scoring)
    has_forms: Mapped[bool] = mapped_column(Boolean, default=False)
    has_cta: Mapped[bool] = mapped_column(Boolean, default=False)
    has_whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    has_booking: Mapped[bool] = mapped_column(Boolean, default=False)
    has_chatbot: Mapped[bool] = mapped_column(Boolean, default=False)

    # Performance metrics
    load_time_ms: Mapped[int | None] = mapped_column(Integer)
    page_speed_score: Mapped[int | None] = mapped_column(Integer)  # 0-100 from PSI

    # SEO basics
    has_title: Mapped[bool] = mapped_column(Boolean, default=False)
    has_meta_desc: Mapped[bool] = mapped_column(Boolean, default=False)
    has_h1: Mapped[bool] = mapped_column(Boolean, default=False)
    has_og_tags: Mapped[bool] = mapped_column(Boolean, default=False)

    # Social presence
    has_facebook: Mapped[bool] = mapped_column(Boolean, default=False)
    has_instagram: Mapped[bool] = mapped_column(Boolean, default=False)
    has_linkedin: Mapped[bool] = mapped_column(Boolean, default=False)
    has_twitter: Mapped[bool] = mapped_column(Boolean, default=False)

    # Tech stack (postgres text array)
    tech_stack: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    cms_detected: Mapped[str | None] = mapped_column(String(100))
    pain_flags: Mapped[dict | None] = mapped_column(JSONB)

    # Raw outputs
    screenshot_url: Mapped[str | None] = mapped_column(Text)
    raw_html_hash: Mapped[str | None] = mapped_column(String(64))

    # Job meta
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | running | completed | failed | skipped
    error_message: Mapped[str | None] = mapped_column(Text)
    audited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship
    business = relationship("Business", back_populates="audit")

    def __repr__(self) -> str:
        return f"<Audit id={self.id} business_id={self.business_id} status={self.status!r}>"
