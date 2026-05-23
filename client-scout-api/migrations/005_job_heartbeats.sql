-- =============================================================================
-- 005_job_heartbeats.sql
--
-- Adds liveness tracking to discovery_jobs so a separate orphan reaper can
-- mark jobs as `failed` when the worker that owned them dies (OOM, deploy,
-- container kill, etc). Without these columns the previous in-process
-- BackgroundTasks design left jobs stuck at status='running' forever.
--
-- Column meaning:
--   last_heartbeat - UTC timestamp updated by the worker every
--                    WORKER_HEARTBEAT_INTERVAL_SECONDS while the task runs.
--   worker_id      - hostname:job_try string identifying which worker replica
--                    is processing the job. Useful for log correlation.
--   attempts       - 1-based counter incremented when ARQ retries a task.
-- =============================================================================

ALTER TABLE discovery_jobs
    ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS worker_id      TEXT,
    ADD COLUMN IF NOT EXISTS attempts       INTEGER NOT NULL DEFAULT 0;

-- The reaper query is: WHERE status='running' AND last_heartbeat < now() - interval.
-- A partial index on running jobs keeps that scan O(running_jobs).
CREATE INDEX IF NOT EXISTS ix_discovery_jobs_running_heartbeat
    ON discovery_jobs (last_heartbeat)
    WHERE status = 'running';
