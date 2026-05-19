# Yantrix Client Scout

Yantrix Client Scout is a Dockerized lead discovery and sales intelligence platform for Yantrix Labs. It finds local businesses from Google Maps, audits their websites, scores them as agency prospects, generates AI-powered outreach pitches, and presents everything in a React dashboard.

## What problem it solves

Yantrix Client Scout helps sales and growth teams move from raw local-business discovery to qualified outreach in one workflow. Instead of manually searching Google Maps, checking websites, and writing outreach by hand, the system automates lead discovery, enrichment, scoring, and pitch generation.

This reduces manual research time, improves consistency, and makes it easier to prioritize the businesses most likely to convert into agency clients.

## Feature overview

- Google Maps lead discovery.
- CSV ingestion for pre-scraped Google Maps files.
- Business normalization and deduplication.
- Website audits using Playwright.
- Audit signals for website, SSL, mobile, form, CTA, WhatsApp, booking, chatbot, Facebook, Instagram, load time, PageSpeed, tech stack, and CMS detection.
- Pain flags for no booking, no WhatsApp, no form, no SSL, not mobile, slow load, no CTA, and no chatbot.
- Scoring for overall score, website quality, online presence, conversion readiness, urgency, agency fit score, fit bucket, opportunity types, and estimated deal value.
- Contact enrichment with name, title, email, phone, LinkedIn URL, and confidence.
- Mini CRM with lead status, notes, follow-up date, contact attempts, and assigned user.
- AI pitch generation for email, WhatsApp, follow-up, call opener, service recommendations, and personalization notes.
- Dashboard for filtering, viewing lead details, regenerating pitches, copying pitches, sending via WhatsApp, launching scout jobs, and tracking job status.

## Architecture diagram

```text
User
  |
  v
React + TypeScript + Vite Dashboard
  |
  | same-origin requests via /api/v1/...
  v
Nginx reverse proxy
  |-----------------------------|
  |                             |
  v                             v
FastAPI API  <----->  PostgreSQL / Supabase-compatible DB
  |
  | internal Docker network
  v
gosom/google-maps-scraper container
  |
  v
Google Maps lead discovery

FastAPI also uses Playwright Chromium inside the API container for website audits.
```

## Tech stack

- Backend: FastAPI, Python.
- Frontend: React, TypeScript, Vite.
- Database: PostgreSQL with a Supabase-compatible schema.
- Orchestration: Docker Compose.
- Deployment target: Single VM, currently GCP VM.
- Browser automation: Playwright Chromium inside the API container.
- Scraper: `gosom/google-maps-scraper` container.
- Reverse proxy: Nginx serving the React SPA and proxying `/api` to FastAPI.

## Repository structure

```text
yantrix-client-scout/
├─ api/
├─ dashboard/
├─ db/
├─ scripts/
├─ docker-compose.yml
├─ nginx/
├─ README.md
└─ .env.example
```

## Environment variables

Create a `.env` file at the repository root and configure the following values as needed:

```env
# Core
YANTRIX_API_TOKEN=replace_with_strong_token
ENV=production
DEBUG=false

# Database
POSTGRES_DB=clientscout
POSTGRES_USER=clientscout
POSTGRES_PASSWORD=replace_with_strong_password
POSTGRES_HOST=db
POSTGRES_PORT=5432
DATABASE_URL=postgresql://clientscout:replace_with_strong_password@db:5432/clientscout

# Scraper
GMAPS_SCRAPER_URL=http://gmaps-scraper:8080

# Frontend
VITE_APP_NAME=Yantrix Client Scout

# Optional application settings
SNAPSHOT_DIR=/app/snapshots
LOG_LEVEL=info
```

Important production note: `GMAPS_SCRAPER_URL` must remain `http://gmaps-scraper:8080` inside Docker.

Do not use `localhost` or `127.0.0.1` as the frontend API base URL in production, because the dashboard should talk to the API through the same-origin `/api` proxy.

## Local Docker setup

Clone the repository:

```bash
git clone [https://github.com/nexmemai/yantrix-client-scout.git](https://github.com/nexmemai/yantrix-client-scout.git)
cd yantrix-client-scout
```

Build the services:

```bash
docker compose build api dashboard
```

Start the stack:

```bash
docker compose up -d
```

Check running services:

```bash
docker compose ps
```

Health checks:

```bash
curl [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
curl [http://127.0.0.1:8000/ready](http://127.0.0.1:8000/ready)
curl [http://127.0.0.1:3000/health](http://127.0.0.1:3000/health)
```

## Production Docker Compose setup

The production topology is the same Docker Compose stack, usually deployed on a single VM with a stable IP or domain. The API, DB, dashboard, and scraper containers communicate over the internal Docker network, while the dashboard is the main public entry point through Nginx.

Recommended exposure model:

- API and DB should remain private where possible.
- Dashboard can be exposed on port `3000` with firewall rules restricted to trusted IPs.
- Dashboard should talk to the API through the same-origin `/api` proxy.
- Playwright browsers should be installed during the API image build.
- The snapshot directory must be writable by the scout user.

## GCP VM deployment notes

