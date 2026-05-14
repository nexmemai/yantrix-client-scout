"""
services/scoring.py - Gap-based scoring engine.

This module computes a weighted lead-fit score from audit and business signals.
It loads the matching niche config row for FK linkage, but uses code-defined
gap weights until the DB config schema is expanded to match these categories.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import Audit
from app.models.business import Business
from app.models.config import NicheConfig
from app.models.score import Score

logger = logging.getLogger(__name__)

WEAK_WEBSITE = "weak_website"
LEAD_CAPTURE_GAP = "lead_capture_gap"
OUTDATED_CONTACT = "outdated_contact"
HIGH_TICKET = "high_ticket"
TRUST_GAP = "trust_gap"
AUTOMATION_GAP = "automation_gap"

DEFAULT_GAP_WEIGHTS: dict[str, int] = {
    WEAK_WEBSITE: 20,
    LEAD_CAPTURE_GAP: 25,
    OUTDATED_CONTACT: 10,
    HIGH_TICKET: 20,
    TRUST_GAP: 10,
    AUTOMATION_GAP: 15,
}

HIGH_FIT_MIN_SCORE = 60
MID_FIT_MIN_SCORE = 40

HIGH_FIT_BUCKET = "high-fit"
MID_FIT_BUCKET = "mid-fit"
LOW_FIT_BUCKET = "low-fit"

HIGH_TICKET_NICHES = {
    "ca",
    "clinic",
    "dental",
    "gym",
    "lawyer",
    "optician",
    "physiotherapy",
    "real_estate",
    "spa",
    "veterinary",
}


@dataclass(frozen=True)
class ScoreOutcome:
    """Returned by score_business after the DB row is upserted."""

    score: Score
    total_score: int
    fit_bucket: str
    breakdown: dict[str, int]


async def score_business(
    business_id: uuid.UUID | str,
    db: AsyncSession,
) -> ScoreOutcome | None:
    """
    Score a business from its linked audit signals and persist the result.

    The matching niche config row is loaded from DB for FK reference and
    fallback behavior, but weights remain code-defined in this version.
    """
    if isinstance(business_id, str):
        business_id = uuid.UUID(business_id)

    business = await _load_business(business_id, db)
    if business is None:
        logger.error("score_business: Business %s not found", business_id)
        return None

    audit = await _load_audit(business_id, db)
    if audit is None or audit.status != "completed":
        logger.warning(
            "score_business: No completed audit for business %s (status=%s)",
            business_id,
            audit.status if audit else "missing",
        )
        return None

    niche_config = await _load_niche_config(business.niche, db)
    weights = DEFAULT_GAP_WEIGHTS.copy()
    breakdown = compute_gap_breakdown(business, audit, weights)
    total_score = min(100, max(0, sum(breakdown.values())))
    fit_bucket = bucket_for_score(total_score)

    score = await _upsert_score(
        business_id=business_id,
        audit_id=audit.id,
        niche_config_id=niche_config.id if niche_config else None,
        total_score=total_score,
        breakdown=breakdown,
        db=db,
    )

    await db.refresh(score)
    _update_business_stage(business, fit_bucket)
    await db.commit()

    logger.info(
        "Gap score complete business=%s total=%d bucket=%s breakdown=%s",
        business_id,
        total_score,
        fit_bucket,
        breakdown,
    )

    return ScoreOutcome(
        score=score,
        total_score=total_score,
        fit_bucket=fit_bucket,
        breakdown=breakdown,
    )


def compute_gap_breakdown(
    business: Business,
    audit: Audit,
    weights: dict[str, int] | None = None,
) -> dict[str, int]:
    """Compute a per-signal breakdown using all-or-nothing gap weights."""
    active_weights = weights or DEFAULT_GAP_WEIGHTS

    return {
        WEAK_WEBSITE: active_weights[WEAK_WEBSITE] if has_weak_website_gap(audit) else 0,
        LEAD_CAPTURE_GAP: active_weights[LEAD_CAPTURE_GAP] if has_lead_capture_gap(audit) else 0,
        OUTDATED_CONTACT: active_weights[OUTDATED_CONTACT] if has_outdated_contact_gap(business, audit) else 0,
        HIGH_TICKET: active_weights[HIGH_TICKET] if is_high_ticket_business(business) else 0,
        TRUST_GAP: active_weights[TRUST_GAP] if has_trust_gap(business, audit) else 0,
        AUTOMATION_GAP: active_weights[AUTOMATION_GAP] if has_automation_gap(audit) else 0,
    }


def bucket_for_score(total_score: int) -> str:
    """Map a numeric score to the requested fit buckets."""
    if total_score >= HIGH_FIT_MIN_SCORE:
        return HIGH_FIT_BUCKET
    if total_score >= MID_FIT_MIN_SCORE:
        return MID_FIT_BUCKET
    return LOW_FIT_BUCKET


def is_high_fit_score(total_score: int) -> bool:
    """True when a score belongs to the high-fit bucket."""
    return total_score >= HIGH_FIT_MIN_SCORE


def has_weak_website_gap(audit: Audit) -> bool:
    """Flag weak websites using a small set of public website quality heuristics."""
    if not audit.has_website:
        return True

    issues = 0
    if not audit.ssl_valid:
        issues += 1
    if not audit.mobile_friendly:
        issues += 1
    if not audit.has_title:
        issues += 1
    if not audit.has_meta_desc:
        issues += 1
    if not audit.has_h1:
        issues += 1
    if _is_slow_site(audit):
        issues += 1

    return issues >= 2


def has_lead_capture_gap(audit: Audit) -> bool:
    """Flag sites with weak conversion capture paths."""
    capture_channels = sum(
        bool(signal)
        for signal in (
            audit.has_forms,
            audit.has_cta,
            audit.has_booking,
            _get_bool(audit, "has_tel_links"),
        )
    )
    return capture_channels <= 1


def has_outdated_contact_gap(business: Business, audit: Audit) -> bool:
    """Flag leads with no clear public contact path."""
    has_contact_path = any(
        (
            bool((business.phone or "").strip()),
            bool((business.email or "").strip()),
            _get_bool(audit, "has_tel_links"),
            audit.has_whatsapp,
        )
    )
    return not has_contact_path


def is_high_ticket_business(business: Business) -> bool:
    """Use the niche first, then category keywords, to identify high-ticket leads."""
    niche = (business.niche or "").strip().lower()
    if niche in HIGH_TICKET_NICHES:
        return True

    category = (business.category or "").strip().lower()
    return any(
        keyword in category
        for keyword in (
            "dental",
            "clinic",
            "doctor",
            "law",
            "legal",
            "real estate",
            "property",
            "physio",
            "spa",
        )
    )


def has_trust_gap(business: Business, audit: Audit) -> bool:
    """Flag weak public trust signals across reviews, rating, and social presence."""
    trust_issues = 0
    rating = _as_float(business.rating)
    reviews = business.review_count or 0

    if rating == 0 or rating < 4.2:
        trust_issues += 1
    if reviews < 20:
        trust_issues += 1
    if not any((audit.has_facebook, audit.has_instagram, audit.has_linkedin, audit.has_twitter)):
        trust_issues += 1

    return trust_issues >= 2


def has_automation_gap(audit: Audit) -> bool:
    """Flag missing sales automation helpers like WhatsApp, booking, or chat."""
    automation_channels = sum(
        bool(signal)
        for signal in (
            audit.has_whatsapp,
            audit.has_booking,
            audit.has_chatbot,
        )
    )
    return automation_channels == 0


async def _load_business(business_id: uuid.UUID, db: AsyncSession) -> Business | None:
    result = await db.execute(select(Business).where(Business.id == business_id))
    return result.scalar_one_or_none()


async def _load_audit(business_id: uuid.UUID, db: AsyncSession) -> Audit | None:
    result = await db.execute(select(Audit).where(Audit.business_id == business_id))
    return result.scalar_one_or_none()


async def _load_niche_config(
    niche: str | None,
    db: AsyncSession,
) -> NicheConfig | None:
    """Load the niche-specific config row, then default config if needed."""
    if niche:
        result = await db.execute(select(NicheConfig).where(NicheConfig.niche == niche))
        config = result.scalar_one_or_none()
        if config is not None:
            return config

    result = await db.execute(select(NicheConfig).where(NicheConfig.is_default.is_(True)))
    config = result.scalar_one_or_none()
    if config is None:
        logger.debug("No niche_configs row found for niche=%r or default config", niche)
    return config


async def _upsert_score(
    business_id: uuid.UUID,
    audit_id: uuid.UUID,
    niche_config_id: uuid.UUID | None,
    total_score: int,
    breakdown: dict[str, int],
    db: AsyncSession,
) -> Score:
    """Upsert the score row while preserving the existing scores table schema."""
    result = await db.execute(select(Score).where(Score.business_id == business_id))
    score = result.scalar_one_or_none()

    if score is None:
        score = Score(id=uuid.uuid4(), business_id=business_id)
        db.add(score)

    score.audit_id = audit_id
    score.niche_config_id = niche_config_id
    score.overall_score = total_score
    score.website_quality = breakdown[WEAK_WEBSITE]
    score.conversion_readiness = breakdown[LEAD_CAPTURE_GAP] + breakdown[AUTOMATION_GAP]
    score.online_presence = breakdown[OUTDATED_CONTACT] + breakdown[TRUST_GAP]
    score.urgency = breakdown[HIGH_TICKET]
    score.llm_provider = "rule_engine"
    score.llm_model = "gap_weighted_v1"

    await db.flush()
    return score


def _update_business_stage(business: Business, fit_bucket: str) -> None:
    """
    Promote high-fit businesses using valid stage values from the DB enum.

    Lower buckets remain `new` so they can be reviewed later without being
    prematurely marked as rejected.
    """
    if fit_bucket == HIGH_FIT_BUCKET:
        business.stage = "qualified"
    else:
        business.stage = "new"


def _get_bool(obj: Any, attr_name: str) -> bool:
    return bool(getattr(obj, attr_name, False))


def _as_float(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _is_slow_site(audit: Audit) -> bool:
    page_speed = audit.page_speed_score
    if page_speed is not None:
        return page_speed < 50
    load_time_ms = audit.load_time_ms or 0
    return load_time_ms > 5000
