"""
api/run_scout.py - POST /run-scout.

Returns a job_id immediately and enqueues the heavy pipeline (discovery +
audit + score + pitch) onto the ARQ worker queue. The legacy in-process
BackgroundTasks path has been removed: a worker container restart no longer
loses jobs, and heavy pipelines no longer share an event loop with the API.

Real-time progress is delivered to the dashboard over SSE at:
    GET /api/v1/jobs/{job_id}/events
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.job import DiscoveryJob
from app.services.niche_resolver import (
    InvalidNicheError,
    normalize_niche_key,
    resolve_niche,
)
from app.workers.queue import get_arq_pool, publish_job_event

router = APIRouter(prefix="/run-scout", tags=["Scout"])
logger = logging.getLogger(__name__)

PIPELINE_BATCH_CAP = 100

# Free-text city validator. Accepts:
#   - any Unicode letter (Café, São Paulo, Bengaluru),
#   - spaces, hyphens, apostrophes (curly or straight), periods.
# Rejects digits and other punctuation so a typo'd payload like "Pune; DROP"
# fails validation before reaching the gosom client.
CITY_PATTERN = re.compile(r"^[\w\s.\-'\u2019]{2,100}$", flags=re.UNICODE)
# `\w` includes underscores under re.UNICODE which we don't want for cities.
CITY_REJECT_PATTERN = re.compile(r"[\d_]", flags=re.UNICODE)


class RunScoutRequest(BaseModel):
    """Free-text scout payload.

    `niche` is intentionally NOT validated against an allow-list anymore. The
    /run-scout handler runs `resolve_niche()` against the DB + built-in catalog
    + generic fallback so users can target any industry the team adds to
    niche_configs (or anything Google Maps recognises directly).
    """

    niche: str = Field(
        ...,
        min_length=2,
        max_length=80,
        description=(
            "Free-text industry, e.g. 'dental', 'EV charging stations', "
            "'corporate cafeterias'. Resolved server-side via "
            "app.services.niche_resolver."
        ),
    )
    city: str = Field(..., min_length=2, max_length=100, description="City name")
    depth: int = Field(1, ge=1, le=5, description="gosom pagination depth")
    max_businesses: int = Field(
        PIPELINE_BATCH_CAP,
        ge=1,
        description=f"Max businesses to process (cap: {PIPELINE_BATCH_CAP})",
    )
    auto_audit: bool = Field(True, description="Run website audit for each business")
    auto_score: bool = Field(True, description="Run scoring after audit")
    auto_pitch: bool = Field(True, description="Generate pitches for high/mid-fit leads")
    pitch_tone: str = Field("professional", description="Pitch tone metadata")

    @field_validator("niche")
    @classmethod
    def validate_niche(cls, value: str) -> str:
        # We only validate that the input CAN be normalised to a canonical
        # key. The actual resolution (DB + catalog + generic) happens in the
        # handler so we have a session.
        try:
            normalize_niche_key(value)
        except InvalidNicheError as exc:
            raise ValueError(str(exc)) from exc
        return value.strip()

    @field_validator("city")
    @classmethod
    def validate_city(cls, value: str) -> str:
        city = value.strip()
        # Match-and-reject pair: regex modules cannot easily express
        # "any letter except underscore" so we test in two passes.
        if not CITY_PATTERN.match(city) or CITY_REJECT_PATTERN.search(city):
            raise ValueError(
                "City must be 2-100 characters of letters, spaces, hyphens, "
                "apostrophes, or periods (no digits or underscores)."
            )
        return city

    @field_validator("pitch_tone")
    @classmethod
    def validate_pitch_tone(cls, value: str) -> str:
        tone = value.lower().strip()
        valid = {"professional", "friendly", "urgent", "consultative", "auto"}
        if tone not in valid:
            raise ValueError(f"Invalid tone '{tone}'. Choose from {sorted(valid)}")
        return tone


class PipelineSummary(BaseModel):
    """API response after enqueueing - the heavy work runs on the worker.

    Counters stay zero in this response on purpose: the dashboard streams the
    real numbers live via the /jobs/{id}/events SSE feed and falls back to
    polling /jobs/{id} if SSE is unavailable.
    """

    job_id: str
    status: str
    niche: str
    city: str
    source: str = "google_maps"
    discovered: int = 0
    audited: int = 0
    scored: int = 0
    pitched: int = 0
    skipped_no_website: int = 0
    failed_dns: int = 0
    failed_audit_other: int = 0
    failed: int = 0
    high_fit_count: int = 0
    mid_fit_count: int = 0
    high_fit_lead_ids: list[str] = Field(default_factory=list)
    message: str = ""
    created_at: str
    started_at: str
    completed_at: str | None = None
    duration_seconds: float | None = None


@router.post(
    "",
    response_model=PipelineSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue full discovery, audit, score, and pitch pipeline",
)
async def run_scout(
    payload: RunScoutRequest,
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq_pool),
) -> PipelineSummary:
    """Validate, resolve, persist, enqueue. Single-digit ms when Redis is healthy."""
    started_at = datetime.now(tz=timezone.utc)
    settings = get_settings()

    if payload.max_businesses > PIPELINE_BATCH_CAP:
        logger.warning(
            "run-scout rejected max_businesses limit niche=%s city=%s requested=%d",
            payload.niche,
            payload.city,
            payload.max_businesses,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"max_businesses must be <= {PIPELINE_BATCH_CAP}.",
        )

    # Free-text resolution: try DB first, then the built-in catalog, then a
    # generic plural. Throws InvalidNicheError only when the input cannot be
    # normalised (already filtered by the validator, but defensive).
    try:
        resolved = await resolve_niche(payload.niche, db)
    except InvalidNicheError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    await _enforce_hourly_run_limit(
        resolved.key,
        payload.city,
        started_at,
        settings.RUN_SCOUT_HOURLY_LIMIT,
        db,
    )

    # Status begins as "queued"; the worker flips it to "running" on pickup.
    # This distinction lets the dashboard show "waiting for a worker" if
    # every replica is busy.
    job = DiscoveryJob(
        id=uuid.uuid4(),
        query=f"{resolved.search_phrase} in {payload.city}",
        city=payload.city,
        niche=resolved.key,
        source="google_maps",
        status="queued",
        created_at=started_at,
        updated_at=started_at,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    logger.info(
        "[Job %s] [PIPELINE] enqueued niche=%s key=%s phrase=%r city=%s depth=%d max_businesses=%d source=%s",
        job.id,
        payload.niche,
        resolved.key,
        resolved.search_phrase,
        payload.city,
        payload.depth,
        payload.max_businesses,
        resolved.source,
    )

    # Idempotency: ARQ deduplicates identical _job_ids, so a retried client
    # request (or accidental double-submit) cannot trigger two pipeline runs
    # for the same DB job row.
    enqueue_job_id = f"discovery:{job.id}"
    enqueued = await arq.enqueue_job(
        "run_discovery_task",
        job_id=str(job.id),
        niche=resolved.key,
        search_phrase=resolved.search_phrase,
        city=payload.city,
        depth=payload.depth,
        max_businesses=payload.max_businesses,
        auto_audit=payload.auto_audit,
        auto_score=payload.auto_score,
        auto_pitch=payload.auto_pitch,
        pitch_tone=payload.pitch_tone,
        _job_id=enqueue_job_id,
    )
    if enqueued is None:
        # ARQ returns None when a job with the same _job_id is already queued.
        # We still publish "job_queued" so the dashboard renders state, and
        # the existing worker run will drive completion.
        logger.info("[Job %s] enqueue dedup hit (_job_id=%s)", job.id, enqueue_job_id)

    # Seed the SSE state cache so a dashboard that connects in the gap
    # between this response and the worker pickup sees "queued" immediately.
    await publish_job_event(
        arq,
        job.id,
        "job_queued",
        stage="pipeline",
        data={
            "niche": resolved.key,
            "niche_display": resolved.display,
            "search_phrase": resolved.search_phrase,
            "city": payload.city,
            "max_businesses": payload.max_businesses,
            "resolution_source": resolved.source,
        },
    )

    return PipelineSummary(
        job_id=str(job.id),
        status="queued",
        niche=resolved.key,
        city=payload.city,
        source=job.source,
        message=(
            f"Scout job queued for '{resolved.display}' in '{payload.city}' "
            f"(resolved via {resolved.source}). Subscribe to "
            f"/api/v1/jobs/{job.id}/events for live progress."
        ),
        created_at=job.created_at.isoformat(),
        started_at=started_at.isoformat(),
    )


async def _enforce_hourly_run_limit(
    niche: str,
    city: str,
    now: datetime,
    hourly_limit: int,
    db: AsyncSession,
) -> None:
    """Reject excessive run-scout calls for the same niche/city pair."""
    if hourly_limit <= 0:
        return

    window_start = now - timedelta(hours=1)
    stmt = (
        select(func.count(DiscoveryJob.id))
        .where(func.lower(DiscoveryJob.niche) == niche.lower())
        .where(func.lower(DiscoveryJob.city) == city.lower())
        .where(DiscoveryJob.created_at >= window_start)
    )
    recent_runs = await db.scalar(stmt) or 0
    if recent_runs >= hourly_limit:
        logger.warning(
            "run-scout rejected hourly limit niche=%s city=%s recent_runs=%d cap=%d",
            niche,
            city,
            recent_runs,
            hourly_limit,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Hourly run limit reached for {niche} in {city}.",
        )
