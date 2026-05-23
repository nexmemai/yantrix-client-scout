"""
workers/queue.py - ARQ pool and pub/sub helpers shared by the API container.

The API container does NOT execute jobs. It uses these helpers to:

  * enqueue work onto the Redis-backed ARQ queue (so a worker replica picks
    it up), and
  * publish progress events on a per-job pub/sub channel that the SSE
    endpoint streams to the dashboard.

Both the pool and the pub/sub Redis client are lazily constructed and reused
across requests; FastAPI's lifespan owns their teardown.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from arq import create_pool
from arq.connections import ArqRedis
from redis.asyncio import Redis

from app.config import get_settings
from app.workers.arq_worker import build_redis_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Channel naming - kept in one place so worker tasks and the SSE endpoint
# never disagree on the wire format.
# ---------------------------------------------------------------------------


def job_channel(job_id: uuid.UUID | str) -> str:
    """Redis pub/sub channel name carrying events for one discovery job."""
    return f"job:{job_id}"


def job_state_key(job_id: uuid.UUID | str) -> str:
    """Redis key holding the last-known event payload for late SSE subscribers."""
    return f"job:{job_id}:last_event"


# ---------------------------------------------------------------------------
# Module-level singletons (per-process). Not thread-safe, but FastAPI runs on
# a single asyncio loop per worker so this is safe in our deployment.
# ---------------------------------------------------------------------------

_arq_pool: ArqRedis | None = None
_pubsub_redis: Redis | None = None


async def get_arq_pool() -> ArqRedis:
    """Return a process-wide ARQ pool, creating it on first use.

    Use as a FastAPI dependency:

        @router.post(...)
        async def ep(pool: ArqRedis = Depends(get_arq_pool)): ...
    """
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(build_redis_settings())
        logger.info("[QUEUE] ARQ pool created url=%s", get_settings().REDIS_URL)
    return _arq_pool


async def get_pubsub_redis() -> Redis:
    """Return a process-wide redis-py async client for pub/sub + state reads.

    A separate connection from the ARQ pool because pub/sub clients enter a
    blocking SUBSCRIBE loop that cannot be shared with command traffic.
    """
    global _pubsub_redis
    if _pubsub_redis is None:
        _pubsub_redis = Redis.from_url(
            get_settings().REDIS_URL,
            decode_responses=True,
            health_check_interval=30,
        )
        logger.info("[QUEUE] pub/sub redis client created")
    return _pubsub_redis


async def close_queue_clients() -> None:
    """Tear down both clients on application shutdown."""
    global _arq_pool, _pubsub_redis
    if _arq_pool is not None:
        try:
            await _arq_pool.close(close_connection_pool=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QUEUE] ARQ pool close failed: %s", exc)
        _arq_pool = None
    if _pubsub_redis is not None:
        try:
            await _pubsub_redis.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QUEUE] pub/sub redis close failed: %s", exc)
        _pubsub_redis = None


# ---------------------------------------------------------------------------
# Event publishing - called from BOTH the API (on enqueue) and the worker
# tasks (on stage transitions). Centralised so the wire format stays stable.
# ---------------------------------------------------------------------------


def build_event(
    job_id: uuid.UUID | str,
    event_type: str,
    *,
    stage: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct the canonical SSE event envelope.

    Wire format (kept tight on purpose so it's easy to evolve):
      {
        "type":   "stage_started" | "stage_progress" | "stage_completed"
                | "job_queued"    | "job_completed"  | "job_failed",
        "job_id": "<uuid>",
        "stage":  "discovery" | "audit" | "score" | "pitch" | None,
        "data":   { ...stage-specific, free-form... },
        "ts":     "2025-05-23T12:34:56.789012+00:00"
      }
    """
    return {
        "type": event_type,
        "job_id": str(job_id),
        "stage": stage,
        "data": data or {},
        "ts": datetime.now(tz=timezone.utc).isoformat(),
    }


async def publish_job_event(
    redis: Redis | ArqRedis,
    job_id: uuid.UUID | str,
    event_type: str,
    *,
    stage: str | None = None,
    data: dict[str, Any] | None = None,
    state_ttl_seconds: int = 60 * 60 * 24,
) -> dict[str, Any]:
    """Publish an event AND store it as the job's last-known state.

    Storing the last event under `job:{id}:last_event` lets a dashboard that
    connects mid-flight render the current state immediately, before the
    next live event arrives. TTL keeps Redis lean - completed-job state
    expires after a day, which is well past dashboard staleness.
    """
    payload = build_event(job_id, event_type, stage=stage, data=data)
    encoded = json.dumps(payload, default=_json_default)
    channel = job_channel(job_id)
    state_key = job_state_key(job_id)

    try:
        # Pipeline keeps the publish + cache write atomic from the
        # subscriber's perspective: a late SSE reader either gets the new
        # state via PUBLISH or via GET, never a mismatched pair.
        async with redis.pipeline(transaction=False) as pipe:  # type: ignore[attr-defined]
            pipe.publish(channel, encoded)
            pipe.set(state_key, encoded, ex=state_ttl_seconds)
            await pipe.execute()
    except Exception as exc:  # noqa: BLE001 - publishing must never crash a task
        logger.warning(
            "[QUEUE] publish_job_event failed job=%s type=%s: %s",
            job_id,
            event_type,
            exc,
        )
    return payload


async def get_last_job_event(
    redis: Redis,
    job_id: uuid.UUID | str,
) -> dict[str, Any] | None:
    """Read the most recent event for a job (used by SSE on connect)."""
    raw = await redis.get(job_state_key(job_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[QUEUE] last_event for %s was not valid JSON", job_id)
        return None


async def subscribe_job_events(
    redis: Redis,
    job_id: uuid.UUID | str,
) -> AsyncIterator[dict[str, Any]]:
    """Async iterator yielding decoded events for a job's pub/sub channel.

    Caller is responsible for closing the underlying pubsub object - we yield
    via a context manager pattern so cancellation closes the subscription
    cleanly even if the SSE client disconnects mid-stream.
    """
    pubsub = redis.pubsub()
    await pubsub.subscribe(job_channel(job_id))
    try:
        async for message in pubsub.listen():
            if not message or message.get("type") != "message":
                continue
            raw = message.get("data")
            if raw is None:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[QUEUE] dropped malformed event for job %s", job_id)
                continue
    finally:
        try:
            await pubsub.unsubscribe(job_channel(job_id))
            await pubsub.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[QUEUE] pubsub teardown error: %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _json_default(value: Any) -> Any:
    """JSON encoder for UUIDs and datetimes, which the rest of the app uses."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
