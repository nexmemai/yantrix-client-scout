"""
api/lead_queries.py - shared lead filtering helpers.
"""

from datetime import datetime
from typing import Literal

from sqlalchemy import func

from app.models.business import Business
from app.models.score import Score
from app.services.scoring import HIGH_FIT_MIN_SCORE, MID_FIT_MIN_SCORE

LeadBucket = Literal["high", "mid", "low", "high-fit", "mid-fit", "low-fit"]


def lead_filters(
    *,
    city: str | None = None,
    category: str | None = None,
    niche: str | None = None,
    source: str | None = None,
    search: str | None = None,
    min_score: int | None = None,
    score_min: int | None = None,
    bucket: str | None = None,
    agency_fit_bucket: str | None = None,
    lead_status: str | None = None,
    priority_rank: int | None = None,
    created_after: datetime | None = None,
) -> list:
    """Build composable SQLAlchemy filters for lead listing and export."""
    filters = []
    if city:
        filters.append(func.lower(Business.city) == city.lower())
    if category:
        filters.append(func.lower(Business.category) == category.lower())
    if niche:
        filters.append(func.lower(Business.niche) == niche.lower())
    if source:
        filters.append(func.lower(Business.source) == source.lower())
    if search:
        pattern = f"%{search.lower()}%"
        filters.append(func.lower(Business.name).like(pattern))

    score_floor = min_score if min_score is not None else score_min
    if score_floor is not None:
        filters.append(Score.overall_score >= score_floor)

    if bucket:
        filters.extend(_bucket_filters(bucket))
    if agency_fit_bucket:
        filters.append(func.lower(Score.agency_fit_bucket) == agency_fit_bucket.lower())
    if lead_status:
        filters.append(func.lower(Business.lead_status) == lead_status.lower())
    if priority_rank is not None:
        filters.append(Business.priority_rank == priority_rank)
    if created_after:
        filters.append(Business.created_at >= created_after)
    return filters


def _bucket_filters(bucket: str) -> list:
    normalized = bucket.lower().strip()
    if normalized in {"high", "high-fit"}:
        return [Score.overall_score >= HIGH_FIT_MIN_SCORE]
    if normalized in {"mid", "mid-fit"}:
        return [
            Score.overall_score >= MID_FIT_MIN_SCORE,
            Score.overall_score < HIGH_FIT_MIN_SCORE,
        ]
    if normalized in {"low", "low-fit"}:
        return [Score.overall_score < MID_FIT_MIN_SCORE]
    return []
