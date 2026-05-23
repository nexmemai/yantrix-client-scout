"""
api/jobs.py - Discovery job read APIs and live event stream.
"""

import asyncio
import json
import logging
import uuid
from math import ceil
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.business import Business
from app.models.job import DiscoveryJob
from app.models.pitch import Pitch
from app.schemas.job import JobRead
from app.workers.queue import (
    build_event,
    get_last_job_event,
    get_pubsub_redis,
    job_channel,
)

router = APIRouter(prefix="/jobs", tags=["Jobs"])
logger = logging.getLogger(__name__)

# Browsers will reconnect EventSource automatically if the connection drops.
# We send a keepalive comment every SSE_KEEPALIVE_SECONDS so intermediate
# proxies (Nginx default 60s read timeout) don't tear the stream down on idle
# jobs (e.g. pitch generation that takes 40s with no progress events).
SSE_KEEPALIVE_SECONDS = 15


@router.get("", response_model=dict, status_code=status.HTTP_200_OK)
async def list_jobs(
    status_filter: str | None = Query(None, alias="status"),
    city: str | None = Query(None),
    niche: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = []
    if status_filter:
        filters.append(DiscoveryJob.status == status_filter)
    if city:
        filters.append(func.lower(DiscoveryJob.city) == city.lower())
    if niche:
        filters.append(func.lower(DiscoveryJob.niche) == niche.lower())

    total = await db.scalar(select(func.count(DiscoveryJob.id)).where(*filters)) or 0
    result = await db.execute(
        select(DiscoveryJob)
        .where(*filters)
        .order_by(desc(DiscoveryJob.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = [await _job_to_read(db, job) for job in result.scalars().all()]
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, ceil(total / limit)) if total else 1,
        "items": items,
    }


@router.get("/{job_id}", response_model=JobRead, status_code=status.HTTP_200_OK)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> JobRead:
    result = await db.execute(select(DiscoveryJob).where(DiscoveryJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return await _job_to_read(db, job)


async def _job_to_read(db: AsyncSession, job: DiscoveryJob) -> JobRead:
    total_pitched = await db.scalar(
        select(func.count(Pitch.id))
        .join(Business, Business.id == Pitch.business_id)
        .where(Business.discovery_job_id == job.id)
    )
    return JobRead(
        id=job.id,
        query=job.query,
        city=job.city,
        source=job.source,
        niche=job.niche,
        status=job.status,
        total_discovered=job.total_discovered,
        total_audited=job.total_audited,
        total_scored=job.total_scored,
        total_pitched=total_pitched or 0,
        error_message=job.error_message,
        started_at=job.started_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        last_updated_at=job.updated_at,
        completed_at=job.completed_at,
    )




# ---------------------------------------------------------------------------
# Server-Sent Events stream for one DiscoveryJob.
#
# Why SSE instead of WebSockets:
#   - one-way (server -> client) traffic, which is exactly what we have,
#   - native EventSource support in browsers with automatic reconnection,
#   - works through plain HTTP/1.1 reverse proxies (Nginx, Cloudflare) with
#     no protocol upgrade, which keeps deployment shape simple.
#
# Auth note:
#   EventSource cannot send custom headers. The dashboard appends the shared
#   bearer token as ?token=... and we accept it as a query string OR via the
#   normal Authorization/X-Yantrix-Token headers (so curl + Bearer still
#   works for ops debugging).
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}/events",
    summary="Live SSE stream of job progress events",
    description=(
        "Subscribe to real-time progress events for a discovery job. "
        "On connect the stream emits the last known event (if any) so a "
        "client that reconnects mid-flight can render state immediately, "
        "then forwards every subsequent event published by the worker."
    ),
    responses={
        200: {"content": {"text/event-stream": {}}},
        404: {"description": "Job not found"},
    },
)
async def stream_job_events(
    job_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # Validate the job exists before we open a long-lived stream so a typo
    # in the URL fails fast with 404 rather than silently subscribing to a
    # channel that nobody will ever publish to.
    job_exists = await db.scalar(
        select(func.count(DiscoveryJob.id)).where(DiscoveryJob.id == job_id)
    )
    if not job_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    redis = await get_pubsub_redis()
    return StreamingResponse(
        _job_event_generator(job_id, request, redis),
        media_type="text/event-stream",
        headers={
            # Disable buffering at proxies so events stream byte-by-byte.
            # `X-Accel-Buffering: no` is the Nginx-specific knob; modern
            # browsers ignore the header but Nginx honours it.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _job_event_generator(
    job_id: uuid.UUID,
    request: Request,
    redis: Redis,
) -> AsyncIterator[bytes]:
    """Yield SSE-formatted bytes for one job until the client disconnects.

    Lifecycle:
      1. Send a comment line so the client transitions to OPEN immediately.
      2. Send the last cached event (if any) so a reconnecting client gets
         current state before the next live event.
      3. Subscribe to the per-job pub/sub channel and forward decoded events.
      4. Send keepalive comments every SSE_KEEPALIVE_SECONDS to defeat proxy
         idle timeouts.
      5. Tear the subscription down cleanly on cancellation/disconnect.
    """
    pubsub = redis.pubsub()
    await pubsub.subscribe(job_channel(job_id))
    try:
        # 1) Open the stream.
        yield b": connected\n\n"

        # 2) Replay the last known state for late subscribers.
        last_event = await get_last_job_event(redis, job_id)
        if last_event is not None:
            yield _format_sse(last_event)

        # 3) Live events + 4) keepalive (interleaved via asyncio.wait_for).
        while True:
            if await request.is_disconnected():
                break

            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=SSE_KEEPALIVE_SECONDS,
                )
            except asyncio.TimeoutError:
                # No event in the keepalive window: send a comment line so
                # the connection stays warm through proxies.
                yield b": keepalive\n\n"
                continue

            if message is None:
                # redis-py returns None when there's nothing to read yet;
                # loop with a tiny yield so we don't spin.
                await asyncio.sleep(0.05)
                continue
            if message.get("type") != "message":
                continue

            raw = message.get("data")
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[SSE] dropped malformed event for job %s", job_id)
                continue

            yield _format_sse(payload)

            # Terminal states: close the stream cleanly so the dashboard
            # stops listening rather than reconnecting forever.
            if payload.get("type") in {"job_completed", "job_failed"}:
                break

    except asyncio.CancelledError:
        # FastAPI cancels the generator when the client disconnects.
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("[SSE] stream for job %s aborted: %s", job_id, exc)
        # Tell the client about the failure before closing so the toast layer
        # can surface it. EventSource will then auto-reconnect.
        try:
            yield _format_sse(
                build_event(
                    job_id,
                    "stream_error",
                    stage="pipeline",
                    data={"error": str(exc)[:200]},
                )
            )
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await pubsub.unsubscribe(job_channel(job_id))
            await pubsub.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[SSE] pubsub teardown for job %s: %s", job_id, exc)


def _format_sse(payload: dict) -> bytes:
    """Encode a JSON event into the SSE wire format.

    `event:` lets the client install per-type listeners (e.g.
    `source.addEventListener('job_completed', ...)`). Falling back to the
    generic `message` event is fine; we still set `event:` for clarity.
    """
    event_type = str(payload.get("type", "message"))
    data = json.dumps(payload, separators=(",", ":"))
    return f"event: {event_type}\ndata: {data}\n\n".encode("utf-8")
