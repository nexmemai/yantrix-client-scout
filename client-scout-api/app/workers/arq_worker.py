"""
workers/arq_worker.py - ARQ worker entrypoint.

Run with:
    arq app.workers.arq_worker.WorkerSettings

This process is *separate* from the FastAPI uvicorn process. Heavy pipelines
(discovery + audit + score + pitch) run here so the API event loop never has
to compete with Playwright browsers or LLM calls.

Scaling:
    docker compose up -d --scale worker=3

Each replica pulls jobs from the shared Redis queue. ARQ's max_jobs cap
applies per-process; total cluster concurrency is replicas * max_jobs.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron

from app.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Redis settings helper
# ---------------------------------------------------------------------------


def build_redis_settings() -> RedisSettings:
    """Parse REDIS_URL into the structured form ARQ expects.

    Centralised so the API container (queue.py) and the worker container both
    talk to the same broker with identical retry/connection behaviour.
    """
    return RedisSettings.from_dsn(get_settings().REDIS_URL)


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------


async def on_startup(ctx: dict[str, Any]) -> None:
    """Attach a stable worker_id and warm up shared resources.

    The worker_id is written into discovery_jobs.worker_id by each task so
    operators can trace which container ran which job (and the orphan reaper
    can spot heartbeats from dead replicas).
    """
    worker_id = f"{socket.gethostname()}:{ctx.get('job_try', 0)}"
    ctx["worker_id"] = worker_id
    logger.info("[ARQ] worker startup worker_id=%s", worker_id)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Best-effort dispose of the SQLAlchemy engine on graceful shutdown.

    Without this, the `asyncpg` connection pool can leave open sockets when
    the worker is signalled. Failure is logged, never raised, because shutdown
    must succeed for the orchestrator to redeploy a replica cleanly.
    """
    try:
        from app.database import engine

        await engine.dispose()
    except Exception as exc:  # noqa: BLE001 - shutdown must not throw
        logger.warning("[ARQ] engine.dispose() during shutdown failed: %s", exc)
    logger.info("[ARQ] worker shutdown worker_id=%s", ctx.get("worker_id"))


# ---------------------------------------------------------------------------
# WorkerSettings (the ARQ contract)
# ---------------------------------------------------------------------------


class WorkerSettings:
    """ARQ-discoverable settings.

    `functions` and `cron_jobs` use lazy attribute access via classmethods so
    importing this module does NOT immediately import the task module — that
    matters because tasks.py pulls in Playwright, which is heavy and only the
    worker process needs it.
    """

    # Resolved lazily (see __init_subclass__-free pattern below).
    redis_settings = build_redis_settings()

    # Concurrency: how many tasks one worker process runs in parallel.
    max_jobs = get_settings().WORKER_MAX_JOBS

    # Per-task wall-clock timeout. Defensive ceiling so a stuck Playwright
    # navigation does not pin a worker slot forever.
    job_timeout = get_settings().WORKER_JOB_TIMEOUT_SECONDS

    # Keep job results around long enough for the SSE endpoint to surface them
    # if the client connects late.
    keep_result = 60 * 60 * 24  # 24h

    # ARQ writes a heartbeat key every health_check_interval seconds. The
    # docker-compose worker healthcheck reads it.
    health_check_interval = 30
    health_check_key = "arq:health-check"

    # Lifecycle hooks
    on_startup = staticmethod(on_startup)
    on_shutdown = staticmethod(on_shutdown)

    # Lazy registration: the resolver imports the tasks module on demand so
    # the API container can import this file (to enqueue jobs) without
    # eagerly loading the task functions. The tasks module itself defers
    # heavy imports (Playwright, LLM SDKs) inside each task body.
    @classmethod
    def _resolve_functions(cls) -> list[Any]:
        from app.workers import tasks

        return [
            tasks.run_discovery_task,
            tasks.run_audit_task,
            tasks.run_score_task,
            tasks.run_pitch_task,
            tasks.run_send_outreach_task,
        ]

    @classmethod
    def _resolve_cron_jobs(cls) -> list[Any]:
        from app.workers import tasks

        return [
            cron(
                tasks.reap_stale_jobs,
                # Run every minute. The reaper itself filters by
                # WORKER_STALE_JOB_THRESHOLD_SECONDS so the cadence is cheap.
                minute=set(range(0, 60, 1)),
                run_at_startup=True,
            ),
        ]


# ARQ reads `functions` and `cron_jobs` off the WorkerSettings class at worker
# boot. We resolve them once at import time so a future arq release that
# inspects them via getattr(cls, ...) sees concrete lists, not properties.
WorkerSettings.functions = WorkerSettings._resolve_functions()  # type: ignore[attr-defined]
WorkerSettings.cron_jobs = WorkerSettings._resolve_cron_jobs()  # type: ignore[attr-defined]
