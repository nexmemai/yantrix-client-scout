# Yantrix Client Scout — Architecture Specification

> **Version:** 1.0 · **Date:** 2026-05-14 · **Author:** Yantrix Labs Engineering

Internal engine that discovers local businesses, audits their websites, scores them, and generates pitch-ready outreach notes.

---

## 1. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Oracle Cloud A1 Flex VM                        │
│                      (Docker Compose)                            │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  Dashboard   │  │  FastAPI     │  │  gosom/gmaps-scraper   │  │
│  │  React+Vite  │  │  Backend     │  │  Docker sidecar        │  │
│  │  :3000       │  │  :8000       │  │  :8080                 │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬───────────┘  │
│         │                 │                        │              │
│         └────────►  REST API  ◄────────────────────┘              │
│                       │                                          │
│              ┌────────┼────────┐                                 │
│              ▼        ▼        ▼                                 │
│        ┌──────┐ ┌─────────┐ ┌──────────┐                        │
│        │Audit │ │ LLM     │ │ CRM      │                        │
│        │Worker│ │ Scorer  │ │ Exporter │                        │
│        │(PW)  │ │Groq/NIM │ │HS/Zoho  │                        │
│        └──┬───┘ └────┬────┘ └─────┬────┘                        │
│           │          │            │                              │
│           ▼          ▼            ▼                              │
│       ┌────────────────────────────────┐                        │
│       │   PostgreSQL (Supabase)        │                        │
│       │   :5432 (or hosted)            │                        │
│       └────────────────────────────────┘                        │
└──────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Discovery (GMaps/JustDial/CSV)
    → businesses table
        → Website Auditor (Playwright)
            → audits table
                → LLM Scorer (Groq / NVIDIA NIM)
                    → scores table (pitch notes)
                        → CRM Export (HubSpot/Zoho/JSON)
```

---

## 2. Service Boundaries

### 2.1 FastAPI Backend (`backend/`)

| Concern | Responsibility |
|---------|---------------|
| **API Layer** | REST endpoints, validation, auth (optional) |
| **Discovery Service** | Orchestrate gmaps-scraper jobs, JustDial crawl, CSV import |
| **Audit Service** | Playwright-based website audit pipeline |
| **Scoring Service** | LLM calls to Groq/NVIDIA NIM, composite scoring |
| **Export Service** | JSON/CSV export, HubSpot/Zoho CRM push |
| **Config Service** | Niche definitions, scoring weight presets |

### 2.2 Google Maps Scraper (`gosom/google-maps-scraper`)

- Runs as a Docker sidecar on port `8080`
- Exposes REST API: `POST /api/v1/jobs`, `GET /api/v1/jobs/{id}/download`
- Backend submits queries like `"dental clinics in Pune"` and polls for CSV results

### 2.3 Dashboard (`dashboard/`)

- Vite + React + TanStack Router + TanStack Table
- Consumes backend REST API exclusively
- No direct database access

---

## 3. REST API Design

### `POST /api/v1/run-scout`
Trigger a full discovery → audit → score pipeline.

```json
{
  "query": "dental clinics in Pune",
  "source": "google_maps",        // google_maps | justdial | csv
  "csv_file": null,               // base64 CSV (when source=csv)
  "niche": "healthcare",          // maps to scoring config
  "auto_audit": true,
  "auto_score": true
}
```
**Response:** `{ "job_id": "uuid", "status": "queued" }`

### `POST /api/v1/audit-site`
Audit a single website on demand.

```json
{
  "url": "https://example-clinic.com",
  "business_id": "uuid"           // optional, link to existing lead
}
```
**Response:** Full audit result object.

### `GET /api/v1/leads`
List/filter/sort discovered businesses with audit + score data.

```
?city=Pune&category=dental&min_score=60&sort=score_desc&page=1&limit=25
```

### `GET /api/v1/leads/{id}`
Full lead detail: business info + audit + score + pitch notes.

### `GET /api/v1/configs`
List scoring configurations per niche.

### `PUT /api/v1/configs/{niche}`
Update scoring weights for a niche.

```json
{
  "niche": "healthcare",
  "weights": {
    "has_website": 5,
    "mobile_friendly": 15,
    "has_forms": 15,
    "has_cta": 10,
    "has_whatsapp": 10,
    "has_booking": 15,
    "ssl_valid": 5,
    "page_speed": 10,
    "seo_basics": 10,
    "social_presence": 5
  }
}
```

### `POST /api/v1/export`
Export leads to CRM or download.

```json
{
  "lead_ids": ["uuid1", "uuid2"],
  "destination": "hubspot",       // hubspot | zoho | json | csv
  "filters": {}                   // alternative to lead_ids
}
```

### `GET /api/v1/jobs`
List pipeline jobs with status tracking.

---

## 4. Database Schema

### ERD

```
discovery_jobs 1──* businesses 1──1 audits 1──1 scores
                                                  │
