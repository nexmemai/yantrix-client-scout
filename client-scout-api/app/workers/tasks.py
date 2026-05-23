"""
workers/tasks.py - ARQ task definitions for the Client Scout pipeline.

Tasks here run inside the dedicated worker container, NOT the FastAPI
process. Each task:

  * opens its own AsyncSession (never shares the API's session),
  * heartbeats its DiscoveryJob row every WORKER_HEARTBEAT_INTERVAL_SECONDS
    so the orphan reaper can spot crashed workers,
  * publishes progress events to a Redis pub/sub channel for the SSE stream
    consumed by the dashboard.

Public tasks (registered in WorkerSettings.functions):
  - run_discovery_task: end-to-end orchestrator (discovery + audit + score +
    pitch). Mirrors the legacy `_run_scout_job` semantics exactly so cutover
    is behaviour-preserving.
  - run_audit_task / run_score_task / run_pitch_task: single-lead retry
    handlers. Useful for "regenerate audit" or "retry pitch" UI actions.

Cron job:
  - reap_stale_jobs: marks any DiscoveryJob whose heartbeat is older than
    WORKER_STALE_JOB_THRESHOLD_SECONDS as `failed`. This is what eliminates
    the previous "stuck running forever" failure mode after worker crashes.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.job import DiscoveryJob
from app.workers.queue import publish_job_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage names - canonical set used in the SSE event envelope. Keep in sync
# with the dashboard's progress-bar logic.
# ---------------------------------------------------------------------------

STAGE_DISCOVERY = "discovery"
STAGE_AUDIT = "audit"
STAGE_SCORE = "score"
STAGE_PITCH = "pitch"
STAGE_PIPELINE = "pipeline"

JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


# ---------------------------------------------------------------------------
# Heartbeat loop: a fire-and-forget asyncio task that bumps last_heartbeat
# while the parent task is in-flight. Cancelled in finally().
# ---------------------------------------------------------------------------


class _HeartbeatLoop:
    """Periodically writes `last_heartbeat = now()` for one DiscoveryJob.

    Designed for `async with`. Each tick uses its own short-lived session so
    heartbeats do not contend with the long pipeline transaction. If a tick
    fails (network blip, DB restart) it is logged and skipped - we'd rather
    miss a heartbeat than crash the parent task.
    """

    def __init__(self, job_id: uuid.UUID, worker_id: str, interval_seconds: int) -> None:
        self._job_id = job_id
        self._worker_id = worker_id
        self._interval = max(5, int(interval_seconds))
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "_HeartbeatLoop":
        # Initial tick is immediate so the row reflects "alive" before the
        # first long blocking call (the gosom poll can take 60+ seconds).
        await self._tick()
        self._task = asyncio.create_task(self._run(), name=f"heartbeat:{self._job_id}")
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval)
                await self._tick()
        except asyncio.CancelledError:
            return

    async def _tick(self) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(DiscoveryJob)
                    .where(DiscoveryJob.id == self._job_id)
                    .values(
                        last_heartbeat=datetime.now(tz=timezone.utc),
                        worker_id=self._worker_id,
                    )
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - never crash the parent
            logger.warning(
                "[HEARTBEAT] tick failed job=%s worker=%s: %s",
                self._job_id,
                self._worker_id,
                exc,
            )


# ---------------------------------------------------------------------------
# Public ARQ tasks
# ---------------------------------------------------------------------------


async def run_discovery_task(
    ctx: dict[str, Any],
    job_id: str,
    niche: str,
    city: str,
    depth: int,
    max_businesses: int,
    auto_audit: bool = True,
    auto_score: bool = True,
    auto_pitch: bool = True,
    pitch_tone: str = "professional",
) -> dict[str, Any]:
    """Run the full scout pipeline for one DiscoveryJob.

    Behaviour-preserving port of the legacy in-process `_run_scout_job`:
    discovery -> per-lead (audit -> score -> pitch). The orchestration
    stays inside this task on purpose so we cut over without changing
    semantics; future PRs can fan out per-lead audit work via
    `enqueue_job("run_audit_task", ...)` once we have a completion watcher.
    """
    job_uuid = uuid.UUID(job_id)
    settings = get_settings()
    worker_id = ctx.get("worker_id") or f"{socket.gethostname()}:{ctx.get('job_try', 0)}"
    redis = ctx.get("redis")  # ArqRedis - usable for both publish and enqueue

    # Resolve the job row up-front so we can fail fast if the API and the
    # worker disagree on existence (e.g. a manually deleted job).
    async with AsyncSessionLocal() as db:
        job = await db.get(DiscoveryJob, job_uuid)
        if job is None:
            logger.error("[Job %s] [PIPELINE] job row missing - skipping task", job_uuid)
            return {"ok": False, "reason": "job_missing"}

        # Mark running and bump attempts. ARQ retries the task on transient
        # failures; the column lets operators correlate retries with logs.
        job.status = JOB_STATUS_RUNNING
        job.attempts = (job.attempts or 0) + 1
        job.worker_id = worker_id
        job.last_heartbeat = datetime.now(tz=timezone.utc)
        if job.started_at is None:
            job.started_at = datetime.now(tz=timezone.utc)
        await db.commit()

    if redis is not None:
        await publish_job_event(
            redis,
            job_uuid,
            "stage_started",
            stage=STAGE_PIPELINE,
            data={"niche": niche, "city": city, "max_businesses": max_businesses},
        )

    # Defer heavy imports until inside the worker so the API container does
    # not pay the Playwright import cost just to enqueue a job.
    from app.services.audit_worker import (
        audit_failure_reason,
        run_audit_for_business,
    )
    from app.services.discovery import discover_businesses
    from app.services.pitch_generator import generate_and_save_pitch
    from app.services.scoring import (
        HIGH_FIT_BUCKET,
        MID_FIT_BUCKET,
        score_business,
    )

    pitchable_buckets = {HIGH_FIT_BUCKET, MID_FIT_BUCKET}
    pipeline_sem = asyncio.Semaphore(max(1, settings.AUDIT_CONCURRENCY))
    summary = _empty_summary()

    try:
        async with _HeartbeatLoop(
            job_uuid,
            worker_id,
            settings.WORKER_HEARTBEAT_INTERVAL_SECONDS,
        ):
            # ── Stage 1: Discovery ─────────────────────────────────────
            if redis is not None:
                await publish_job_event(redis, job_uuid, "stage_started", stage=STAGE_DISCOVERY)
            async with AsyncSessionLocal() as db:
                job = await db.get(DiscoveryJob, job_uuid)
                business_ids = await discover_businesses(
                    niche=niche,
                    city=city,
                    db=db,
                    job=job,
                    depth=depth,
                    max_results=max_businesses,
                )
                summary["discovered"] = len(business_ids)
                if job is not None:
                    job.total_discovered = summary["discovered"]
                await db.commit()

            if redis is not None:
                await publish_job_event(
                    redis,
                    job_uuid,
                    "stage_completed",
                    stage=STAGE_DISCOVERY,
                    data={"discovered": summary["discovered"]},
                )

            # Zero-discovery short-circuit: still a successful run.
            if not business_ids:
                await _finalise_job(
                    job_uuid,
                    JOB_STATUS_COMPLETED,
                    summary,
                    error_message=None,
                )
                if redis is not None:
                    await publish_job_event(
                        redis,
                        job_uuid,
                        "job_completed",
                        stage=STAGE_PIPELINE,
                        data={**summary, "message": "Discovery returned 0 businesses."},
                    )
                return {"ok": True, "summary": summary}

            # ── Stages 2-4: per-lead audit/score/pitch (bounded fan-out) ──
            tasks = [
                _process_one_business(
                    business_id=business_id,
                    auto_audit=auto_audit,
                    auto_score=auto_score,
                    auto_pitch=auto_pitch,
                    pitch_tone=pitch_tone,
                    pitchable_buckets=pitchable_buckets,
                    pipeline_sem=pipeline_sem,
                    job_uuid=job_uuid,
                    redis=redis,
                    audit_runner=run_audit_for_business,
                    audit_reason=audit_failure_reason,
                    score_runner=score_business,
                    pitch_runner=generate_and_save_pitch,
                    high_fit=HIGH_FIT_BUCKET,
                    mid_fit=MID_FIT_BUCKET,
                )
                for business_id in business_ids
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            _apply_results(summary, results, business_ids)

            await _finalise_job(
                job_uuid,
                JOB_STATUS_COMPLETED,
                summary,
                error_message=None,
            )
            if redis is not None:
                await publish_job_event(
                    redis,
                    job_uuid,
                    "job_completed",
                    stage=STAGE_PIPELINE,
                    data=summary,
                )

        return {"ok": True, "summary": summary}

    except Exception as exc:  # noqa: BLE001 - record failure and rethrow
        logger.exception("[Job %s] [PIPELINE] fatal error: %s", job_uuid, exc)
        await _finalise_job(
            job_uuid,
            JOB_STATUS_FAILED,
            summary,
            error_message=str(exc)[:2000],
        )
        if redis is not None:
            await publish_job_event(
                redis,
                job_uuid,
                "job_failed",
                stage=STAGE_PIPELINE,
                data={**summary, "error": str(exc)[:500]},
            )
        # Re-raise so ARQ records the failure and (depending on retry policy)
        # may schedule a retry. The reaper covers the case where the worker
        # dies before reaching this except branch.
        raise


async def run_audit_task(
    ctx: dict[str, Any],
    business_id: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Single-business audit - usable for "regenerate audit" UI actions."""
    from app.services.audit_worker import run_audit_for_business

    business_uuid = uuid.UUID(business_id)
    redis = ctx.get("redis")

    async with AsyncSessionLocal() as db:
        audit = await run_audit_for_business(business_uuid, db)
        await db.commit()

    if redis is not None and job_id is not None:
        await publish_job_event(
            redis,
            job_id,
            "stage_completed",
            stage=STAGE_AUDIT,
            data={
                "business_id": business_id,
                "status": audit.status if audit is not None else "no_website",
            },
        )

    return {
        "ok": audit is not None,
        "business_id": business_id,
        "audit_status": audit.status if audit is not None else None,
    }


