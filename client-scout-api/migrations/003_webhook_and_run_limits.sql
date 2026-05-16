-- =============================================================================
-- Webhook sync metadata and run-scout safety tuning
-- =============================================================================

ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS webhook_url TEXT,
    ADD COLUMN IF NOT EXISTS last_sync_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_sync_status VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_businesses_last_sync_at
    ON businesses (last_sync_at DESC);
