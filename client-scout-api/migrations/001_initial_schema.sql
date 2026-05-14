-- =============================================================================
-- Yantrix Client Scout — Full Postgres Schema
-- Compatible with: Supabase, SQLAlchemy 2.0 (async), asyncpg
-- Convention: snake_case columns, UUID PKs, timestamptz everywhere
-- Run order matters: discovery_jobs → businesses → audits → scores → pitches
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for fuzzy name search later

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

CREATE TYPE business_source AS ENUM (
    'google_maps',
    'justdial',
    'csv',
    'manual'
);

CREATE TYPE job_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed',
    'cancelled'
);

CREATE TYPE audit_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed',
    'skipped'
);

CREATE TYPE llm_provider AS ENUM (
    'groq',
    'nvidia_nim',
    'openai'  -- reserved for future use
);

CREATE TYPE lead_stage AS ENUM (
    'new',
    'qualified',
    'contacted',
    'converted',
    'rejected'
);

-- =============================================================================
-- TABLE: discovery_jobs
-- Tracks a single "run-scout" pipeline execution
-- =============================================================================

CREATE TABLE discovery_jobs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query               TEXT NOT NULL,                      -- e.g. "dental clinics in Pune"
    city                VARCHAR(100),
    niche               VARCHAR(100),
    source              business_source NOT NULL DEFAULT 'google_maps',
    status              job_status NOT NULL DEFAULT 'pending',
    total_discovered    INTEGER NOT NULL DEFAULT 0,
    total_audited       INTEGER NOT NULL DEFAULT 0,
    total_scored        INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Useful for polling the status of recent jobs
CREATE INDEX idx_jobs_status_created ON discovery_jobs (status, created_at DESC);
CREATE INDEX idx_jobs_niche_city     ON discovery_jobs (niche, city);

-- =============================================================================
-- TABLE: businesses
-- Core lead entity. Unique on (name, city, address) to prevent duplicates.
-- =============================================================================

CREATE TABLE businesses (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(255) NOT NULL,
    category            VARCHAR(100),
    niche               VARCHAR(100),                       -- e.g. "dental", "salon", "real_estate"
    address             TEXT,
    city                VARCHAR(100),
    state               VARCHAR(100),
    country             VARCHAR(50) NOT NULL DEFAULT 'India',
    phone               VARCHAR(50),
    email               VARCHAR(255),
    website_url         TEXT,
    google_maps_url     TEXT,
    rating              NUMERIC(2, 1) CHECK (rating >= 0 AND rating <= 5),
    review_count        INTEGER CHECK (review_count >= 0),
    source              business_source NOT NULL DEFAULT 'google_maps',
    stage               lead_stage NOT NULL DEFAULT 'new',
    discovery_job_id    UUID REFERENCES discovery_jobs (id) ON DELETE SET NULL,
    raw_data            JSONB,                              -- full scraper payload for reprocessing
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Prevent duplicate ingestion from the same source
    CONSTRAINT uq_business_identity UNIQUE (name, city, address)
);

-- Most common query pattern: filter by niche + city for a scout run
CREATE INDEX idx_businesses_niche_city     ON businesses (niche, city);
-- Dashboard: sort by most recent
CREATE INDEX idx_businesses_created        ON businesses (created_at DESC);
-- Filter by stage (e.g., show only 'qualified' leads)
CREATE INDEX idx_businesses_stage          ON businesses (stage);
-- FK lookup
CREATE INDEX idx_businesses_job_id         ON businesses (discovery_job_id);
-- Trigram index for fuzzy search by business name
CREATE INDEX idx_businesses_name_trgm      ON businesses USING gin (name gin_trgm_ops);

-- =============================================================================
-- TABLE: audits
-- Website audit results. 1:1 with businesses.
-- =============================================================================

