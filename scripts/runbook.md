# Yantrix Client Scout — Operations Runbook

> All commands assume you are in the repo root: `cd ~/yantrix-client-scout`

---

## Quick Reference

| Action | Command |
|--------|---------|
| Build API image | `docker compose build --no-cache api` |
| Start all services | `docker compose up -d` |
| Start with local DB | `COMPOSE_PROFILES=local-db docker compose up -d` |
| Restart API + scraper | `docker compose restart api gmaps-scraper` |
| Smoke test | `bash scripts/smoke-test.sh` |
| View API logs | `docker compose logs api --tail=100 -f` |
| View all logs | `docker compose logs --tail=50 -f` |
| Stop all | `docker compose down` |
| Full teardown (⚠ deletes data) | `docker compose down -v` |

---

## Build

Rebuild the API image from scratch (after code/Dockerfile changes):

```bash
docker compose build --no-cache api
```

This bakes Playwright Chromium into the image. No manual `playwright install` needed.

To rebuild all services (API + dashboard):

```bash
docker compose build --no-cache
```

---

## Start / Up

### With external DB (Supabase, managed Postgres)

```bash
docker compose up -d
```

### With local Postgres

```bash
COMPOSE_PROFILES=local-db docker compose up -d
```

### With all optional services

```bash
COMPOSE_PROFILES=local-db,n8n,scrapy docker compose up -d
```

### Verify

```bash
docker compose ps
```

All services should show `Up` status. The API should become `healthy` within 30 seconds.

---

## Restart

Restart specific services without rebuilding:

```bash
docker compose restart api gmaps-scraper
```

Restart and rebuild:

```bash
docker compose up -d --build api
```

---

## Logs

### API logs (most useful)

```bash
docker compose logs api --tail=100 -f
```

Look for startup validation lines:

```
[STARTUP] ✓ Database connectivity OK
[STARTUP] ✓ Playwright Chromium OK
[STARTUP] ✓ GMaps scraper reachable at http://gmaps-scraper:8080
[STARTUP] Yantrix Client Scout API v0.1.0 ready
```

### Pipeline run logs

After a run-scout request, you'll see structured stage tags:

```
[Job <id>] [PIPELINE] started ...
[Job <id>] [DISCOVER] starting ...
[Job <id>] [DISCOVER] complete — N new businesses found
[<business-id>] [AUDIT] starting ...
[<business-id>] [SCORE] completed total=65 bucket=high-fit
[<business-id>] [PITCH] completed
[Job <id>] [PIPELINE] completed: ...
```

### All service logs

```bash
docker compose logs --tail=50 -f
```

### Scraper-specific

```bash
docker compose logs gmaps-scraper --tail=50 -f
```

---

## Smoke Test

Run the full smoke test suite:

```bash
bash scripts/smoke-test.sh
```

Customize the test payload:

```bash
SMOKE_NICHE=salon SMOKE_CITY=Mumbai bash scripts/smoke-test.sh
```

The smoke test checks:
1. Docker containers are running
2. Scraper API docs endpoint
3. API health endpoint
4. Database connectivity
5. Playwright browser launch
6. A live run-scout request

---

## Manual API Calls

### Health check

```bash
curl http://127.0.0.1:8000/health
```

### Run a scout pipeline

```bash
curl -X POST http://127.0.0.1:8000/api/v1/run-scout \
  -H "Content-Type: application/json" \
  -d '{
    "niche": "dental",
    "city": "Jaipur",
    "depth": 1,
    "max_businesses": 10,
    "auto_audit": true,
    "auto_score": true,
    "auto_pitch": true,
    "pitch_tone": "professional"
  }'
```

### List leads

```bash
curl "http://127.0.0.1:8000/api/v1/leads?niche=dental&city=Jaipur&page=1&limit=10"
```

### Export CSV

```bash
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -d '{"niche":"dental","city":"Jaipur","format":"csv"}'
```

---

## Teardown

### Stop containers (preserve data volumes)

```bash
docker compose down
```

### Full teardown (⚠ destroys DB data, snapshots, scraper cache)

```bash
docker compose down -v
```

### Remove images too

```bash
docker compose down -v --rmi local
```

---

## Troubleshooting

### API won't start / healthcheck failing

```bash
docker compose logs api --tail=30
```

Look for `[STARTUP] ✗` lines:

| Error | Fix |
|-------|-----|
| `Database connectivity FAILED` | Check `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD` in `.env`. If using local-db profile, ensure `COMPOSE_PROFILES=local-db`. |
| `Playwright Chromium FAILED` | Rebuild the image: `docker compose build --no-cache api` |
| `GMaps scraper not reachable` | Check if scraper is running: `docker compose logs gmaps-scraper --tail=20`. It may still be starting. |

### Playwright permission denied

This means the Dockerfile wasn't rebuilt. The fix is baked into the image build:

```bash
docker compose build --no-cache api
docker compose up -d api
```

### Zero discovery results

This is normal behavior — the Google Maps scraper sometimes returns no results for a given query. Try:
- A different city (larger cities have more listings)
- Increasing `depth` (1→3)
- A broader niche

### Scraper not reachable from host

The scraper is bound to `127.0.0.1:8080` (localhost only). From the VM:

```bash
curl http://127.0.0.1:8080/api/docs
```

It is NOT accessible from outside the VM for security.

---

## Architecture Notes

### DB Schema (Postgres)

The core tables are:
- `businesses` — discovered business leads (NOT "leads" table)
- `audits` — website audit results (1:1 with businesses)
- `scores` — composite lead-fit scores (1:1 with businesses)
- `pitches` — LLM-generated outreach text (many per business)
- `discovery_jobs` — pipeline execution tracking
- `niche_configs` — per-niche scoring weights

There is NO `leads` table. The `/api/v1/leads` endpoint queries the `businesses` table.

### Service Communication

```
Host → API container:  localhost:8000
Host → Scraper:        localhost:8080 (debug only)
API  → Scraper:        http://gmaps-scraper:8080 (Docker internal DNS)
API  → DB:             postgresql://scout:***@db:5432/clientscout (Docker internal)
```

The API MUST use `GMAPS_SCRAPER_URL=http://gmaps-scraper:8080` (Docker DNS), never `127.0.0.1:8080`.