async def run_score_task(
    ctx: dict[str, Any],
    business_id: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Single-business scoring - rule-based, fast."""
    from app.services.scoring import score_business

    business_uuid = uuid.UUID(business_id)
    redis = ctx.get("redis")

    async with AsyncSessionLocal() as db:
        outcome = await score_business(business_uuid, db)
        await db.commit()

    if redis is not None and job_id is not None and outcome is not None:
        await publish_job_event(
            redis,
            job_id,
            "stage_completed",
            stage=STAGE_SCORE,
            data={
                "business_id": business_id,
                "total_score": outcome.total_score,
                "fit_bucket": outcome.fit_bucket,
            },
        )

    return {
        "ok": outcome is not None,
        "business_id": business_id,
        "total_score": outcome.total_score if outcome is not None else None,
        "fit_bucket": outcome.fit_bucket if outcome is not None else None,
    }


async def run_pitch_task(
    ctx: dict[str, Any],
    business_id: str,
    tone: str = "professional",
    job_id: str | None = None,
) -> dict[str, Any]:
    """Single-business pitch generation - LLM-bound, gated by per-call retries."""
    from app.services.pitch_generator import generate_and_save_pitch

    business_uuid = uuid.UUID(business_id)
    redis = ctx.get("redis")

    async with AsyncSessionLocal() as db:
        try:
            await generate_and_save_pitch(business_id=business_uuid, db=db, tone=tone)
            ok = True
            err: str | None = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] [PITCH] failed: %s", business_uuid, exc)
            ok = False
            err = str(exc)[:500]
            await db.rollback()

    if redis is not None and job_id is not None:
        await publish_job_event(
            redis,
            job_id,
            "stage_completed" if ok else "stage_failed",
            stage=STAGE_PITCH,
            data={"business_id": business_id, "ok": ok, "error": err},
        )
    return {"ok": ok, "business_id": business_id, "error": err}


# ---------------------------------------------------------------------------
# Cron: orphan reaper
# ---------------------------------------------------------------------------


async def reap_stale_jobs(ctx: dict[str, Any]) -> dict[str, int]:
    """Mark DiscoveryJobs that haven't heartbeated recently as failed.

    Runs once a minute (registered in arq_worker.py). The query is cheap
    thanks to the partial index on (last_heartbeat) WHERE status='running'.

    Why both `last_heartbeat` AND `started_at` checks?
      - `last_heartbeat` is the live signal once a worker has picked up
        the job. Stale heartbeat => worker crashed mid-flight.
      - `started_at` covers a corner case: a job that was enqueued but
        never picked up (e.g. all workers down at enqueue time). Without
        this, such a job would sit at status='running' with NULL
        last_heartbeat indefinitely, since reapers normally ignore NULL.
    """
    settings = get_settings()
    threshold = timedelta(seconds=settings.WORKER_STALE_JOB_THRESHOLD_SECONDS)
    now = datetime.now(tz=timezone.utc)
    cutoff = now - threshold

    async with AsyncSessionLocal() as db:
        # Find candidates first so we can publish a job_failed event for each.
        result = await db.execute(
            select(DiscoveryJob.id).where(
                DiscoveryJob.status == JOB_STATUS_RUNNING,
                # Either heartbeat has gone silent, or there is no heartbeat
                # but the job has been "running" for longer than the threshold.
                # COALESCE(last_heartbeat, started_at, created_at) < cutoff.
                (
                    (DiscoveryJob.last_heartbeat.is_not(None) & (DiscoveryJob.last_heartbeat < cutoff))
                    | (
                        DiscoveryJob.last_heartbeat.is_(None)
                        & (
                            (DiscoveryJob.started_at.is_not(None) & (DiscoveryJob.started_at < cutoff))
                            | (
                                DiscoveryJob.started_at.is_(None)
                                & (DiscoveryJob.created_at < cutoff)
                            )
                        )
                    )
                ),
            )
        )
        stale_ids = [row[0] for row in result.all()]
        if not stale_ids:
            return {"reaped": 0}

        await db.execute(
            update(DiscoveryJob)
            .where(DiscoveryJob.id.in_(stale_ids))
            .values(
                status=JOB_STATUS_FAILED,
                error_message="reaper: worker died or never picked up the job",
                completed_at=now,
                updated_at=now,
            )
        )
        await db.commit()

    redis = ctx.get("redis")
    if redis is not None:
        for job_id in stale_ids:
            try:
                await publish_job_event(
                    redis,
                    job_id,
                    "job_failed",
                    stage=STAGE_PIPELINE,
                    data={"error": "worker_died", "reaper": True},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[REAPER] publish failed job=%s: %s", job_id, exc)

    logger.warning("[REAPER] marked %d job(s) as failed: %s", len(stale_ids), stale_ids)
    return {"reaped": len(stale_ids)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _empty_summary() -> dict[str, Any]:
    return {
        "discovered": 0,
        "audited": 0,
        "scored": 0,
        "pitched": 0,
        "skipped_no_website": 0,
        "failed_dns": 0,
        "failed_audit_other": 0,
        "failed": 0,
        "high_fit_count": 0,
        "mid_fit_count": 0,
        "high_fit_lead_ids": [],
    }


async def _process_one_business(
    *,
    business_id: uuid.UUID,
    auto_audit: bool,
    auto_score: bool,
    auto_pitch: bool,
    pitch_tone: str,
    pitchable_buckets: set[str],
    pipeline_sem: asyncio.Semaphore,
    job_uuid: uuid.UUID,
    redis: Any,
    audit_runner: Any,
    audit_reason: Any,
    score_runner: Any,
    pitch_runner: Any,
    high_fit: str,
    mid_fit: str,
) -> dict[str, Any]:
    """Run audit -> score -> pitch for one business in its own DB session."""
    async with pipeline_sem:
        async with AsyncSessionLocal() as db:
            outcome: dict[str, Any] = {
                "business_id": str(business_id),
                "audited": False,
                "scored": False,
                "pitched": False,
                "skipped_no_website": False,
                "failed_dns": False,
                "failed_audit_other": False,
                "failed": False,
                "fit_bucket": None,
                "total_score": None,
                "error_message": None,
            }
            try:
                # ── Audit ────────────────────────────────────────────
                audit = None
                if auto_audit:
                    audit = await audit_runner(business_id, db)
                    if audit is None:
                        outcome["skipped_no_website"] = True
                        outcome["error_message"] = "no_website"
                        return outcome
                    reason = audit_reason(audit.error_message)
                    if audit.status == "skipped" and reason == "no_website":
                        outcome["skipped_no_website"] = True
                        outcome["error_message"] = audit.error_message
                        return outcome
                    if audit.status != "completed":
                        outcome["failed"] = True
                        if reason == "dns_resolution_failed":
                            outcome["failed_dns"] = True
                        else:
                            outcome["failed_audit_other"] = True
                        outcome["error_message"] = audit.error_message
                        return outcome
                    outcome["audited"] = True

                # ── Score ────────────────────────────────────────────
                score_outcome = None
                if auto_score and audit is not None and audit.status == "completed":
                    score_outcome = await score_runner(business_id, db)
                    if score_outcome is None:
                        outcome["failed"] = True
                        outcome["error_message"] = "score_no_result"
                        return outcome
                    outcome["scored"] = True
                    outcome["fit_bucket"] = score_outcome.fit_bucket
                    outcome["total_score"] = score_outcome.total_score

                # ── Pitch ────────────────────────────────────────────
                if (
                    auto_pitch
                    and score_outcome is not None
                    and score_outcome.fit_bucket in pitchable_buckets
                ):
                    tone = "professional" if pitch_tone == "auto" else pitch_tone
                    await pitch_runner(business_id=business_id, db=db, tone=tone)
                    outcome["pitched"] = True

                if redis is not None:
                    # Lightweight per-lead progress tick - powers the dashboard's
                    # live counter without forcing an extra DB round-trip.
                    await publish_job_event(
                        redis,
                        job_uuid,
                        "stage_progress",
                        stage=STAGE_PIPELINE,
                        data={
                            "business_id": str(business_id),
                            "audited": outcome["audited"],
                            "scored": outcome["scored"],
                            "pitched": outcome["pitched"],
                            "fit_bucket": outcome["fit_bucket"],
                        },
                    )
                return outcome

            except Exception as exc:  # noqa: BLE001 - record per-lead failure
                logger.exception("[%s] [PIPELINE] business processing failed", business_id)
                outcome["failed"] = True
                outcome["error_message"] = str(exc)[:500]
                return outcome


def _apply_results(
    summary: dict[str, Any],
    results: list[Any],
    business_ids: list[uuid.UUID],
) -> None:
    """Aggregate per-lead outcomes into the job summary in-place."""
    high_fit_ids: list[str] = []
    for business_id, result in zip(business_ids, results, strict=False):
        if isinstance(result, Exception):
            logger.exception("[%s] unhandled task error", business_id, exc_info=result)
            summary["failed"] += 1
            continue
        if result.get("audited"):
            summary["audited"] += 1
        if result.get("scored"):
            summary["scored"] += 1
        if result.get("pitched"):
            summary["pitched"] += 1
        if result.get("skipped_no_website"):
            summary["skipped_no_website"] += 1
        if result.get("failed_dns"):
            summary["failed_dns"] += 1
        if result.get("failed_audit_other"):
            summary["failed_audit_other"] += 1
        if result.get("failed"):
            summary["failed"] += 1
        bucket = result.get("fit_bucket")
        if bucket == "high-fit":
            high_fit_ids.append(str(business_id))
            summary["high_fit_count"] += 1
        elif bucket == "mid-fit":
            summary["mid_fit_count"] += 1
    summary["high_fit_lead_ids"] = high_fit_ids


async def _finalise_job(
    job_id: uuid.UUID,
    status: str,
    summary: dict[str, Any],
    error_message: str | None,
) -> None:
    """Write final job state in a fresh session so heartbeat tasks can stop."""
    now = datetime.now(tz=timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(DiscoveryJob)
            .where(DiscoveryJob.id == job_id)
            .values(
                status=status,
                total_discovered=summary["discovered"],
                total_audited=summary["audited"],
                total_scored=summary["scored"],
                completed_at=now,
                updated_at=now,
                last_heartbeat=now,
                error_message=error_message,
            )
        )
        await db.commit()
