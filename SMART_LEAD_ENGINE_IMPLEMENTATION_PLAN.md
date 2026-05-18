# Yantrix Client Scout - Smart Lead Engine Implementation Plan

This document is a detailed handoff for any AI agent or engineer implementing
the next phase of Yantrix Client Scout.

The current system is already live and working on a GCP VM with Docker Compose.
Do not redesign the architecture, replace the stack, or break existing routes.
The goal is to upgrade the current scraper + dashboard into a smarter,
higher-conversion lead engine while preserving all existing behavior.

## Project Context

Yantrix Client Scout discovers local businesses, audits their websites, scores
them for agency opportunity, generates outreach pitches, and displays leads in
a React dashboard.

Current pipeline:

```text
DISCOVERY -> AUDIT -> SCORE -> PITCH -> DASHBOARD
```

Current deployment:

```text
GCP VM -> Docker Compose -> api + dashboard + gmaps-scraper + db
```

The application is production-like and actively used, so all changes should be:

- Additive where possible.
- Backward compatible.
- Covered by basic tests.
- Committed as permanent repo changes, not container hotfixes.
- Safe for a single-VM Docker Compose deployment.

## Repository Layout

```text
client-scout-api/          FastAPI backend
client-scout-dashboard/    React dashboard served by Nginx
docs/                      Operational docs
scripts/                   VM and smoke-test scripts
docker-compose.yml         Main Docker Compose stack
```

Important backend files:

```text
client-scout-api/app/api/run_scout.py
client-scout-api/app/api/jobs.py
client-scout-api/app/api/leads.py
client-scout-api/app/api/configs.py
client-scout-api/app/services/discovery.py
client-scout-api/app/services/gmaps_client.py
client-scout-api/app/services/audit_worker.py
client-scout-api/app/services/auditor.py
client-scout-api/app/services/scoring.py
client-scout-api/app/services/pitch_generator.py
client-scout-api/app/models/
client-scout-api/app/schemas/
client-scout-api/migrations/001_initial_schema.sql
```

Important dashboard files:

```text
client-scout-dashboard/src/api/client.ts
client-scout-dashboard/src/lib/types.ts
client-scout-dashboard/src/pages/LeadsPage.tsx
client-scout-dashboard/src/pages/LeadDetailPage.tsx
client-scout-dashboard/src/pages/ConfigsPage.tsx
client-scout-dashboard/nginx.conf
client-scout-dashboard/README.md
```

## Current Runtime Architecture

Docker services:

```text
api             FastAPI backend, container: clientscout-api
gmaps-scraper   Google Maps scraper sidecar, container: gmaps-scraper
dashboard       React SPA served by Nginx, container: clientscout-dashboard
db              Postgres, container: clientscout-db
```

Important URLs and ports:

```text
Dashboard public browser URL: http://<vm-ip>:3000
API debug URL on VM only:     http://127.0.0.1:8000
Postgres on VM only:          127.0.0.1:5432
Scraper inside Docker:        http://gmaps-scraper:8080
```

Do not change this required Docker-internal API setting:

```env
GMAPS_SCRAPER_URL=http://gmaps-scraper:8080
```

Do not replace it with this for the API container:

```env
GMAPS_SCRAPER_URL=http://127.0.0.1:8080
```

The dashboard talks to the API through same-origin Nginx proxying:

```text
Browser -> http://<vm-ip>:3000/api/v1/...
Nginx  -> http://api:8000/api/v1/... on Docker network
```

Production frontend requests should remain relative:

```text
/api/v1/...
```

Do not make production browser code call `localhost`, `127.0.0.1`, port `8000`,
or the VM IP directly for API requests.

## Existing Database Tables

The existing schema includes:

```text
discovery_jobs
businesses
audits
scores
pitches
niche_configs
```

There is no separate `leads` table.

Dashboard leads come from `businesses` enriched with related audit, score, and
pitch data.

## Existing UI Ground Truth

### Leads List

Route:

```text
/leads
```

Current filters:

```text
niche
city
max_businesses / Run Scout panel
fit_bucket
created date range
```

Current table columns:

```text
Lead name
City
Website Yes/No
Score numeric
Fit badge, e.g. high-fit
Created date
```

### Lead Detail Page

