-- =============================================================================
-- Smart Lead Engine additive fields
-- Adds contact enrichment, reliability, mini-CRM, pain flags, and agency-fit
-- scoring columns without changing existing routes or required data.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Businesses: person-level contact enrichment
-- -----------------------------------------------------------------------------
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS contact_name TEXT,
    ADD COLUMN IF NOT EXISTS contact_title TEXT,
    ADD COLUMN IF NOT EXISTS contact_email TEXT,
    ADD COLUMN IF NOT EXISTS contact_phone TEXT,
    ADD COLUMN IF NOT EXISTS contact_linkedin_url TEXT,
    ADD COLUMN IF NOT EXISTS contact_confidence INTEGER;

-- -----------------------------------------------------------------------------
-- Businesses: ability-to-pay and reliability signals
-- -----------------------------------------------------------------------------
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS primary_language VARCHAR(20),
    ADD COLUMN IF NOT EXISTS domain_age_years NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS has_recent_updates BOOLEAN,
    ADD COLUMN IF NOT EXISTS budget_tier VARCHAR(20),
    ADD COLUMN IF NOT EXISTS reliability VARCHAR(20);

-- -----------------------------------------------------------------------------
-- Businesses: lightweight sales workflow / mini-CRM fields
-- -----------------------------------------------------------------------------
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS lead_status VARCHAR(30) NOT NULL DEFAULT 'new',
    ADD COLUMN IF NOT EXISTS follow_up_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_contacted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS contact_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sales_notes TEXT,
    ADD COLUMN IF NOT EXISTS priority_rank INTEGER,
    ADD COLUMN IF NOT EXISTS assigned_to TEXT;

CREATE INDEX IF NOT EXISTS idx_businesses_lead_status
    ON businesses (lead_status);

CREATE INDEX IF NOT EXISTS idx_businesses_follow_up_at
    ON businesses (follow_up_at);

CREATE INDEX IF NOT EXISTS idx_businesses_priority_rank
    ON businesses (priority_rank);

CREATE INDEX IF NOT EXISTS idx_businesses_budget_reliability
    ON businesses (budget_tier, reliability);

-- -----------------------------------------------------------------------------
-- Audits: structured pain flags and first-class CMS detection
-- Existing audit booleans remain the source of truth; pain_flags is derived.
-- -----------------------------------------------------------------------------
ALTER TABLE audits
    ADD COLUMN IF NOT EXISTS pain_flags JSONB,
    ADD COLUMN IF NOT EXISTS cms_detected VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_audits_pain_flags
    ON audits USING GIN (pain_flags);

CREATE INDEX IF NOT EXISTS idx_audits_cms_detected
    ON audits (cms_detected);

-- -----------------------------------------------------------------------------
-- Scores: agency-fit layer added on top of the existing score model
-- -----------------------------------------------------------------------------
ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS agency_fit_score INTEGER,
    ADD COLUMN IF NOT EXISTS agency_fit_bucket VARCHAR(20),
    ADD COLUMN IF NOT EXISTS opportunity_types TEXT[],
    ADD COLUMN IF NOT EXISTS estimated_deal_value INTEGER;

CREATE INDEX IF NOT EXISTS idx_scores_agency_fit_bucket
    ON scores (agency_fit_bucket);

CREATE INDEX IF NOT EXISTS idx_scores_agency_fit_score
    ON scores (agency_fit_score DESC);

CREATE INDEX IF NOT EXISTS idx_scores_opportunity_types
    ON scores USING GIN (opportunity_types);

-- -----------------------------------------------------------------------------
-- Idempotent check constraints
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_business_contact_confidence'
    ) THEN
        ALTER TABLE businesses
            ADD CONSTRAINT chk_business_contact_confidence
            CHECK (contact_confidence IS NULL OR contact_confidence BETWEEN 0 AND 100);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_business_contact_attempts'
    ) THEN
        ALTER TABLE businesses
            ADD CONSTRAINT chk_business_contact_attempts
            CHECK (contact_attempts >= 0);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_business_lead_status'
    ) THEN
        ALTER TABLE businesses
            ADD CONSTRAINT chk_business_lead_status
            CHECK (
                lead_status IN (
                    'new',
                    'contacted',
                    'replied',
                    'meeting_set',
                    'proposal_sent',
                    'won',
                    'lost',
                    'ignored'
                )
            );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_business_budget_tier'
    ) THEN
        ALTER TABLE businesses
            ADD CONSTRAINT chk_business_budget_tier
            CHECK (budget_tier IS NULL OR budget_tier IN ('low', 'medium', 'high'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_business_reliability'
    ) THEN
        ALTER TABLE businesses
            ADD CONSTRAINT chk_business_reliability
            CHECK (reliability IS NULL OR reliability IN ('low', 'medium', 'high'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_score_agency_fit_score'
    ) THEN
        ALTER TABLE scores
            ADD CONSTRAINT chk_score_agency_fit_score
            CHECK (agency_fit_score IS NULL OR agency_fit_score BETWEEN 0 AND 100);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_score_agency_fit_bucket'
    ) THEN
        ALTER TABLE scores
            ADD CONSTRAINT chk_score_agency_fit_bucket
            CHECK (agency_fit_bucket IS NULL OR agency_fit_bucket IN ('hot', 'warm', 'cold', 'skip'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_score_estimated_deal_value'
    ) THEN
        ALTER TABLE scores
            ADD CONSTRAINT chk_score_estimated_deal_value
            CHECK (estimated_deal_value IS NULL OR estimated_deal_value >= 0);
    END IF;
END $$;
