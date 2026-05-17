"""
main.py — FastAPI application factory.

Responsibilities:
- Create the FastAPI app with metadata for OpenAPI/Swagger docs
- Register CORS middleware
- Mount all API routers under /api/v1
- Expose /health endpoint
- Handle startup/shutdown lifecycle via lifespan context
- Validate critical dependencies on startup (DB, Playwright, scraper)
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api import audit_site, configs, export, jobs, leads, reports, run_scout

settings = get_settings()
logger = logging.getLogger(__name__)


# ── Startup dependency checks ─────────────────────────────────────────────────

async def _check_db() -> bool:
    """Verify the database is reachable. Returns True on success."""
    from app.database import engine
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("[STARTUP] ✓ Database connectivity OK")
        return True
    except Exception as exc:
        logger.critical("[STARTUP] ✗ Database connectivity FAILED: %s", exc)
        return False


async def _check_playwright() -> bool:
    """Verify Playwright Chromium binary is available. Returns True on success."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            await browser.close()

        logger.info("[STARTUP] ✓ Playwright Chromium OK")
        return True
    except Exception as exc:
        logger.critical("[STARTUP] ✗ Playwright Chromium FAILED: %s", exc)
        return False


async def _check_scraper() -> bool:
    """Verify the GMaps scraper sidecar is reachable. Returns True on success."""
    import httpx

    url = settings.GMAPS_SCRAPER_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url}/api/v1/jobs")
            resp.raise_for_status()
        logger.info("[STARTUP] ✓ GMaps scraper reachable at %s", url)
        return True
    except Exception as exc:
        logger.warning("[STARTUP] ⚠ GMaps scraper not reachable at %s: %s", url, exc)
        return False


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup and shutdown hooks.
    Validates DB, Playwright, and scraper connectivity on boot.
    Fails fast if DB or Playwright are unavailable.
    """
    logger.info("[STARTUP] %s v%s starting...", settings.APP_NAME, settings.APP_VERSION)

    # ── Critical checks (fail fast) ───────────────────────────────────────
    db_ok = await _check_db()
    if not db_ok:
        raise RuntimeError(
            "Cannot start: database is unreachable. "
            "Check DB_HOST, DB_PORT, DB_USER, DB_PASSWORD in .env"
        )

    pw_ok = await _check_playwright()
    if not pw_ok:
        raise RuntimeError(
            "Cannot start: Playwright Chromium binary is missing. "
            "Rebuild the API image: docker compose build --no-cache api"
        )

    # ── Non-critical check (warn only) ────────────────────────────────────
    await _check_scraper()

    logger.info("[STARTUP] %s v%s ready", settings.APP_NAME, settings.APP_VERSION)
    yield
    logger.info("[SHUTDOWN] %s cleaning up...", settings.APP_NAME)


# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Internal lead-gen engine for Yantrix Labs. "
            "Discovers local businesses, audits their websites, "
            "scores them with configurable weights, and generates "
            "pitch-ready outreach notes via Groq / NVIDIA NIM."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health check ──────────────────────────────────────────────────────
    @app.get(
        "/health",
        tags=["System"],
        summary="Health check",
        description="Returns 200 OK when the API is up. Used by load balancers and Docker HEALTHCHECK.",
    )
    async def health() -> JSONResponse:
        return JSONResponse(
            content={
                "status": "ok",
                "service": settings.APP_NAME,
                "version": settings.APP_VERSION,
            }
        )

    # ── API v1 routers ────────────────────────────────────────────────────
    PREFIX = "/api/v1"

    app.include_router(run_scout.router, prefix=PREFIX)
    app.include_router(audit_site.router, prefix=PREFIX)
    app.include_router(leads.router, prefix=PREFIX)
    app.include_router(configs.router, prefix=PREFIX)
    app.include_router(jobs.router, prefix=PREFIX)
    app.include_router(export.router, prefix=PREFIX)
    app.include_router(reports.router, prefix=PREFIX)

    return app


app = create_app()