Current top badges:

```text
high-fit
Score 90
```

Current Business Info card:

```text
Website URL
Phone
Email
Rating
Review count
Created date
```

Current Score Breakdown card:

```text
Website quality
Online presence
Conversion readiness
Urgency
```

These are shown as numeric bars adding up to the old total score.

Current Audit Signals card:

```text
Website
SSL
Mobile
Form
CTA
WhatsApp
Booking
Chatbot
Facebook
Instagram
Load time
PageSpeed
Tech stack
```

Current Pitch section:

```text
AI-generated pitch paragraph
Regenerate pitch button
```

Do not remove or rename existing UI fields unless absolutely necessary.

## Existing Run Scout Behavior

Endpoint:

```http
POST /api/v1/run-scout
```

Current behavior:

1. Creates a `discovery_jobs` row.
2. Returns immediately with `job_id` and `status=running`.
3. Runs the pipeline in the background.
4. Dashboard polls job status.

Job status endpoints:

```http
GET /api/v1/jobs
GET /api/v1/jobs/{job_id}
```

The Leads page includes a Run Scout form and polls job status every few seconds.

## Core Goal

Upgrade the system from a good leads list into a global, reliable client finder.

The new system should help answer:

```text
Who should I contact today?
Why are they a good lead?
What pain do they have?
Can they pay?
Who should I contact?
What should I say?
When should I follow up?
```

## Non-Negotiable Rules

1. Do not redesign the architecture.
2. Do not introduce Kubernetes.
3. Do not break existing routes.
4. Do not remove existing fields from API responses.
5. Use additive migrations.
6. Keep API and DB private to the VM.
7. Keep dashboard API calls same-origin through `/api`.
8. Keep `GMAPS_SCRAPER_URL=http://gmaps-scraper:8080`.
9. No heavy crawling or expensive enrichment by default.
10. Keep the solution budget-conscious and reliable for one VM.

## Implementation Phases

Implement in phases. Do not attempt all features in one large patch.

Recommended order:

```text
Phase 0: Safety baseline
Phase 1: Additive database migration
Phase 2: Backend schema/API expansion
Phase 3: Rating + review count verification
Phase 4: Pain flags
Phase 5: Agency-fit scoring
Phase 6: Contact enrichment
Phase 7: Mini-CRM fields and endpoints
Phase 8: Outreach helpers
Phase 9: Dashboard UI updates
Phase 10: Today summary
Phase 11: Docs, tests, smoke test updates
```

## Phase 0 - Safety Baseline

Before changes:

1. Create a feature branch.
2. Check current git status.
3. Run existing tests.
4. Build the dashboard.
5. Confirm smoke test passes on the VM before deployment.

Local commands:

```bash
cd client-scout-api
DEBUG=false python -m pytest tests/test_health.py -q
cd ../client-scout-dashboard
npm run build
```

VM commands:

```bash
cd ~/yantrix-client-scout
docker compose ps
bash scripts/smoke-test.sh
```

Database backup before migration:

```bash
docker exec clientscout-db pg_dump -U scout -d clientscout > clientscout_backup_$(date +%Y%m%d_%H%M%S).sql
```

## Phase 1 - Additive Database Migration

Create a new migration file, for example:

```text
client-scout-api/migrations/004_smart_lead_engine.sql
```

All columns should be nullable or have safe defaults.

### Businesses Additions

Add person-level contact fields:

```sql
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS contact_name TEXT,
    ADD COLUMN IF NOT EXISTS contact_title TEXT,
    ADD COLUMN IF NOT EXISTS contact_email TEXT,
    ADD COLUMN IF NOT EXISTS contact_phone TEXT,
    ADD COLUMN IF NOT EXISTS contact_linkedin_url TEXT,
    ADD COLUMN IF NOT EXISTS contact_confidence INTEGER;
```

Add reliability and ability-to-pay fields:

```sql
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS primary_language VARCHAR(20),
    ADD COLUMN IF NOT EXISTS domain_age_years NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS has_recent_updates BOOLEAN,
    ADD COLUMN IF NOT EXISTS budget_tier VARCHAR(20),
    ADD COLUMN IF NOT EXISTS reliability VARCHAR(20);
```