For GCP VM deployment, provision a VM with enough CPU and RAM for Playwright, the scraper, and PostgreSQL. Keep the instance updated, restrict inbound firewall access, and only open the ports you actually need. In most cases, `3000` is the only externally reachable application port, while `8000`, `5432`, and scraper debug ports should stay internal or locked down.

A good production checklist:

- Install Docker and Docker Compose.
- Clone the repository.
- Configure the `.env` file.
- Build images on the VM.
- Start the stack with `docker compose up -d`.
- Restrict access to the dashboard by source IP.
- Keep backups of the database volume and any important snapshots.

## Running migrations

Run database migrations from the API container after the database is reachable and the schema is in place:

```bash
docker exec -it clientscout-api python -m alembic upgrade head
```

If your project uses a different migration entrypoint, keep the same operational pattern: run migrations from inside the API container so they use the same environment and database network as the running app.

## Smoke testing

Run the smoke test script after deployment or after any image rebuild:

```bash
bash scripts/smoke-test.sh
```

The smoke test should verify that the API is healthy, the dashboard is reachable, the database connection works, and the core routes return expected responses.

## Dashboard usage

The dashboard provides a fast operational view of discovery and outreach. Use it to inspect leads, filter by city, niche, score bucket, agency fit, status, and date, and open the lead detail page for deeper review. From the lead detail screen, you can regenerate pitches, copy the email pitch, send via WhatsApp, and update sales state.

The dashboard also includes a today summary view and job polling so you can monitor in-progress scout jobs without leaving the UI.

## Starting a scout job

Trigger a new scout job from the API with a POST request:

```bash
curl -X POST [http://127.0.0.1:8000/api/v1/run-scout](http://127.0.0.1:8000/api/v1/run-scout) \
  -H "Authorization: Bearer $YANTRIX_API_TOKEN" \
  -H "X-Yantrix-Token: $YANTRIX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"niche":"dental","city":"Chicago","max_businesses":10}'
```

Check the job status:

```bash
curl http://127.0.0.1:8000/api/v1/jobs/<job_id> \
  -H "Authorization: Bearer $YANTRIX_API_TOKEN" \
  -H "X-Yantrix-Token: $YANTRIX_API_TOKEN"
```

Useful API routes:

- `GET /health`
- `GET /ready`
- `POST /api/v1/run-scout`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/leads`
- `GET /api/v1/leads/{lead_id}`
- `POST /api/v1/leads/{lead_id}/pitch`
- `PATCH /api/v1/leads/{lead_id}/sales`
- `GET /api/v1/leads/summary`
- `GET /api/v1/configs`

## CSV ingestion example

Import a pre-scraped Google Maps CSV from inside the API container:

```bash
docker exec -it clientscout-api python scripts/ingest_gmaps_csv.py \
  --file /app/sioux_falls_dental.csv \
  --niche dental \
  --city "Sioux Falls" \
  --run-audit \
  --run-score \
  --run-pitches
```

This workflow normalizes businesses, deduplicates records, runs audits, generates scores, and creates pitches in one pass.

## Pitch generation workflow

Pitch generation is designed to be repeatable and context-aware. The system combines audit results, contact enrichment, scoring, and niche configuration to generate outreach variants for different channels.

Typical flow:

1. Discover or ingest leads.
2. Normalize and deduplicate businesses.
3. Audit the website and collect signals.
4. Score the lead and assign a fit bucket.
5. Enrich contact data if available.
6. Generate the email pitch, WhatsApp pitch, WhatsApp follow-up, call opener, recommended services, and personalization notes.
7. Review in the dashboard and send the chosen outreach message.

## Operational runbook commands

View service logs:

```bash
docker compose logs -f api
docker compose logs -f dashboard
docker compose logs -f gmaps-scraper
docker compose logs -f db
```

Rebuild the API without cache:

```bash
docker compose build --no-cache api
docker compose up -d --force-recreate api
```

Recreate the dashboard:

```bash
docker compose up -d --force-recreate dashboard
```

Rollback to a previous commit:

```bash
git log --oneline -5
git checkout <previous_commit>
docker compose build api dashboard
docker compose up -d --force-recreate api dashboard
```

## Troubleshooting

If the API is healthy but the dashboard cannot load data, confirm the Nginx `/api` proxy is routing requests to FastAPI and that the frontend is not using a hardcoded localhost API base URL. If scout jobs fail, verify that `GMAPS_SCRAPER_URL` is set correctly and that the scraper container is running on the internal Docker network.

If Playwright audits fail, make sure Chromium is installed in the API image and that the snapshot directory is writable by the scout user. If PostgreSQL is unreachable, confirm the DB container is healthy and the database URL matches the running container name and credentials.

## Security notes

Use a strong API token and keep it out of source control. Restrict access to the dashboard, API, and database ports at the firewall level, especially in production. Keep the API and DB private where possible, and only expose the dashboard to trusted IPs.

Avoid putting secrets in frontend code, environment variables committed to Git, or shell history. Treat lead data and contact enrichment data as operationally sensitive.

## Roadmap

- More advanced enrichment sources.
- Better job history and replay tools.
- Enhanced lead deduplication across cities and niches.
- Export to CRM and sales workflow integrations.
- Improved analytics for outreach performance.
- More configurable pitch templates and scoring weights.
- Role-based access control for dashboard users.

## License

License: **TODO** — add your chosen license here.