CREATE TABLE audits (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id         UUID NOT NULL UNIQUE REFERENCES businesses (id) ON DELETE CASCADE,
    url_checked         TEXT,

    -- Binary presence checks
    has_website         BOOLEAN NOT NULL DEFAULT FALSE,
    ssl_valid           BOOLEAN NOT NULL DEFAULT FALSE,
    mobile_friendly     BOOLEAN NOT NULL DEFAULT FALSE,

    -- Conversion feature checks (used in scoring weights)
    has_forms           BOOLEAN NOT NULL DEFAULT FALSE,
    has_cta             BOOLEAN NOT NULL DEFAULT FALSE,
    has_whatsapp        BOOLEAN NOT NULL DEFAULT FALSE,
    has_booking         BOOLEAN NOT NULL DEFAULT FALSE,
    has_chatbot         BOOLEAN NOT NULL DEFAULT FALSE,

    -- Performance
    load_time_ms        INTEGER CHECK (load_time_ms >= 0),
    page_speed_score    SMALLINT CHECK (page_speed_score BETWEEN 0 AND 100),  -- from Google PSI

    -- SEO basics
    has_title           BOOLEAN NOT NULL DEFAULT FALSE,
    has_meta_desc       BOOLEAN NOT NULL DEFAULT FALSE,
    has_h1              BOOLEAN NOT NULL DEFAULT FALSE,
    has_og_tags         BOOLEAN NOT NULL DEFAULT FALSE,

    -- Social presence
    has_facebook        BOOLEAN NOT NULL DEFAULT FALSE,
    has_instagram       BOOLEAN NOT NULL DEFAULT FALSE,
    has_linkedin        BOOLEAN NOT NULL DEFAULT FALSE,
    has_twitter         BOOLEAN NOT NULL DEFAULT FALSE,

    -- Detected tech stack (Wix, Shopify, WordPress, etc.)
    tech_stack          TEXT[],

    -- Artifacts
    screenshot_url      TEXT,
    raw_html_hash       CHAR(64),                           -- SHA-256 of fetched HTML

    -- Job metadata
    status              audit_status NOT NULL DEFAULT 'pending',
    error_message       TEXT,
    audited_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Quick lookup of audit by business
CREATE INDEX idx_audits_business_id        ON audits (business_id);
-- Filter audits that need reprocessing
CREATE INDEX idx_audits_status             ON audits (status);

-- =============================================================================
-- TABLE: niche_configs
-- Per-niche scoring weight configuration. Replaces scoring_configs.
-- "dental" and "salon" will have different weights for has_booking vs. has_whatsapp.
-- =============================================================================

CREATE TABLE niche_configs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    niche               VARCHAR(100) NOT NULL UNIQUE,       -- e.g. "dental", "salon", "_default"
    display_name        VARCHAR(150),                       -- Human readable: "Dental Clinics"

    -- Scoring weights (must sum to ~100, validated in application layer)
    weight_website      SMALLINT NOT NULL DEFAULT 20 CHECK (weight_website BETWEEN 0 AND 100),
    weight_mobile       SMALLINT NOT NULL DEFAULT 15 CHECK (weight_mobile BETWEEN 0 AND 100),
    weight_forms        SMALLINT NOT NULL DEFAULT 15 CHECK (weight_forms BETWEEN 0 AND 100),
    weight_whatsapp     SMALLINT NOT NULL DEFAULT 10 CHECK (weight_whatsapp BETWEEN 0 AND 100),
    weight_booking      SMALLINT NOT NULL DEFAULT 20 CHECK (weight_booking BETWEEN 0 AND 100),
    weight_social       SMALLINT NOT NULL DEFAULT 10 CHECK (weight_social BETWEEN 0 AND 100),
    weight_seo          SMALLINT NOT NULL DEFAULT 10 CHECK (weight_seo BETWEEN 0 AND 100),

    -- LLM prompt customisation per niche
    prompt_template     TEXT,

    is_default          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed the fallback config
INSERT INTO niche_configs (niche, display_name, is_default)
VALUES ('_default', 'Default (All Niches)', TRUE);

-- =============================================================================
-- TABLE: scores
-- LLM-generated composite score and sub-scores. 1:1 with businesses.
-- =============================================================================

CREATE TABLE scores (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id             UUID NOT NULL UNIQUE REFERENCES businesses (id) ON DELETE CASCADE,
    audit_id                UUID REFERENCES audits (id) ON DELETE SET NULL,
    niche_config_id         UUID REFERENCES niche_configs (id) ON DELETE SET NULL,

    -- Composite (0-100)
    overall_score           SMALLINT NOT NULL CHECK (overall_score BETWEEN 0 AND 100),

    -- Sub-scores (0-100 each)
    website_quality         SMALLINT CHECK (website_quality BETWEEN 0 AND 100),
    online_presence         SMALLINT CHECK (online_presence BETWEEN 0 AND 100),
    conversion_readiness    SMALLINT CHECK (conversion_readiness BETWEEN 0 AND 100),
    urgency                 SMALLINT CHECK (urgency BETWEEN 0 AND 100),

    -- Score band for fast bucketed filtering (A/B/C/D)
    score_band              CHAR(1) GENERATED ALWAYS AS (
        CASE
            WHEN overall_score >= 75 THEN 'A'
            WHEN overall_score >= 50 THEN 'B'
            WHEN overall_score >= 25 THEN 'C'
            ELSE                          'D'
        END
    ) STORED,

    -- Provider metadata
    llm_provider            llm_provider,
    llm_model               VARCHAR(100),
    tokens_used             INTEGER CHECK (tokens_used >= 0),

    scored_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fastest query: "show me all A-band leads in descending score order"
CREATE INDEX idx_scores_band_overall       ON scores (score_band, overall_score DESC);
-- Lookup by business
CREATE INDEX idx_scores_business_id        ON scores (business_id);
-- Filter by overall threshold
CREATE INDEX idx_scores_overall            ON scores (overall_score DESC);

-- =============================================================================
-- TABLE: pitches
-- AI-generated outreach pitch per business. Separated from scores so we can
-- regenerate pitches independently (e.g. for a new campaign tone).
-- =============================================================================

CREATE TABLE pitches (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id             UUID NOT NULL REFERENCES businesses (id) ON DELETE CASCADE,
    score_id                UUID REFERENCES scores (id) ON DELETE SET NULL,

    -- Generated content
    pitch_notes             TEXT NOT NULL,                  -- markdown bullet points
    recommended_services    TEXT[],                         -- e.g. ["WhatsApp Bot", "SEO Audit"]
    objection_handlers      TEXT,                           -- markdown: how to handle pushback
    subject_line            VARCHAR(255),                   -- for email outreach

    -- Tone / campaign context
    tone                    VARCHAR(50) DEFAULT 'professional',  -- professional | friendly | urgent
    language                VARCHAR(10) DEFAULT 'en',

    -- Provider metadata
    llm_provider            llm_provider,
    llm_model               VARCHAR(100),
    tokens_used             INTEGER CHECK (tokens_used >= 0),
    prompt_version          VARCHAR(20),                    -- tracks which prompt template was used

    -- CRM sync status
    exported_to_hubspot     BOOLEAN NOT NULL DEFAULT FALSE,
    exported_to_zoho        BOOLEAN NOT NULL DEFAULT FALSE,
    exported_at             TIMESTAMPTZ,

    generated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Allow multiple pitch versions per business (different tones / campaigns)
-- Most recent pitch per business is primary use case
CREATE INDEX idx_pitches_business_id       ON pitches (business_id, generated_at DESC);
-- Find all un-exported pitches for a CRM push job
CREATE INDEX idx_pitches_hubspot_export    ON pitches (exported_to_hubspot, generated_at DESC);
CREATE INDEX idx_pitches_zoho_export       ON pitches (exported_to_zoho, generated_at DESC);

-- =============================================================================
-- TRIGGERS: auto-update updated_at timestamps
-- =============================================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_businesses_updated_at
    BEFORE UPDATE ON businesses
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON discovery_jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_niche_configs_updated_at
    BEFORE UPDATE ON niche_configs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- VIEWS: convenience for Supabase dashboard / REST layer
-- =============================================================================

-- Full lead card: join businesses + scores + latest pitch
CREATE OR REPLACE VIEW lead_cards AS
SELECT
    b.id,
    b.name,
    b.niche,
    b.city,
    b.state,
    b.phone,
    b.email,
    b.website_url,
    b.rating,
    b.review_count,
    b.stage,
    b.source,
    s.overall_score,
    s.score_band,
    s.website_quality,
    s.online_presence,
    s.conversion_readiness,
    s.urgency,
    p.pitch_notes,
    p.recommended_services,
    p.subject_line,
    p.exported_to_hubspot,
    p.exported_to_zoho,
    b.created_at
FROM businesses b
LEFT JOIN scores  s ON s.business_id = b.id
LEFT JOIN LATERAL (
    SELECT * FROM pitches
    WHERE business_id = b.id
    ORDER BY generated_at DESC
    LIMIT 1
) p ON TRUE;

COMMENT ON VIEW lead_cards IS 'Full lead view joining businesses, scores, and most recent pitch. Used by dashboard and CRM export.';