Add mini-CRM fields:

```sql
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS lead_status VARCHAR(30) NOT NULL DEFAULT 'new',
    ADD COLUMN IF NOT EXISTS follow_up_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_contacted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS contact_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sales_notes TEXT,
    ADD COLUMN IF NOT EXISTS priority_rank INTEGER,
    ADD COLUMN IF NOT EXISTS assigned_to TEXT;
```

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_businesses_lead_status ON businesses (lead_status);
CREATE INDEX IF NOT EXISTS idx_businesses_follow_up_at ON businesses (follow_up_at);
CREATE INDEX IF NOT EXISTS idx_businesses_priority_rank ON businesses (priority_rank);
CREATE INDEX IF NOT EXISTS idx_businesses_budget_reliability ON businesses (budget_tier, reliability);
```

### Audits Additions

Confirm existing audit fields before adding duplicates. Existing fields likely
already include many of these:

```text
has_website
ssl_valid
mobile_friendly
has_forms
has_cta
has_whatsapp
has_booking
has_chatbot
has_facebook
has_instagram
load_time_ms
tech_stack
```

Add only missing fields or aliases if necessary.

Recommended additive fields:

```sql
ALTER TABLE audits
    ADD COLUMN IF NOT EXISTS pain_flags JSONB,
    ADD COLUMN IF NOT EXISTS cms_detected VARCHAR(100);
```

Optional indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_audits_pain_flags ON audits USING GIN (pain_flags);
CREATE INDEX IF NOT EXISTS idx_audits_cms_detected ON audits (cms_detected);
```

### Scores Additions

Do not replace old score fields.

Add:

```sql
ALTER TABLE scores
    ADD COLUMN IF NOT EXISTS agency_fit_score INTEGER,
    ADD COLUMN IF NOT EXISTS agency_fit_bucket VARCHAR(20),
    ADD COLUMN IF NOT EXISTS opportunity_types TEXT[],
    ADD COLUMN IF NOT EXISTS estimated_deal_value INTEGER;
```

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_scores_agency_fit_bucket ON scores (agency_fit_bucket);
CREATE INDEX IF NOT EXISTS idx_scores_agency_fit_score ON scores (agency_fit_score DESC);
CREATE INDEX IF NOT EXISTS idx_scores_opportunity_types ON scores USING GIN (opportunity_types);
```

### Validation Rules

Recommended check constraints, only if easy and safe:

```sql
ALTER TABLE businesses
    ADD CONSTRAINT chk_contact_confidence
    CHECK (contact_confidence IS NULL OR contact_confidence BETWEEN 0 AND 100);

ALTER TABLE scores
    ADD CONSTRAINT chk_agency_fit_score
    CHECK (agency_fit_score IS NULL OR agency_fit_score BETWEEN 0 AND 100);
```

## Phase 2 - Backend Model and Schema Expansion

Update SQLAlchemy models:

```text
client-scout-api/app/models/business.py
client-scout-api/app/models/audit.py
client-scout-api/app/models/score.py
```

Update Pydantic schemas:

```text
client-scout-api/app/schemas/lead.py
client-scout-api/app/schemas/audit.py
client-scout-api/app/schemas/score.py
```

If schema files differ, find them with:

```bash
rg -n "Lead|Business|Audit|Score" client-scout-api/app/schemas
```

Backend response compatibility rules:

- Keep existing response fields.
- Add new nullable fields.
- Do not rename `overall_score`, old score bucket fields, or existing audit
  booleans.
- Keep old dashboard working even if new fields are null.

## Phase 3 - Rating and Review Count

Goal:

```text
Populate rating and review_count from Google Maps scraper output.
```

Current parser:

```text
client-scout-api/app/services/gmaps_client.py
```

It already parses:

```py
rating
review_count
```

Verify that these are mapped in:

```text
client-scout-api/app/services/discovery.py
```

Specifically check the normalization helper that creates `Business` ORM rows.

Expected mapping:

```py
Business(
    rating=raw.rating,
    review_count=raw.review_count,
)
```

Then verify `/api/v1/leads` and `/api/v1/leads/{id}` include:

```json
{
  "rating": 4.5,
  "review_count": 132
}
```

## Phase 4 - Pain Flags

Goal:

Create structured pain flags from existing audit signals.

Recommended service:

```text
client-scout-api/app/services/pain_flags.py
```

Example function:

```py
def build_pain_flags(audit: Audit) -> dict[str, bool]:
    return {
        "pain_no_booking": not audit.has_booking,
        "pain_no_whatsapp": not audit.has_whatsapp,
        "pain_no_form": not audit.has_forms,
        "pain_no_ssl": not audit.ssl_valid,
        "pain_not_mobile": not audit.mobile_friendly,
        "pain_slow_load": bool(audit.load_time_ms and audit.load_time_ms > 3000),
        "pain_no_cta": not audit.has_cta,
        "pain_no_chatbot": not audit.has_chatbot,
        "pain_no_facebook": not audit.has_facebook,
        "pain_no_instagram": not audit.has_instagram,
    }
