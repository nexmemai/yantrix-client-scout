-- =============================================================================
-- 006_dynamic_niches.sql
--
-- Unblocks free-text niche search. The hardcoded VALID_NICHES allow-list in
-- app/api/run_scout.py is being replaced by a DB-backed resolver
-- (app/services/niche_resolver.py) that reads these columns to choose a
-- search phrase for the gosom Google Maps scraper.
--
-- Columns added:
--   search_phrase  - Natural-language phrase fed to gosom verbatim, e.g.
--                    "EV charging stations". When NULL the resolver falls
--                    back to the built-in catalog or a generic plural.
--   display_name   - Human-friendly label shown in the dashboard. Already
--                    present in the model; the migration adds a default
--                    only if the column is missing on older databases.
--   is_enabled     - Soft-disable a niche without deleting its scoring
--                    config. The resolver ignores rows where this is FALSE.
--   aliases        - Free-text aliases that route to the same canonical
--                    niche key. Indexed via GIN so the resolver can match
--                    "EV chargers" -> ev_charging.
--
-- Backwards compatibility:
--   * is_default and the existing weight columns are unchanged.
--   * Existing rows are migrated to is_enabled = TRUE so nothing disappears.
--   * NULL search_phrase preserves legacy behaviour for rows that already
--     work via the built-in catalog (dental, salon, real_estate, ...).
-- =============================================================================

ALTER TABLE niche_configs
    ADD COLUMN IF NOT EXISTS search_phrase TEXT,
    ADD COLUMN IF NOT EXISTS display_name  TEXT,
    ADD COLUMN IF NOT EXISTS is_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS aliases       TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

-- Cheap partial index: the resolver's hot path filters by is_enabled.
CREATE INDEX IF NOT EXISTS ix_niche_configs_enabled
    ON niche_configs (niche)
    WHERE is_enabled;

-- GIN index on aliases for "alias -> canonical key" lookups. Without this an
-- alias query would seq-scan; with it Postgres uses the inverted index even
-- on a few thousand rows.
CREATE INDEX IF NOT EXISTS ix_niche_configs_aliases_gin
    ON niche_configs USING GIN (aliases);
