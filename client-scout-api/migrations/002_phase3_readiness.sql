-- =============================================================================
-- Phase 3 readiness: gap-weight config contract and provider enum compatibility
-- =============================================================================

ALTER TYPE llm_provider ADD VALUE IF NOT EXISTS 'rule_engine';
ALTER TYPE llm_provider ADD VALUE IF NOT EXISTS 'nvidia';

ALTER TABLE niche_configs
    ADD COLUMN IF NOT EXISTS weights JSONB NOT NULL DEFAULT '{
        "weak_website": 20,
        "lead_capture_gap": 25,
        "outdated_contact": 10,
        "high_ticket": 20,
        "trust_gap": 10,
        "automation_gap": 15
    }'::jsonb;

UPDATE niche_configs
SET weights = '{
    "weak_website": 20,
    "lead_capture_gap": 25,
    "outdated_contact": 10,
    "high_ticket": 20,
    "trust_gap": 10,
    "automation_gap": 15
}'::jsonb
WHERE weights IS NULL OR weights = '{}'::jsonb;
