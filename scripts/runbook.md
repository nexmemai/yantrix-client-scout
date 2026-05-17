# Yantrix Client Scout Operations Runbook

All commands assume:

```bash
cd ~/yantrix-client-scout
```

## Build

```bash
git pull
docker compose build --no-cache api
```

The API image installs Playwright Chromium at build time as the runtime `scout`
user. Do not run `playwright install` manually inside a live container.

To rebuild everything:

```bash
docker compose build --no-cache
```

## Up

```bash
docker compose up -d
docker compose ps
```

The default single-VM stack starts `api`, `dashboard`, `gmaps-scraper`, and
`db`. Optional services still use profiles:

```bash
COMPOSE_PROFILES=n8n,scrapy docker compose up -d
```

## Restart

Restart without rebuilding:

```bash
docker compose restart api gmaps-scraper
```

Recreate the API after a rebuild:

```bash
docker compose up -d --force-recreate api
```

If the Playwright executable was missing in the running container, the API
container must be recreated after `docker compose build --no-cache api`.

## Logs

```bash
docker compose logs api --tail=100 -f
docker compose logs gmaps-scraper --tail=100 -f
docker compose logs db --tail=100 -f
docker compose logs --tail=50 -f
```

Healthy API startup logs should include:

```text
[STARTUP] db connectivity ok
[STARTUP] playwright chromium launch ok
[STARTUP] gmaps scraper reachable at http://gmaps-scraper:8080
[STARTUP] Yantrix Client Scout API v0.1.0 ready
```

Pipeline logs use these stage tags:

```text
[DISCOVERY]
[AUDIT]
[SCORE]
[PITCH]
```

Zero discovery is a completed outcome, not a crash.

## Smoke Test

```bash
bash scripts/smoke-test.sh
```

The smoke test verifies:

1. `docker compose ps`
2. Scraper docs endpoint on localhost
3. API `/health` and `/ready`
4. DB connectivity
5. Playwright browser launch inside `api`
6. One sample `run-scout` request

Custom payload:

```bash
SMOKE_NICHE=salon SMOKE_CITY=Mumbai SMOKE_MAX_BUSINESSES=3 bash scripts/smoke-test.sh
```

## Manual Verification

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:8080/api/docs | head
docker compose exec -T api python - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    print("playwright ok")
    browser.close()
PY
```

Run a small pipeline:

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/v1/run-scout \
  -H "Content-Type: application/json" \
  -d '{"niche":"dental","city":"Jaipur","depth":1,"max_businesses":3,"auto_audit":true,"auto_score":true,"auto_pitch":true}'
```

## Rollback

Use the previous git commit and recreate containers:

```bash
git log --oneline -5
git checkout <previous-good-commit>
docker compose build --no-cache api
docker compose up -d --force-recreate
bash scripts/smoke-test.sh
```

Return to the normal branch later:

```bash
git checkout main
git pull
docker compose build --no-cache api
docker compose up -d --force-recreate
```

## Teardown

Stop containers and keep data:

```bash
docker compose down
```

Delete containers and volumes, including local Postgres data:

```bash
docker compose down -v
```

Delete local images too:

```bash
docker compose down -v --rmi local
```

## Configuration Rules

The Dockerized API must use:

```env
GMAPS_SCRAPER_URL=http://gmaps-scraper:8080
```

Do not set it to `http://127.0.0.1:8080` for the API container. `127.0.0.1`
inside the API container means the API container itself, not the scraper.

Default host bindings are localhost-only:

```env
API_HOST_PORT=127.0.0.1:8000
DASHBOARD_HOST_PORT=127.0.0.1:3000
GMAPS_HOST_PORT=127.0.0.1:8080
POSTGRES_HOST_PORT=127.0.0.1:5432
```

For public traffic on a single VM, put Nginx or a GCP load balancer in front of
the app and keep the debug ports closed to the internet.

## Troubleshooting

Playwright executable missing:

```bash
docker compose build --no-cache api
docker compose up -d --force-recreate api
docker compose logs api --tail=100
```

API readiness failing:

```bash
curl -fsS http://127.0.0.1:8000/ready
docker compose logs api --tail=100
docker compose logs gmaps-scraper --tail=100
docker compose logs db --tail=100
```

Scraper not reachable:

```bash
docker compose ps gmaps-scraper
curl -fsS http://127.0.0.1:8080/api/docs | head
docker compose logs gmaps-scraper --tail=100
```

Database schema reminder:

```text
audits
businesses
discovery_jobs
niche_configs
pitches
scores
```

There is no `leads` table. Lead views query `businesses` with joined audit and
score data.
