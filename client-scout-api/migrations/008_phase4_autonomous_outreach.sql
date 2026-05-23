-- =============================================================================
-- 008_phase4_autonomous_outreach.sql
--
-- Phase 4 - Autonomous Outreach.
--
-- Adds the persistence layer required for the worker to send pitches over
-- email and WhatsApp on the operator's behalf, and for the dashboard to
-- render a per-lead Communication Log.
--
-- Two surfaces:
--   1. businesses.* gains denormalised summary columns
--      (email_sent_at, whatsapp_sent_at, outreach_status, last_outreach_error)
--      so list views and Kanban cards can show "Sent" / "Failed" badges
--      without joining the new attempts table.
--   2. outreach_attempts is the immutable log of every send the worker
--      attempts. One row per channel per attempt - retries append rather
--      than mutate. Powers the timeline on /leads/{id}/outreach.
--
-- Why a separate table (vs. JSONB on businesses):
--   * Multiple channels (email + WhatsApp + future SMS) per lead.
--   * Each attempt has its own status / error / timestamp / provider
--     message id for traceability.
--   * GIN-indexed JSONB would still need fan-out queries for the timeline;
--     a real table keeps the SSE worker writes O(insert) and gives us
--     proper FK + cascade semantics.
--
-- Backwards compatibility:
--   * outreach_status defaults to 'idle' so existing rows render as
--     "Not yet contacted" in the UI.
--   * All new columns are NULL-tolerant. Auto-send is OFF by default in
--     run_scout; existing manual workflows are untouched.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Businesses: summary columns surfaced on list views and badges.
--
-- outreach_status canonical values (kept in sync with
--   app.services.outreach_sender.OutreachStatus):
--     'idle'    - never attempted (default)
--     'pending' - enqueued; no provider response yet
--     'sent'    - at least one channel succeeded; no failures since
--     'partial' - one channel sent, the other failed
--     'failed'  - all channels failed on the latest attempt
--     'skipped' - auto-send was enabled but the lead lacked a contact
--                 channel (no email AND no phone)
-- -----------------------------------------------------------------------------
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS email_sent_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS whatsapp_sent_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS outreach_status      VARCHAR(20) NOT NULL DEFAULT 'idle',
    ADD COLUMN IF NOT EXISTS last_outreach_error  TEXT,
    ADD COLUMN IF NOT EXISTS last_outreach_at     TIMESTAMPTZ;

-- The Kanban "stale" / "follow-ups" columns will eventually filter by
-- outreach_status, so a btree index keeps that O(log n).
CREATE INDEX IF NOT EXISTS idx_businesses_outreach_status
    ON businesses (outreach_status);

-- last_outreach_at lets the dashboard sort "recently auto-contacted" leads
-- to the top of the Communication Log section without scanning attempts.
CREATE INDEX IF NOT EXISTS idx_businesses_last_outreach_at
    ON businesses (last_outreach_at);

-- Idempotent CHECK constraint on outreach_status. Lifted into a DO block so
-- re-running the migration on an already-bootstrapped DB is a no-op.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_business_outreach_status'
    ) THEN
        ALTER TABLE businesses
            ADD CONSTRAINT chk_business_outreach_status
            CHECK (
                outreach_status IN (
                    'idle',
                    'pending',
                    'sent',
                    'partial',
                    'failed',
                    'skipped'
                )
            );
    END IF;
END $$;


-- -----------------------------------------------------------------------------
-- outreach_attempts: append-only log.
--
-- Schema decisions:
--   * channel is an enum-like VARCHAR with CHECK; cheap to evolve when we
--     add SMS or LinkedIn vs. a Postgres ENUM type.
--   * status carries the same lifecycle as businesses.outreach_status
--     except 'idle' (an attempt by definition is not idle).
--   * provider records WHICH backend handled the send so a switch from
--     SMTP -> SES -> Resend can be debugged from the row.
--   * provider_message_id is the upstream id (SMTP message-id header,
--     WhatsApp Cloud API message id) so support can correlate bounces.
--   * payload_subject / payload_body are persisted exactly as sent. We do
--     NOT recompute from the latest pitch when rendering the timeline -
--     the historical record is the truth.
--   * pitch_id FK is SET NULL on delete so regenerating a pitch never
--     wipes the audit trail.
--   * job_id FK lets you trace "which scout run sent this" for ops.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outreach_attempts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id         UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    pitch_id            UUID REFERENCES pitches(id) ON DELETE SET NULL,
    job_id              UUID REFERENCES discovery_jobs(id) ON DELETE SET NULL,

    channel             VARCHAR(20) NOT NULL,
    status              VARCHAR(20) NOT NULL,
    provider            VARCHAR(40),
    provider_message_id TEXT,

    -- Recipient as actually used (email address or normalised phone digits).
    -- Stored separately from businesses.* because the lead row may change
    -- over time (re-enriched contact email) and we want the historical
    -- record of "where did we send this".
    recipient           TEXT,

    -- The exact copy sent. Subject only applies to email; nullable so
    -- WhatsApp rows don't carry empty values.
    payload_subject     TEXT,
    payload_body        TEXT,

    error_message       TEXT,
    is_dry_run          BOOLEAN NOT NULL DEFAULT FALSE,

    attempted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

-- Index choices:
--   - (business_id, attempted_at DESC) supports the timeline query used
--     by GET /leads/{id}/outreach. Composite + DESC matches the ORDER BY
--     so Postgres can stream rows without a sort step.
--   - (job_id) helps the eventual "this scout run failed for N leads"
--     ops view; cheap to maintain.
--   - (status) is a partial-friendly column; we'll filter by 'failed' on
--     dashboards but most rows are 'sent', so a plain btree is fine.
CREATE INDEX IF NOT EXISTS idx_outreach_attempts_business_attempted
    ON outreach_attempts (business_id, attempted_at DESC);

CREATE INDEX IF NOT EXISTS idx_outreach_attempts_job_id
    ON outreach_attempts (job_id);

CREATE INDEX IF NOT EXISTS idx_outreach_attempts_status
    ON outreach_attempts (status);


-- Idempotent CHECK constraints for outreach_attempts.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_outreach_attempt_channel'
    ) THEN
        ALTER TABLE outreach_attempts
            ADD CONSTRAINT chk_outreach_attempt_channel
            CHECK (channel IN ('email', 'whatsapp', 'sms'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_outreach_attempt_status'
    ) THEN
        ALTER TABLE outreach_attempts
            ADD CONSTRAINT chk_outreach_attempt_status
            CHECK (
                status IN (
                    'pending',
                    'sent',
                    'failed',
                    'skipped'
                )
            );
    END IF;
END $$;
