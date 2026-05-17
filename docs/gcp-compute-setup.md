# Yantrix Client Scout on GCP Compute Engine

This guide targets one reliable, budget-conscious VM first. No Kubernetes is
required.

## 1. Create the VM

Recommended starter VM:

- Machine type: `e2-medium` or larger
- OS: Ubuntu 24.04 LTS or 22.04 LTS
- Disk: 30 GB minimum
- Firewall: allow HTTP/HTTPS only if you plan to put Nginx or a load balancer in front

Keep debug ports `8000`, `8080`, and `5432` closed publicly. The Compose defaults
bind them to `127.0.0.1`.

## 2. Install Docker

```bash
sudo apt update
sudo apt install -y git ca-certificates curl
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker "$USER"
exit
```

SSH back into the VM after logging out so the Docker group is active.

## 3. Clone and Configure

```bash
git clone https://github.com/nexmemai/yantrix-client-scout.git ~/yantrix-client-scout
cd ~/yantrix-client-scout
cp .env.example .env
nano .env
```

Use these production-safe single-VM values:

```env
COMPOSE_PROJECT_NAME=yantrix-client-scout

API_HOST_PORT=127.0.0.1:8000
DASHBOARD_HOST_PORT=127.0.0.1:3000
GMAPS_HOST_PORT=127.0.0.1:8080
POSTGRES_HOST_PORT=127.0.0.1:5432

GMAPS_SCRAPER_URL=http://gmaps-scraper:8080

DB_HOST=db
DB_PORT=5432
DB_NAME=clientscout
DB_USER=scout
DB_PASSWORD=<pick-a-strong-password>

AUDIT_CONCURRENCY=3
SCRAPER_CONCURRENCY=2
```

Important: do not set `GMAPS_SCRAPER_URL` to `http://127.0.0.1:8080` for the
Dockerized API. Compose also pins the API container to
`http://gmaps-scraper:8080` so stale shell exports do not override it.

## 4. Build and Start

```bash
docker compose build --no-cache api
docker compose up -d
docker compose ps
```

The API image installs Playwright Chromium during build. No manual
`playwright install` step is needed after startup.

## 5. Verify

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
bash scripts/smoke-test.sh
```

## 6. Public Access

The safest low-cost setup is:

- Keep Compose debug ports on `127.0.0.1`
- Expose only ports `80` and `443` publicly
- Proxy public traffic through Nginx or a GCP load balancer

For a temporary direct API debug session only, you can change:

```env
API_HOST_PORT=0.0.0.0:8000
```

Then recreate:

```bash
docker compose up -d --force-recreate api
```

Change it back to `127.0.0.1:8000` when done.

## 7. Ongoing Operations

Common commands:

```bash
git pull
docker compose build --no-cache api
docker compose up -d --force-recreate api
bash scripts/smoke-test.sh
docker compose logs api --tail=100 -f
```

Full runbook:

```bash
less scripts/runbook.md
```

## 8. Current Failure Anchor

If the running API container reports:

```text
BrowserType.launch: Executable doesn't exist at /home/scout/.cache/ms-playwright/...
```

the running container is using a stale or incomplete API image. Apply the repo
fix by rebuilding and recreating the container:

```bash
git pull
docker compose build --no-cache api
docker compose up -d --force-recreate api
docker compose exec -T api python - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    print("playwright ok")
    browser.close()
PY
bash scripts/smoke-test.sh
```

## 9. Rollback and Teardown

Rollback:

```bash
git log --oneline -5
git checkout <previous-good-commit>
docker compose build --no-cache api
docker compose up -d --force-recreate
bash scripts/smoke-test.sh
```

Stop but keep data:

```bash
docker compose down
```

Delete containers and volumes, including local Postgres data:

```bash
docker compose down -v
```