```

Integrate after audit completes, likely in:

```text
client-scout-api/app/services/audit_worker.py
```

Store:

```py
audit.pain_flags = build_pain_flags(audit)
```

Also map CMS:

```py
audit.cms_detected = detected_cms
```

If `tech_stack` already contains `WordPress`, `Shopify`, etc., derive
`cms_detected` from that list.

## Phase 5 - Agency-Fit Scoring

Goal:

Add a new agency-fit layer without replacing the old score.

Recommended service:

```text
client-scout-api/app/services/agency_fit.py
```

Add function:

```py
def calculate_agency_fit(
    business: Business,
    audit: Audit | None,
    score: Score | None,
) -> AgencyFitResult:
    ...
```

Recommended result shape:

```py
class AgencyFitResult(BaseModel):
    agency_fit_score: int
    agency_fit_bucket: str
    opportunity_types: list[str]
    estimated_deal_value: int
```

Suggested scoring rules:

```text
No booking              +15
No WhatsApp             +10
No chatbot              +10
No form                 +12
No CTA                  +8
Slow load > 3000ms      +10
Not mobile              +15
No SSL                  +8
WordPress               +8
Review count > 100      +10
Rating >= 4.2           +8
High-value niche        +10
```

High-value niches:

```text
dental
clinic
lawyer
real_estate
coaching
salon
spa
physiotherapy
veterinary
hotel
```

Buckets:

```text
hot:  75-100
warm: 50-74
cold: 25-49
skip: 0-24
```

Opportunity types:

```text
website_rebuild
booking_system
whatsapp_integration
chatbot
lead_capture_form
speed_optimization
mobile_optimization
ssl_fix
local_seo
crm_followup
```

Estimated deal value, simple first version:

```text
hot + high-value niche: 150000
hot:                    100000
warm + high-value:       75000
warm:                    50000
cold:                    25000
skip:                        0
```

Persist to `scores`:

```text
agency_fit_score
agency_fit_bucket
opportunity_types
estimated_deal_value
```

Do not replace:

```text
overall_score
fit_bucket / current old bucket
website_quality
online_presence
conversion_readiness
urgency
```

## Phase 6 - Contact Enrichment

Goal:

Find person-level contact info cheaply and best-effort.

Add fields to `businesses`:

```text
contact_name
contact_title
contact_email
contact_phone
contact_linkedin_url
contact_confidence
```

Recommended service:

```text
client-scout-api/app/services/contact_enrichment.py
```

Inputs:

```text
Business
Audit snapshot HTML or audited page HTML
Website URL
```

Cheap sources:

- Homepage HTML.
- Footer.
- `mailto:` links.
- `tel:` links.
- Text containing founder/owner/director/manager.
- LinkedIn links.
- One extra page max:
  - `/contact`
  - `/contact-us`
  - `/about`
  - `/about-us`

Do not implement broad crawling.

Recommended extraction:

```text
Email regex
Phone regex
LinkedIn URL regex
Name/title pattern heuristics
```

Confidence heuristic:

```text
90: email + person name + title found
75: email + title or LinkedIn found
60: email found on contact/about page
45: phone only or generic email found
25: weak text-only match
0: no contact found
```

Generic emails such as `info@`, `hello@`, `contact@`, `admin@` should be lower
confidence unless paired with a person name.

Possible titles:

```text
Owner
Founder
Director
Manager
Principal
Partner
Doctor
Dentist
Clinic Manager
Marketing Manager
```

Trigger point:

- After successful audit.
- Before scoring, if possible.
- Or as a best-effort step in the run-scout pipeline after audit.

Failure rule:

- Enrichment failure must never fail the whole pipeline.
- Log and continue.

## Phase 7 - Mini-CRM Fields and API

Add sales workflow fields to businesses:

```text
lead_status
follow_up_at
last_contacted_at
contact_attempts
sales_notes
priority_rank
assigned_to
```

Allowed `lead_status` values:

```text
new
contacted
replied
meeting_set
proposal_sent
won
lost
ignored
```

Extend:

```http
GET /api/v1/leads
GET /api/v1/leads/{id}
```

Add update endpoint:

```http
PATCH /api/v1/leads/{id}/sales
```

Example payload:

```json
{
  "lead_status": "contacted",
  "follow_up_at": "2026-05-20T10:00:00Z",
  "sales_notes": "Interested. Follow up Friday.",
  "assigned_to": "founder",
  "priority_rank": 1
}
```

Rules:

- If status changes to `contacted`, update `last_contacted_at` if not supplied.
- Optionally increment `contact_attempts` when explicitly requested.
- Do not increment attempts every autosave.

Optional endpoint:

```http
POST /api/v1/leads/{id}/contact-attempt
```

This can safely increment `contact_attempts` and set `last_contacted_at`.

## Phase 8 - Outreach Helpers

Goal:

Make manual outreach fast without integrating email APIs.

Backend should compute for lead detail:

```text
whatsapp_link
email_subject
email_body
```

WhatsApp format:

```text
https://wa.me/<clean_phone>?text=<urlencoded_pitch>
```

Only return `whatsapp_link` when a valid phone exists.

Email subject examples:

```text
Quick idea for {business_name}
Helping {business_name} get more bookings
Website and lead follow-up idea for {business_name}
```

Email body:

- Use existing pitch text.
- Keep it plain text.
- Include business name and niche if helpful.

Dashboard buttons:

```text
Send via WhatsApp
Copy email pitch
```

Optional:

```text
Open email
```

via `mailto:`.

No Gmail/Outlook integration yet.

## Phase 9 - Dashboard UI Updates

Update types:

```text
client-scout-dashboard/src/lib/types.ts
```

Update API client:

```text
client-scout-dashboard/src/api/client.ts
```

Update Leads page:

```text
client-scout-dashboard/src/pages/LeadsPage.tsx
```

Add:

- Status filter.
- Agency fit bucket filter.
- Priority filter.
- Status pill in table.
- Optional agency-fit metric:

```text
Fit: hot · ₹100k potential
```

Update Lead Detail page:

```text
client-scout-dashboard/src/pages/LeadDetailPage.tsx
```

Add to Business Info card:

- Contact name.
- Contact title.
- Contact email with copy icon.
- Contact phone with copy icon.
- Contact LinkedIn URL.
- Contact confidence.
- Budget tier.
- Reliability.
- Rating.
- Review count.

Add to Audit/Pain card:

- Red or amber badges for missing items.
- Example:

```text
No booking
No WhatsApp
Slow load
Not mobile
No chatbot
```

Add to Score section:

- Agency fit score.
- Agency fit bucket.
- Opportunity type badges.
- Estimated deal value.

Add mini-CRM controls:

- Status dropdown.
- Notes textarea with autosave.
- Follow-up date picker.
- Contact attempts count.
- Last contacted timestamp.
- Assigned-to field if simple.

Add outreach buttons:

- Send via WhatsApp.
- Copy email pitch.

UI constraints:

- Keep existing cards and layout.
- Do not create a new landing page.
- Use existing button, field, surface classes.
- Keep cards compact and operational.
- Avoid broad visual redesign.

## Phase 10 - Today Summary

Goal:

Give a daily action snapshot on the Leads page.

Recommended endpoint:

```http
GET /api/v1/leads/summary
```

Response:

```json
{
  "followups_today": 4,
  "new_hot_leads": 12,
  "stale_contacted": 7
}
```

Definitions:

```text
followups_today:
  leads where follow_up_at is today

