#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Yantrix Client Scout — Smoke Test
# Run from the repo root: bash scripts/smoke-test.sh
# Exits non-zero on any failure.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS=0
FAIL=0

pass() { echo -e "${GREEN}✓ PASS${NC}: $1"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}✗ FAIL${NC}: $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "${YELLOW}⚠ WARN${NC}: $1"; }

# ── Configurable test payload ────────────────────────────────────────────────
NICHE="${SMOKE_NICHE:-dental}"
CITY="${SMOKE_CITY:-Jaipur}"
API_HOST="${SMOKE_API_HOST:-127.0.0.1}"
API_PORT="${SMOKE_API_PORT:-8000}"
SCRAPER_HOST="${SMOKE_SCRAPER_HOST:-127.0.0.1}"
SCRAPER_PORT="${SMOKE_SCRAPER_PORT:-8080}"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Yantrix Client Scout — Smoke Test"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── 1. Docker Compose status ─────────────────────────────────────────────────
echo "── 1. Docker Compose containers ──"
if docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null | grep -q "Up"; then
    docker compose ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null
    pass "Docker Compose containers are running"
else
    fail "Docker Compose containers are not running"
fi
echo ""

# ── 2. GMaps Scraper ─────────────────────────────────────────────────────────
echo "── 2. GMaps Scraper (${SCRAPER_HOST}:${SCRAPER_PORT}) ──"
if curl -fsS --max-time 5 "http://${SCRAPER_HOST}:${SCRAPER_PORT}/api/docs" > /dev/null 2>&1; then
    pass "Scraper API docs reachable"
else
    fail "Scraper API docs NOT reachable at http://${SCRAPER_HOST}:${SCRAPER_PORT}/api/docs"
fi
echo ""

# ── 3. API Health ────────────────────────────────────────────────────────────
echo "── 3. API Health (${API_HOST}:${API_PORT}) ──"
HEALTH_RESPONSE=$(curl -fsS --max-time 5 "http://${API_HOST}:${API_PORT}/health" 2>/dev/null || echo "UNREACHABLE")
if echo "$HEALTH_RESPONSE" | grep -q '"status":"ok"'; then
    pass "API health endpoint OK"
    echo "    Response: ${HEALTH_RESPONSE}"
else
    fail "API health endpoint FAILED"
    echo "    Response: ${HEALTH_RESPONSE}"
fi
echo ""

# ── 4. Database connectivity ─────────────────────────────────────────────────
echo "── 4. Database connectivity ──"
DB_CONTAINER=$(docker compose ps --format '{{.Name}}' 2>/dev/null | grep -E "db$|clientscout-db" | head -1)
if [ -n "$DB_CONTAINER" ]; then
    if docker exec "$DB_CONTAINER" pg_isready -U scout -d clientscout > /dev/null 2>&1; then
        pass "Database (local) is ready"
    else
        fail "Database container exists but pg_isready failed"
    fi
else
    # No local DB container — check if the API can reach its configured DB
    if echo "$HEALTH_RESPONSE" | grep -q '"status":"ok"'; then
        pass "Database connectivity (external) — API is healthy, so DB is reachable"
    else
        warn "No local DB container found and API is not healthy — cannot verify DB"
    fi
fi
echo ""

# ── 5. Playwright check ─────────────────────────────────────────────────────
echo "── 5. Playwright browser in API container ──"
API_CONTAINER=$(docker compose ps --format '{{.Name}}' 2>/dev/null | grep -E "api$|clientscout-api" | head -1)
if [ -n "$API_CONTAINER" ]; then
    PW_CHECK=$(docker exec "$API_CONTAINER" python -c "
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
b = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
b.close()
p.stop()
print('OK')
" 2>&1)
    if echo "$PW_CHECK" | grep -q "OK"; then
        pass "Playwright Chromium launches successfully inside the API container"
    else
        fail "Playwright Chromium failed inside the API container"
        echo "    Output: ${PW_CHECK}"
    fi
else
    fail "API container not found — cannot check Playwright"
fi
echo ""

# ── 6. Sample run-scout request ──────────────────────────────────────────────
echo "── 6. Sample run-scout (niche=${NICHE}, city=${CITY}) ──"
SCOUT_RESPONSE=$(curl -fsS --max-time 120 \
    -X POST "http://${API_HOST}:${API_PORT}/api/v1/run-scout" \
    -H "Content-Type: application/json" \
    -d "{\"niche\":\"${NICHE}\",\"city\":\"${CITY}\",\"depth\":1,\"max_businesses\":3,\"auto_audit\":true,\"auto_score\":true,\"auto_pitch\":true}" \
    2>/dev/null || echo "REQUEST_FAILED")

if echo "$SCOUT_RESPONSE" | grep -q '"status":"completed"'; then
    pass "run-scout returned status=completed"
    # Extract key metrics
    DISCOVERED=$(echo "$SCOUT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('discovered',0))" 2>/dev/null || echo "?")
    AUDITED=$(echo "$SCOUT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('audited',0))" 2>/dev/null || echo "?")
    SCORED=$(echo "$SCOUT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('scored',0))" 2>/dev/null || echo "?")
    PITCHED=$(echo "$SCOUT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('pitched',0))" 2>/dev/null || echo "?")
    echo "    Discovered: ${DISCOVERED} | Audited: ${AUDITED} | Scored: ${SCORED} | Pitched: ${PITCHED}"
elif echo "$SCOUT_RESPONSE" | grep -q '"status":"failed"'; then
    fail "run-scout returned status=failed"
    MSG=$(echo "$SCOUT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('message',''))" 2>/dev/null || echo "")
    echo "    Message: ${MSG}"
else
    fail "run-scout request failed or returned unexpected response"
    echo "    Response: ${SCOUT_RESPONSE:0:500}"
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════"
echo -e "  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
echo "═══════════════════════════════════════════════════════════════"
echo ""

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
