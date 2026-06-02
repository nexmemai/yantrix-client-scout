"""
workers/redis_settings.py - Tiny helper: build ARQ RedisSettings from REDIS_URL.

Kept in its own module so *both* queue.py (API container) and arq_worker.py
(worker container) can import it without pulling each other's dependencies in.

Import graph after this split:
  queue.py      ← redis_settings.py   (no tasks, no arq_worker)
  arq_worker.py ← redis_settings.py   (no queue, no circular risk)
"""

from __future__ import annotations

from arq.connections import RedisSettings

from app.config import get_settings


def build_redis_settings() -> RedisSettings:
    """Parse REDIS_URL into the structured form ARQ expects."""
    return RedisSettings.from_dsn(get_settings().REDIS_URL)
