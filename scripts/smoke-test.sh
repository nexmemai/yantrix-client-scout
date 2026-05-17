#!/usr/bin/env bash
set -euo pipefail

# Yantrix Client Scout smoke test.
# Run from the repo root: bash scripts/smoke-test.sh

PASS=0
FAIL=0

pass() { printf 'PASS: %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf 'FAIL: %s\n' "$1"; FAIL=$((FAIL + 1)); }
warn() { printf 'WARN: %s\n' "$1"; }

API_HOST="${SMOKE_API_HOST:-127.0.0.1}"
API_PORT="${SMOKE_API_PORT:-8000}"
SCRAPER_HOST="${SMOKE_SCRAPER_HOST:-127.0.0.1}"
SCRAPER_PORT="${SMOKE_SCRAPER_PORT:-8080}"
NICHE="${SMOKE_NICHE:-dental}"
CITY="${SMOKE_CITY:-Jaipur}"
MAX_BUSINESSES="${SMOKE_MAX_BUSINESSES:-3}"

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        fail "required command not found: $1"
        exit 1
    fi
}

check_url() {
    local label="$1"
    local url="$2"
    if curl -fsS --max-time 10 "$url" >/tmp/client-scout-smoke.out 2>/tmp/client-scout-smoke.err; then
        pass "$label reachable"
        return 0
    fi
    fail "$label not reachable at $url"
    sed 's/^/    /' /tmp/client-scout-smoke.err || true
    return 1
}

require_cmd docker
require_cmd curl

printf '\nYantrix Client Scout smoke test\n\n'

printf '1. docker compose ps\n'
if docker compose ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'; then
    if docker compose ps --format '{{.Name}} {{.Status}}' | grep -q 'Up'; then
        pass "compose has running containers"
    else
        fail "compose has no running containers"
    fi
else
    fail "docker compose ps failed"
fi
printf '\n'

printf '2. scraper endpoint\n'
check_url "scraper docs" "http://${SCRAPER_HOST}:${SCRAPER_PORT}/api/docs" || true
printf '\n'

printf '3. API health and readiness\n'
HEALTH_RESPONSE="$(curl -fsS --max-time 10 "http://${API_HOST}:${API_PORT}/health" 2>/dev/null || true)"
READY_RESPONSE="$(curl -fsS --max-time 10 "http://${API_HOST}:${API_PORT}/ready" 2>/dev/null || true)"
if printf '%s' "$HEALTH_RESPONSE" | grep -q '"status":"ok"'; then
    pass "API /health ok"
else
    fail "API /health failed: ${HEALTH_RESPONSE:-empty response}"
fi
if printf '%s' "$READY_RESPONSE" | grep -q '"status":"ready"'; then
    pass "API /ready ok"
else
    fail "API /ready failed: ${READY_RESPONSE:-empty response}"
fi
printf '\n'

printf '4. database connectivity\n'
if docker compose ps -q db >/tmp/client-scout-db.cid && [ -s /tmp/client-scout-db.cid ]; then
    DB_READY_CMD='pg_isready -U "${POSTGRES_USER:-scout}" -d "${POSTGRES_DB:-clientscout}"'
    if docker compose exec -T db sh -lc "$DB_READY_CMD" >/dev/null 2>&1; then
        pass "local Postgres is ready"
    else
        fail "local Postgres pg_isready failed"
    fi
else
    warn "db service is not running; relying on API readiness for external DB"
    if printf '%s' "$READY_RESPONSE" | grep -q '"db":true'; then
        pass "API reports DB ready"
    else
        fail "API does not report DB ready"
    fi
fi
printf '\n'

printf '5. Playwright browser launch inside api container\n'
PW_CHECK="$(docker compose exec -T api python - <<'PY' 2>&1
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    page = browser.new_page()
    page.goto("data:text/html,<title>ok</title>")
    print(page.title())
    browser.close()
PY
)"
if printf '%s' "$PW_CHECK" | grep -q '^ok$'; then
    pass "Playwright Chromium launches inside api"
else
    fail "Playwright Chromium failed inside api"
    printf '%s\n' "$PW_CHECK" | sed 's/^/    /'
fi
printf '\n'

printf '6. sample run-scout request\n'
SCOUT_RESPONSE="$(curl -fsS --max-time 240 \
    -X POST "http://${API_HOST}:${API_PORT}/api/v1/run-scout" \
    -H "Content-Type: application/json" \
    -d "{\"niche\":\"${NICHE}\",\"city\":\"${CITY}\",\"depth\":1,\"max_businesses\":${MAX_BUSINESSES},\"auto_audit\":true,\"auto_score\":true,\"auto_pitch\":true}" \
    2>/tmp/client-scout-smoke.err || true)"

if printf '%s' "$SCOUT_RESPONSE" | grep -q '"status":"completed"'; then
    pass "run-scout completed"
    printf '    %s\n' "$SCOUT_RESPONSE" | cut -c 1-500
elif printf '%s' "$SCOUT_RESPONSE" | grep -q '"status":"failed"'; then
    fail "run-scout returned failed"
    printf '    %s\n' "$SCOUT_RESPONSE" | cut -c 1-500
else
    fail "run-scout request failed or returned unexpected response"
    sed 's/^/    /' /tmp/client-scout-smoke.err || true
    printf '    %s\n' "${SCOUT_RESPONSE:-empty response}" | cut -c 1-500
fi
printf '\n'

printf 'Results: %d passed, %d failed\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
