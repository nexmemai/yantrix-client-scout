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
from app.workers.queue import get_arq_pool, publish_job_event

router = APIRouter(prefix="/run-scout", tags=["Scout"])
logger = logging.getLogger(__name__)

PIPELINE_BATCH_CAP = 100

# Kept here for now - moving to a DB-backed niche resolver is tracked as a
# separate story. Removing the validator wholesale would silently broaden the
# API contract before the worker pipeline knows what to do with new niches.
VALID_NICHES = {
    "dental",
    "salon",
    "real_estate",
    "clinic",
    "gym",
    "restaurant",
    "hotel",
    "ca",
    "lawyer",
    "physiotherapy",
    "optician",
    "veterinary",
    "pharmacy",
    "spa",
    "coaching",
}


class RunScoutRequest(BaseModel):
    niche: str = Field(..., description="Business niche key, e.g. dental or salon")
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
        niche = value.lower().strip()
        if niche not in VALID_NICHES:
            raise ValueError(f"Unknown niche '{niche}'. Valid niches: {sorted(VALID_NICHES)}")
        return niche

    @field_validator("city")
    @classmethod
    def validate_city(cls, value: str) -> str:
        city = value.strip()
        if not city.replace(" ", "").isalpha():
            raise ValueError("City must contain only letters and spaces.")
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
    """Validate, persist a queued DiscoveryJob row, and enqueue the worker task.

    Hot path: this returns in single-digit ms when Redis is healthy. The
    dashboard immediately opens an SSE stream and starts rendering events.
    """
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

    await _enforce_hourly_run_limit(
        payload.niche,
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
        query=f"{payload.niche} in {payload.city}",
        city=payload.city,
        niche=payload.niche,
        source="google_maps",
        status="queued",
        created_at=started_at,
        updated_at=started_at,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    logger.info(
        "[Job %s] [PIPELINE] enqueued niche=%s city=%s depth=%d max_businesses=%d",
        job.id,
        payload.niche,
        payload.city,
        payload.depth,
        payload.max_businesses,
    )

    # Idempotency: ARQ deduplicates identical _job_ids, so a retried client
    # request (or accidental double-submit) cannot trigger two pipeline runs
    # for the same DB job row.
    enqueue_job_id = f"discovery:{job.id}"
    enqueued = await arq.enqueue_job(
        "run_discovery_task",
        job_id=str(job.id),
        niche=payload.niche,
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
            "niche": payload.niche,
            "city": payload.city,
            "max_businesses": payload.max_businesses,
        },
    )

    return PipelineSummary(
        job_id=str(job.id),
        status="queued",
        niche=payload.niche,
        city=payload.city,
        source=job.source,
        message=(
            f"Scout job queued for '{payload.niche}' in '{payload.city}'. "
            "Subscribe to /api/v1/jobs/{job_id}/events for live progress."
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