scoring_configs (per niche)                       │
                                            export_logs
```

### Tables

```sql
-- ============================================================
-- Discovery Jobs
-- ============================================================
CREATE TABLE discovery_jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query         TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('google_maps','justdial','csv')),
    niche         TEXT,
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued','running','completed','failed')),
    result_count  INTEGER DEFAULT 0,
    error_message TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    completed_at  TIMESTAMPTZ
);

-- ============================================================
-- Businesses (Leads)
-- ============================================================
CREATE TABLE businesses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    category        TEXT,
    niche           TEXT,
    address         TEXT,
    city            TEXT,
    state           TEXT,
    country         TEXT DEFAULT 'India',
    phone           TEXT,
    email           TEXT,
    website_url     TEXT,
    google_maps_url TEXT,
    rating          NUMERIC(2,1),
    review_count    INTEGER,
    source          TEXT NOT NULL,
    discovery_job_id UUID REFERENCES discovery_jobs(id) ON DELETE SET NULL,
    raw_data        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, city, address)
);

CREATE INDEX idx_businesses_city ON businesses(city);
CREATE INDEX idx_businesses_niche ON businesses(niche);
CREATE INDEX idx_businesses_source ON businesses(source);

-- ============================================================
-- Website Audits
-- ============================================================
CREATE TABLE audits (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id       UUID NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
    url_checked       TEXT,
    -- Binary checks
    has_website       BOOLEAN DEFAULT FALSE,
    ssl_valid         BOOLEAN DEFAULT FALSE,
    mobile_friendly   BOOLEAN DEFAULT FALSE,
    -- Feature checks
    has_forms         BOOLEAN DEFAULT FALSE,
    has_cta           BOOLEAN DEFAULT FALSE,
    has_whatsapp      BOOLEAN DEFAULT FALSE,
    has_booking       BOOLEAN DEFAULT FALSE,
    has_chatbot       BOOLEAN DEFAULT FALSE,
    -- Metrics
    load_time_ms      INTEGER,
    page_speed_score  INTEGER,           -- 0-100 from PSI API
    -- SEO
    has_title         BOOLEAN DEFAULT FALSE,
    has_meta_desc     BOOLEAN DEFAULT FALSE,
    has_h1            BOOLEAN DEFAULT FALSE,
    has_og_tags       BOOLEAN DEFAULT FALSE,
    -- Social
    has_facebook      BOOLEAN DEFAULT FALSE,
    has_instagram     BOOLEAN DEFAULT FALSE,
    has_linkedin      BOOLEAN DEFAULT FALSE,
    has_twitter       BOOLEAN DEFAULT FALSE,
    -- Tech
    tech_stack        TEXT[],             -- ['wordpress','php','jquery']
    -- Raw
    screenshot_url    TEXT,
    raw_html_hash     TEXT,
    audit_details     JSONB,
    -- Meta
    status            TEXT DEFAULT 'pending'
                      CHECK (status IN ('pending','running','completed','failed','skipped')),
    error_message     TEXT,
    audited_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Scores + Pitch Notes
-- ============================================================
CREATE TABLE scores (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id         UUID NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
    audit_id            UUID REFERENCES audits(id) ON DELETE SET NULL,
    -- Composite
    overall_score       INTEGER NOT NULL CHECK (overall_score BETWEEN 0 AND 100),
    -- Sub-scores
    website_quality     INTEGER CHECK (website_quality BETWEEN 0 AND 100),
    online_presence     INTEGER CHECK (online_presence BETWEEN 0 AND 100),
    conversion_readiness INTEGER CHECK (conversion_readiness BETWEEN 0 AND 100),
    urgency             INTEGER CHECK (urgency BETWEEN 0 AND 100),
    -- LLM output
    pitch_notes         TEXT,             -- markdown bullet points
    recommended_services TEXT[],
    objection_handlers  TEXT,
    -- Meta
    llm_provider        TEXT,             -- 'groq' | 'nvidia_nim'
    llm_model           TEXT,
    scoring_config_id   UUID REFERENCES scoring_configs(id),
    scored_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scores_overall ON scores(overall_score DESC);

-- ============================================================
-- Scoring Configs (per niche)
-- ============================================================
CREATE TABLE scoring_configs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    niche       TEXT NOT NULL UNIQUE,
    weights     JSONB NOT NULL,
    prompt_template TEXT,
    is_default  BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Default config
INSERT INTO scoring_configs (niche, weights, is_default) VALUES
('default', '{
    "has_website": 5,
    "mobile_friendly": 15,
    "has_forms": 15,
    "has_cta": 10,
    "has_whatsapp": 10,
    "has_booking": 15,
    "ssl_valid": 5,
    "page_speed": 10,
    "seo_basics": 10,
    "social_presence": 5
}', true);

-- ============================================================
-- Export Logs
-- ============================================================
CREATE TABLE export_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    destination   TEXT NOT NULL CHECK (destination IN ('hubspot','zoho','json','csv')),
    lead_count    INTEGER,
    status        TEXT DEFAULT 'pending'
                  CHECK (status IN ('pending','completed','failed')),
    payload_hash  TEXT,
    error_message TEXT,
    exported_at   TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 5. External Dependencies

| Dependency | Purpose | Cost | Rate Limits |
|-----------|---------|------|-------------|
| **gosom/google-maps-scraper** | Google Maps business discovery | Free (OSS, Docker) | Self-hosted, no limit |
| **Playwright** | Website auditing + JustDial scraping | Free (OSS) | Self-managed concurrency |
| **Google PSI API** | PageSpeed scores | Free (API key) | 25K req/day |
| **Groq API** (primary LLM) | Scoring + pitch generation | Free tier | ~30 RPM, 14.4K req/day |
| **NVIDIA NIM API** (fallback LLM) | Fallback scoring | Free tier | ~40 RPM |
| **Supabase** | Hosted Postgres + Auth | Free tier (500MB) | — |
| **HubSpot API** | CRM export (contacts + deals) | Free CRM | 100 req/10s |
| **Zoho CRM API** | CRM export (alternative) | Free tier | 5K req/day |

### Python Packages (Backend)

```
fastapi[standard]>=0.115
uvicorn[standard]
sqlalchemy[asyncio]>=2.0
asyncpg
pydantic-settings
playwright
httpx
python-multipart
```

### Node Packages (Dashboard)

```
react, react-dom
@tanstack/react-router
@tanstack/react-table
@tanstack/react-query
recharts
vite
```

---

## 6. Audit Engine Detail

The auditor runs Playwright headless against each business URL:

```python
async def audit_website(url: str) -> AuditResult:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 375, "height": 812})  # mobile
        page = await ctx.new_page()

        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        html = await page.content()

        return AuditResult(
            has_website=True,
            ssl_valid=url.startswith("https"),
            mobile_friendly=check_viewport_meta(html),
            has_forms=bool(await page.query_selector_all("form")),
            has_cta=check_cta_buttons(html),
            has_whatsapp=check_whatsapp(html),
            has_booking=check_booking_widget(html),
            load_time_ms=await get_load_time(page),
            tech_stack=detect_tech_stack(html, await page.evaluate("() => navigator")),
            # ... remaining signals
        )
```

### Detection Heuristics

| Signal | How |
|--------|-----|
| `has_forms` | `<form>` tags, `input[type=email]`, embedded Typeform/Google Forms |
| `has_cta` | Buttons with text: "Book", "Call", "Contact", "Get Quote", "Schedule" |
| `has_whatsapp` | `wa.me` links, `api.whatsapp.com`, WhatsApp widget scripts |
| `has_booking` | Calendly, Acuity, Zoho Bookings, custom booking forms |
| `mobile_friendly` | `<meta name="viewport">` present, no horizontal scroll |
| `tech_stack` | `X-Powered-By` header, generator meta, known script patterns |

---

## 7. LLM Scoring Strategy

### Provider Failover

```
Request → Groq (Llama 3.3 70B)
            │
            ├── 200 OK → parse JSON → save score
            │
            └── 429 / timeout → NVIDIA NIM (fallback)
                                    │
                                    ├── 200 OK → parse JSON → save score
                                    │
                                    └── fail → mark as "score_pending", retry later
```

### Prompt Template (per niche, customizable via `scoring_configs.prompt_template`)

```markdown
You are a sales intelligence analyst for a digital agency.

## Business
- Name: {name} | Category: {category} | City: {city}
- Website: {website_url} | Rating: {rating} ({review_count} reviews)

## Website Audit
{audit_json}

## Scoring Weights (niche: {niche})
{weights_json}

## Instructions
1. Calculate `overall_score` (0-100) using the provided weights.
2. Provide sub-scores: website_quality, online_presence, conversion_readiness, urgency.
3. Write 3 bullet-point `pitch_notes` an SDR can use in a cold call.
4. List `recommended_services` (e.g., "Website Redesign", "WhatsApp Integration").
5. Write 2 `objection_handlers` for common pushback.

Return ONLY valid JSON matching this schema:
{output_schema}
```

---

## 8. Deployment Plan — Oracle Cloud Free Tier

### Infrastructure

| Resource | Oracle Free Tier | Usage |
|----------|-----------------|-------|
| **Compute** | A1 Flex (4 OCPU, 24GB RAM) | All containers |
| **Boot Volume** | 200GB | Docker volumes, gmapsdata |
| **Network** | 10TB egress/month | More than enough |
| **OS** | Ubuntu 22.04 (Canonical) | Docker host |

### Docker Compose

```yaml
version: "3.9"

services:
  # ── Backend API ──
  api:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [db, gmaps-scraper]
    restart: unless-stopped
    deploy:
      resources:
        limits: { cpus: "1.5", memory: 4G }

  # ── Google Maps Scraper (sidecar) ──
  gmaps-scraper:
    image: gosom/google-maps-scraper:latest
    ports: ["8080:8080"]
    volumes: ["gmapsdata:/gmapsdata"]
    command: ["-data-folder", "/gmapsdata"]
    restart: unless-stopped
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 4G }

  # ── PostgreSQL ──
  db:
    image: postgres:16-alpine
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: clientscout
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: ["pgdata:/var/lib/postgresql/data"]
    restart: unless-stopped
    deploy:
      resources:
        limits: { cpus: "0.5", memory: 2G }

  # ── Dashboard ──
  dashboard:
    build: ./dashboard
    ports: ["3000:3000"]
    depends_on: [api]
    restart: unless-stopped
    deploy:
      resources:
        limits: { cpus: "0.5", memory: 1G }

  # ── Nginx Reverse Proxy ──
  nginx:
    image: nginx:alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/certs:/etc/nginx/certs:ro
    depends_on: [api, dashboard]
    restart: unless-stopped

volumes:
  pgdata:
  gmapsdata:
```

### Resource Allocation (4 OCPU / 24GB)

```
API:             1.5 OCPU, 4GB   (FastAPI + Playwright browsers)
GMaps Scraper:   1.0 OCPU, 4GB   (Go binary + headless Chrome)
PostgreSQL:      0.5 OCPU, 2GB
Dashboard:       0.25 OCPU, 1GB  (static serve)
Nginx:           0.25 OCPU, 512MB
System/OS:       0.5 OCPU, 2GB
────────────────────────────────
Total:           4.0 OCPU, ~13.5GB (headroom: 10.5GB for bursts)
```

### Setup Script

```bash
#!/bin/bash
# setup-oracle-vm.sh

# 1. Install Docker
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER

# 2. Open firewall ports
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT

# 3. Clone repo
git clone https://github.com/yantrix-labs/client-scout.git
cd client-scout

# 4. Configure
cp .env.example .env
# Edit .env with API keys

# 5. Install Playwright browsers in backend image
# (handled in Dockerfile: RUN playwright install chromium --with-deps)

# 6. Launch
docker compose up -d

# 7. Run migrations
docker compose exec api python -m app.migrate
```

### `.env.example`

```env
# Database
DB_HOST=db
DB_PORT=5432
DB_NAME=clientscout
DB_USER=scout
DB_PASSWORD=changeme

# LLM Providers
GROQ_API_KEY=gsk_...
NVIDIA_NIM_API_KEY=nvapi-...

# Google PageSpeed (optional)
PSI_API_KEY=AIza...

# CRM (optional)
HUBSPOT_ACCESS_TOKEN=pat-...
ZOHO_CLIENT_ID=
ZOHO_CLIENT_SECRET=
ZOHO_REFRESH_TOKEN=

# Scraper
GMAPS_SCRAPER_URL=http://gmaps-scraper:8080

# App
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000
```

---

## 9. Project Structure

```
yantrix-client-scout/
├── ARCHITECTURE.md              ← this file
├── docker-compose.yml
├── .env.example
├── nginx/
│   └── nginx.conf
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app, lifespan, CORS, routers
│   │   ├── config.py            # Pydantic Settings
│   │   ├── database.py          # async SQLAlchemy engine + session
│   │   ├── migrate.py           # Run SQL migrations
│   │   ├── models/
│   │   │   ├── business.py
│   │   │   ├── audit.py
│   │   │   ├── score.py
│   │   │   ├── job.py
│   │   │   └── config.py
│   │   ├── schemas/
│   │   │   ├── business.py
│   │   │   ├── audit.py
│   │   │   ├── score.py
│   │   │   ├── job.py
│   │   │   └── config.py
│   │   ├── api/
│   │   │   ├── run_scout.py     # POST /run-scout
│   │   │   ├── audit_site.py    # POST /audit-site
│   │   │   ├── leads.py         # GET /leads, /leads/{id}
│   │   │   ├── configs.py       # GET/PUT /configs
│   │   │   ├── export.py        # POST /export
│   │   │   └── jobs.py          # GET /jobs
│   │   ├── services/
│   │   │   ├── gmaps_scraper.py
│   │   │   ├── justdial_scraper.py
│   │   │   ├── csv_importer.py
│   │   │   ├── website_auditor.py
│   │   │   ├── llm_scorer.py
│   │   │   └── crm_exporter.py
│   │   └── workers/
│   │       ├── discovery_worker.py
│   │       └── audit_worker.py
│   └── tests/
│       ├── test_api.py
│       ├── test_auditor.py
│       └── test_scorer.py
├── dashboard/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── api/client.js
│       ├── pages/
│       │   ├── Dashboard.jsx
│       │   ├── Discovery.jsx
│       │   ├── Leads.jsx
│       │   ├── LeadDetail.jsx
│       │   ├── Configs.jsx
│       │   └── Export.jsx
│       ├── components/
│       │   ├── Sidebar.jsx
│       │   ├── ScoreGauge.jsx
│       │   ├── AuditCard.jsx
│       │   ├── LeadTable.jsx
│       │   └── StatsCards.jsx
│       └── styles/
│           └── index.css
└── supabase/
    └── migrations/
        └── 001_initial_schema.sql
```

---

## 10. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| API keys in env | `.env` excluded from git, Docker secrets in prod |
| Scraping rate limits | Semaphore-controlled concurrency, jitter delays |
| JustDial ToS | Feature-flagged, disabled by default, rate-limited |
| SQL injection | SQLAlchemy ORM + Pydantic validation |
| CORS | Restricted to dashboard origin only |
| DB credentials | Rotated on deploy, not hardcoded |

---

## 11. Future Enhancements (Post-MVP)

- **n8n integration**: Webhook triggers for pipeline events → n8n workflows
- **Scheduled scouts**: Cron-based recurring discovery per niche/city
- **Lead dedup ML**: Fuzzy matching beyond exact name+address
- **Email enrichment**: Hunter.io / Apollo API for contact discovery
- **WhatsApp outreach**: Direct integration via WhatsApp Business API
- **Multi-tenant**: RBAC + org-level data isolation
- **Supabase Edge Functions**: Serverless audit triggers
