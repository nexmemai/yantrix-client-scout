"""ARQ worker package.

Exposes the WorkerSettings ARQ entrypoint and shared queue helpers used by
both the API container (to enqueue jobs and publish SSE events) and the
worker container (to execute background tasks).
"""
