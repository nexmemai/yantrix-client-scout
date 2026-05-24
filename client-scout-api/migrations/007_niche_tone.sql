-- =============================================================================
-- 007_niche_tone.sql
--
-- Adds niche-level pitch tone so the LLM speaks differently to different
-- industries without the operator picking from a dropdown each time.
--
-- Rationale:
--   * "Law firms" should default to a calm, professional tone.
--   * "CrossFit gyms" should default to a friendly / direct tone.
--   * The dashboard should not require a per-run choice; the system reads
--     the tone from the niche config row matched by the resolver.
--
-- Behaviour:
--   * NULL means "use system default" (DEFAULT_TONE in pitch_generator.py).
--   * The resolver returns the tone alongside the search phrase so
--     run_scout / run_pitch_task pick it up without an extra round-trip.
--   * A CHECK constraint pins the allowed values so a rogue manual UPDATE
--     cannot smuggle in an unsupported tone the LLM has no directive for.
-- =============================================================================

ALTER TABLE niche_configs
    ADD COLUMN IF NOT EXISTS pitch_tone VARCHAR(20);

ALTER TABLE niche_configs
    DROP CONSTRAINT IF EXISTS chk_niche_configs_pitch_tone;

ALTER TABLE niche_configs
    ADD CONSTRAINT chk_niche_configs_pitch_tone
    CHECK (
        pitch_tone IS NULL
        OR pitch_tone IN ('professional', 'friendly', 'urgent', 'consultative')
    );

-- Seed sensible defaults for the legacy 15 niches. Operators can override
-- via PUT /api/v1/configs/{niche} at any time.
UPDATE niche_configs SET pitch_tone = 'professional'
    WHERE pitch_tone IS NULL
      AND niche IN ('lawyer', 'ca', 'physiotherapy', 'clinic', 'dental',
                    'optician', 'veterinary', 'pharmacy');

UPDATE niche_configs SET pitch_tone = 'friendly'
    WHERE pitch_tone IS NULL
      AND niche IN ('salon', 'spa', 'gym', 'restaurant', 'hotel', 'coaching');

UPDATE niche_configs SET pitch_tone = 'consultative'
    WHERE pitch_tone IS NULL
      AND niche IN ('real_estate');