new_hot_leads:
  leads where lead_status='new' and agency_fit_bucket='hot'

stale_contacted:
  leads where lead_status='contacted'
  and last_contacted_at older than 7 days
  and no replied/meeting/proposal/won/lost status
```

Dashboard:

Add a small summary bar at the top of `/leads`:

```text
Today: 4 follow-ups · 12 new hot leads · 7 stale contacted leads
```

## Phase 11 - Docs, Tests, and Smoke Tests

Update docs:

```text
docs/client-scout-ops.md
client-scout-api/README.md
client-scout-dashboard/README.md
CLAUDE_PROJECT_HANDOFF.md
```

Add tests:

```text
client-scout-api/tests/
```

Recommended tests:

- Lead list still works with old fields.
- Lead detail includes new nullable fields.
- Sales update endpoint updates status/notes/follow-up.
- Agency-fit scoring returns expected buckets.
- Pain flags are computed from audit booleans.
- Run Scout still returns a job ID.

Dashboard:

Run:

```bash
cd client-scout-dashboard
npm run build
```

API:

Run:

```bash
cd client-scout-api
DEBUG=false python -m pytest tests/test_health.py -q
```

VM:

Run:

```bash
cd ~/yantrix-client-scout
docker compose build api dashboard
docker compose up -d --force-recreate api dashboard
docker compose ps
bash scripts/smoke-test.sh
```

## Suggested File Changes by Feature

### Migration

Add:

```text
client-scout-api/migrations/004_smart_lead_engine.sql
```

### Models

Edit:

```text
client-scout-api/app/models/business.py
client-scout-api/app/models/audit.py
client-scout-api/app/models/score.py
```

### Schemas

Edit or add:

```text
client-scout-api/app/schemas/lead.py
client-scout-api/app/schemas/audit.py
client-scout-api/app/schemas/score.py
```

### Services

Add:

```text
client-scout-api/app/services/pain_flags.py
client-scout-api/app/services/agency_fit.py
client-scout-api/app/services/contact_enrichment.py
client-scout-api/app/services/outreach_helpers.py
```

Edit:

```text
client-scout-api/app/services/audit_worker.py
client-scout-api/app/services/scoring.py
client-scout-api/app/api/run_scout.py
```

### API Routes

Edit:

```text
client-scout-api/app/api/leads.py
```

Potentially add:

```text
PATCH /api/v1/leads/{id}/sales
POST /api/v1/leads/{id}/contact-attempt
GET /api/v1/leads/summary
```

### Dashboard

Edit:

```text
client-scout-dashboard/src/lib/types.ts
client-scout-dashboard/src/api/client.ts
client-scout-dashboard/src/pages/LeadsPage.tsx
client-scout-dashboard/src/pages/LeadDetailPage.tsx
```

### Docs

Edit:

```text
docs/client-scout-ops.md
client-scout-api/README.md
client-scout-dashboard/README.md
CLAUDE_PROJECT_HANDOFF.md
```

## API Response Additions

### Lead List Item

Add nullable fields:

```json
{
  "lead_status": "new",
  "priority_rank": 1,
  "follow_up_at": null,
  "last_contacted_at": null,
  "contact_attempts": 0,
  "agency_fit_score": 82,
  "agency_fit_bucket": "hot",
  "estimated_deal_value": 100000,
  "rating": 4.5,
  "review_count": 132
}
```

### Lead Detail

Add nullable fields:

```json
{
  "contact_name": "Jane Smith",
  "contact_title": "Owner",
  "contact_email": "jane@example.com",
  "contact_phone": "+15555555555",
  "contact_linkedin_url": "https://linkedin.com/in/janesmith",
  "contact_confidence": 75,
  "primary_language": "en",
  "domain_age_years": 6.5,
  "has_recent_updates": true,
  "budget_tier": "high",
  "reliability": "medium",
  "lead_status": "new",
  "follow_up_at": null,
  "last_contacted_at": null,
  "contact_attempts": 0,
  "sales_notes": "",
  "priority_rank": 1,
  "assigned_to": null,
  "whatsapp_link": "https://wa.me/...",
  "email_subject": "Quick idea for Jane Dental",
  "email_body": "..."
}
```

### Audit

Add:

```json
{
  "pain_flags": {
    "pain_no_booking": true,
    "pain_no_whatsapp": true,
    "pain_no_form": false,
    "pain_no_ssl": false,
    "pain_not_mobile": true,
    "pain_slow_load": true,
    "pain_no_cta": true,
    "pain_no_chatbot": true
  },
  "cms_detected": "WordPress"
}
```

### Score

Add:

```json
{
  "agency_fit_score": 82,
  "agency_fit_bucket": "hot",
  "opportunity_types": [
    "booking_system",
    "whatsapp_integration",
    "chatbot",
    "speed_optimization"
  ],
  "estimated_deal_value": 100000
}
```

## Local Verification Checklist

After each phase:

```bash
git diff --check
python -m compileall client-scout-api/app
cd client-scout-api && DEBUG=false python -m pytest tests/test_health.py -q
cd ../client-scout-dashboard && npm run build
```

Before deployment:

```bash
git status --short
git log --oneline -5
```

## VM Deployment Checklist

```bash
cd ~/yantrix-client-scout
git pull
docker compose build api dashboard
docker compose up -d --force-recreate api dashboard
docker compose ps
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:3000/health
bash scripts/smoke-test.sh
```

If migrations are mounted into Postgres init only, existing DBs may not apply
new migration automatically. In that case, apply the migration explicitly:

```bash
docker exec -i clientscout-db psql -U scout -d clientscout < client-scout-api/migrations/004_smart_lead_engine.sql
```

Adjust the command if running from inside a different working directory.

## Manual Feature Verification

### Run Scout

```bash
curl -X POST http://127.0.0.1:8000/api/v1/run-scout \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $YANTRIX_API_TOKEN" \
  -H "X-Yantrix-Token: $YANTRIX_API_TOKEN" \
  -d '{"niche":"dental","city":"Sioux Falls","max_businesses":10}'
