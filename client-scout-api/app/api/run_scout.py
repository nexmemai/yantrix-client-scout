"""
api/run_scout.py - POST /run-scout.

Runs the full scout pipeline for a niche + city and returns a final summary:
discover -> audit -> score -> pitch.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.job import DiscoveryJob
from app.services.audit_worker import run_audit_for_business
from app.services.discovery import discover_businesses
from app.services.pitch_generator import generate_and_save_pitch
from app.services.scoring import HIGH_FIT_BUCKET, MID_FIT_BUCKET, score_business

router = APIRouter(prefix="/run-scout", tags=["Scout"])
logger = logging.getLogger(__name__)

PIPELINE_BATCH_CAP = 100
PITCHABLE_BUCKETS = {HIGH_FIT_BUCKET, MID_FIT_BUCKET}

_PIPELINE_SEM: asyncio.Semaphore | None = None


def _get_pipeline_sem() -> asyncio.Semaphore:
    global _PIPELINE_SEM
    if _PIPELINE_SEM is None:
        _PIPELINE_SEM = asyncio.Semaphore(5)
    return _PIPELINE_SEM


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


class BusinessPipelineResult(BaseModel):
    business_id: uuid.UUID
    audited: bool = False
    scored: bool = False
    pitched: bool = False
    skipped_no_website: bool = False
    failed: bool = False
    fit_bucket: str | None = None
    total_score: int | None = None
    error_message: str | None = None


class PipelineSummary(BaseModel):
    job_id: str
    status: str
    niche: str
    city: str
    discovered: int = 0
    audited: int = 0
    scored: int = 0
    pitched: int = 0
    skipped_no_website: int = 0
    failed: int = 0
    high_fit_count: int = 0
    mid_fit_count: int = 0
    high_fit_lead_ids: list[str] = Field(default_factory=list)
    message: str = ""
    started_at: str
    completed_at: str | None = None
    duration_seconds: float | None = None


@router.post(
    "",
    response_model=PipelineSummary,
    status_code=status.HTTP_200_OK,
    summary="Run full discovery, audit, score, and pitch pipeline",
)
async def run_scout(
    payload: RunScoutRequest,
    db: AsyncSession = Depends(get_db),
) -> PipelineSummary:
    started_at = datetime.now(tz=timezone.utc)
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

    settings = get_settings()
    await _enforce_hourly_run_limit(
        payload.niche,
        payload.city,
        started_at,
        settings.RUN_SCOUT_HOURLY_LIMIT,
        db,
    )
    job = DiscoveryJob(
        id=uuid.uuid4(),
        query=f"{payload.niche} in {payload.city}",
        city=payload.city,
        niche=payload.niche,
        source="google_maps",
        status="running",
        started_at=started_at,
        created_at=started_at,
        updated_at=started_at,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    logger.info(
        "[Job %s] [PIPELINE] started niche=%s city=%s depth=%d max_businesses=%d",
        job.id,
        payload.niche,
        payload.city,
        payload.depth,
        payload.max_businesses,
    )

    summary = PipelineSummary(
        job_id=str(job.id),
        status="running",
        niche=payload.niche,
        city=payload.city,
        started_at=started_at.isoformat(),
    )

    try:
        # ── Stage 1: Discovery ────────────────────────────────────────
        logger.info("[Job %s] [DISCOVERY] starting for %s in %s", job.id, payload.niche, payload.city)
        business_ids = await discover_businesses(
            niche=payload.niche,
            city=payload.city,
            db=db,
            job=job,
            depth=payload.depth,
            max_results=payload.max_businesses,
        )
        summary.discovered = len(business_ids)
        logger.info("[Job %s] [DISCOVERY] complete - %d new businesses found", job.id, len(business_ids))

        # ── Zero-discovery: clean exit ────────────────────────────────
        if not business_ids:
            summary.status = "completed"
            summary.message = (
                f"Discovery returned 0 new businesses for '{payload.niche}' in "
                f"'{payload.city}'. This can happen when the scraper finds no "
                f"results or all discovered businesses already exist in the DB. "
                f"Try increasing depth or using a different city."
            )
            logger.info("[Job %s] [DISCOVERY] zero results - completing job without errors", job.id)
            _finalize_job(job, summary, started_at)
            await db.commit()
            return summary

        # ── Stages 2-4: Audit → Score → Pitch ─────────────────────────
        results = await _process_businesses(business_ids, payload)
        _apply_results_to_summary(summary, results)

        summary.status = "completed"
        summary.message = (
            f"Pipeline complete. {summary.discovered} discovered, "
            f"{summary.audited} audited, {summary.scored} scored, "
            f"{summary.pitched} pitched, {summary.high_fit_count} high-fit leads."
        )
        if summary.failed > 0:
            summary.message += f" ({summary.failed} businesses had failures — see logs.)"

        _finalize_job(job, summary, started_at)
        await db.commit()

        logger.info("[Job %s] [PIPELINE] completed: %s", job.id, summary.message)
        return summary

    except Exception as exc:  # noqa: BLE001
        logger.exception("[Job %s] [PIPELINE] fatal error: %s", job.id, exc)
        summary.status = "failed"
        summary.message = f"Pipeline error: {exc!s}"
        _finalize_job(job, summary, started_at)
        job.error_message = summary.message[:2000]
        await db.commit()
        return summary


async def _process_businesses(
    business_ids: list[uuid.UUID],
    payload: RunScoutRequest,
) -> list[BusinessPipelineResult]:
    if not business_ids:
        return []

    tasks = [
        _process_one_business(business_id=business_id, payload=payload)
        for business_id in business_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    normalized: list[BusinessPipelineResult] = []
    for business_id, result in zip(business_ids, results, strict=False):
        if isinstance(result, Exception):
            logger.exception("[%s] unhandled business pipeline error", business_id, exc_info=result)
            normalized.append(
                BusinessPipelineResult(
                    business_id=business_id,
                    failed=True,
                    error_message=str(result),
                )
            )
        else:
            normalized.append(result)
    return normalized


async def _process_one_business(
    business_id: uuid.UUID,
    payload: RunScoutRequest,
) -> BusinessPipelineResult:
    from app.database import AsyncSessionLocal

    async with _get_pipeline_sem():
        async with AsyncSessionLocal() as db:
            result = BusinessPipelineResult(business_id=business_id)
            try:
                # ── Audit ─────────────────────────────────────────────
                audit = None
                if payload.auto_audit:
                    logger.info("[%s] [AUDIT] starting", business_id)
                    audit = await run_audit_for_business(business_id, db)
                    if audit is None:
                        result.skipped_no_website = True
                        logger.info("[%s] [AUDIT] skipped — no website URL", business_id)
                        return result
                    if audit.status != "completed":
                        result.failed = True
                        result.error_message = audit.error_message or f"Audit status: {audit.status}"
                        logger.warning("[%s] [AUDIT] failed: %s", business_id, result.error_message)
                        return result
                    result.audited = True
                    logger.info("[%s] [AUDIT] completed", business_id)

                # ── Score ─────────────────────────────────────────────
                score_outcome = None
                if payload.auto_score and audit and audit.status == "completed":
                    logger.info("[%s] [SCORE] starting", business_id)
                    score_outcome = await score_business(business_id, db)
                    if score_outcome is None:
                        result.failed = True
                        result.error_message = "Scoring returned no result."
                        logger.warning("[%s] [SCORE] failed: no result", business_id)
                        return result
                    result.scored = True
                    result.fit_bucket = score_outcome.fit_bucket
                    result.total_score = score_outcome.total_score
                    logger.info(
                        "[%s] [SCORE] completed total=%d bucket=%s",
                        business_id,
                        score_outcome.total_score,
                        score_outcome.fit_bucket,
                    )

                # ── Pitch ─────────────────────────────────────────────
                if (
                    payload.auto_pitch
                    and score_outcome
                    and score_outcome.fit_bucket in PITCHABLE_BUCKETS
                ):
                    logger.info("[%s] [PITCH] generating for bucket=%s", business_id, score_outcome.fit_bucket)
                    tone = "professional" if payload.pitch_tone == "auto" else payload.pitch_tone
                    await generate_and_save_pitch(business_id=business_id, db=db, tone=tone)
                    result.pitched = True
                    logger.info("[%s] [PITCH] completed", business_id)

                return result

            except Exception as exc:  # noqa: BLE001
                logger.exception("[%s] [PIPELINE] business processing failed: %s", business_id, exc)
                result.failed = True
                result.error_message = str(exc)
                return result


def _apply_results_to_summary(
    summary: PipelineSummary,
    results: list[BusinessPipelineResult],
) -> None:
    summary.audited = sum(1 for result in results if result.audited)
    summary.scored = sum(1 for result in results if result.scored)
    summary.pitched = sum(1 for result in results if result.pitched)
    summary.skipped_no_website = sum(1 for result in results if result.skipped_no_website)
    summary.failed = sum(1 for result in results if result.failed)
    summary.high_fit_lead_ids = [
        str(result.business_id)
        for result in results
        if result.fit_bucket == HIGH_FIT_BUCKET
    ]
    summary.high_fit_count = len(summary.high_fit_lead_ids)
    summary.mid_fit_count = sum(1 for result in results if result.fit_bucket == MID_FIT_BUCKET)


def _finalize_job(
    job: DiscoveryJob,
    summary: PipelineSummary,
    started_at: datetime,
) -> None:
    completed_at = datetime.now(tz=timezone.utc)
    summary.completed_at = completed_at.isoformat()
    summary.duration_seconds = round((completed_at - started_at).total_seconds(), 1)

    job.status = summary.status
    job.total_discovered = summary.discovered
    job.total_audited = summary.audited
    job.total_scored = summary.scored
    job.completed_at = completed_at
    job.updated_at = completed_at


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
