"""
models/config.py — ORM model for per-niche scoring configurations.
Replaces scoring_configs. Synced with migrations/001_initial_schema.sql :: niche_configs.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


from app.database import Base


class NicheConfig(Base):
    __tablename__ = "niche_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    niche: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(150))

    # Scoring weights
    weight_website: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=20)
    weight_mobile: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=15)
    weight_forms: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=15)
    weight_whatsapp: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)
    weight_booking: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=20)
    weight_social: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)
    weight_seo: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)
    weights: Mapped[dict | None] = mapped_column(JSONB)

    prompt_template: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("weight_website BETWEEN 0 AND 100", name="chk_w_website"),
        CheckConstraint("weight_mobile BETWEEN 0 AND 100", name="chk_w_mobile"),
        CheckConstraint("weight_forms BETWEEN 0 AND 100", name="chk_w_forms"),
        CheckConstraint("weight_whatsapp BETWEEN 0 AND 100", name="chk_w_whatsapp"),
        CheckConstraint("weight_booking BETWEEN 0 AND 100", name="chk_w_booking"),
        CheckConstraint("weight_social BETWEEN 0 AND 100", name="chk_w_social"),
        CheckConstraint("weight_seo BETWEEN 0 AND 100", name="chk_w_seo"),
    )

    def __repr__(self) -> str:
        return f"<NicheConfig niche={self.niche!r} is_default={self.is_default}>"