```

### Poll Job

```bash
curl http://127.0.0.1:8000/api/v1/jobs/<JOB_ID> \
  -H "Authorization: Bearer $YANTRIX_API_TOKEN" \
  -H "X-Yantrix-Token: $YANTRIX_API_TOKEN"
```

### Check Leads

```bash
curl http://127.0.0.1:3000/api/v1/leads \
  -H "Authorization: Bearer $YANTRIX_API_TOKEN" \
  -H "X-Yantrix-Token: $YANTRIX_API_TOKEN"
```

### Check Dashboard

Open:

```text
http://<vm-ip>:3000/leads
```

Verify:

- Leads list still loads.
- Existing filters still work.
- Run Scout still starts a job.
- Job status updates.
- Detail page still opens.
- New fields appear only when present.
- Sales status and notes save.
- WhatsApp/email buttons work when contact info exists.

## Additional Future Ideas for Maximum Output

These are optional and should come after the core smart lead engine.

### Lead Prioritization

- Daily "Top 20 leads to contact" queue.
- Priority score combining agency fit, follow-up due date, freshness, and
  contact confidence.

### Duplicate Management

- UI to merge duplicate businesses.
- Suppression list for companies that should not be contacted.

### Outreach Workflow

- Follow-up sequence generator.
- Objection-handling snippets by niche.
- Call script generator.
- LinkedIn DM generator.

### Reporting

- Lead audit PDF.
- "Why this lead is hot" explanation card.
- Before/after website opportunity report.

### Better Enrichment

- Google Business Profile quality score.
- Domain email verification.
- Competitor count nearby.
- Social activity freshness.
- GBP review recency.

### CRM Integrations

- Export hot leads to CSV.
- Push selected leads to HubSpot or Zoho.
- Webhook sync for won/lost status.

### Automation Safety

- Rate-limit outreach.
- Add contact suppression.
- Track consent and do-not-contact state.

## Final Deliverables Expected From Implementation Agent

At the end of the implementation, provide:

1. List of files changed or added.
2. SQL migrations created.
3. Any new environment variables.
4. Backend endpoints added or changed.
5. Dashboard screens/components changed.
6. Summary of new capabilities.
7. Exact VM deploy commands.
8. Exact verification commands.
9. Any limitations or known follow-up items.

## Important Security Note

A GitHub personal access token was previously shared in chat history. It should
be rotated and never committed, printed in docs, or stored in git remote config.
