"""
main.py - FastAPI application factory.

The API validates critical runtime dependencies during startup so Docker
readiness reflects a usable service, not just a running process.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import audit_site, configs, export, jobs, leads, reports, run_scout
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

STARTUP_CHECKS: dict[str, bool] = {
    "db": False,
    "playwright": False,
    "scraper": False,
}


async def _check_db() -> bool:
    """Verify the database is reachable."""
    from sqlalchemy import text

    from app.database import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("[STARTUP] db connectivity ok")
        return True
    except Exception as exc:
        logger.critical("[STARTUP] db connectivity failed: %s", exc)
        return False


async def _check_playwright() -> bool:
    """Verify the Playwright Chromium binary can launch."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            await browser.close()

        logger.info("[STARTUP] playwright chromium launch ok")
        return True
    except Exception as exc:
        logger.critical("[STARTUP] playwright chromium launch failed: %s", exc)
        return False


async def _check_scraper() -> bool:
    """Verify the GMaps scraper sidecar is reachable."""
    import httpx

    url = settings.GMAPS_SCRAPER_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url}/api/docs")
            resp.raise_for_status()
        logger.info("[STARTUP] gmaps scraper reachable at %s", url)
        return True
    except Exception as exc:
        logger.critical("[STARTUP] gmaps scraper unreachable at %s: %s", url, exc)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Fail fast when DB, scraper, or Playwright are not ready."""
    logger.info("[STARTUP] %s v%s starting", settings.APP_NAME, settings.APP_VERSION)
    STARTUP_CHECKS.update({"db": False, "playwright": False, "scraper": False})

    db_ok = await _check_db()
    STARTUP_CHECKS["db"] = db_ok
    if not db_ok:
        raise RuntimeError(
            "Cannot start: database is unreachable. "
            "Check DB_HOST, DB_PORT, DB_USER, and DB_PASSWORD in .env."
        )

    pw_ok = await _check_playwright()
    STARTUP_CHECKS["playwright"] = pw_ok
    if not pw_ok:
        raise RuntimeError(
            "Cannot start: Playwright Chromium is unavailable. "
            "Rebuild the API image with: docker compose build --no-cache api"
        )

    scraper_ok = await _check_scraper()
    STARTUP_CHECKS["scraper"] = scraper_ok
    if not scraper_ok:
        raise RuntimeError(
            "Cannot start: GMaps scraper is unreachable. "
            "The Dockerized API must use GMAPS_SCRAPER_URL=http://gmaps-scraper:8080."
        )

    logger.info("[STARTUP] %s v%s ready", settings.APP_NAME, settings.APP_VERSION)
    yield
    logger.info("[SHUTDOWN] %s cleaning up", settings.APP_NAME)
    # Close ARQ pool + pub/sub Redis client created lazily by app.workers.queue.
    # Done in the shutdown half of the lifespan so connections drain before
    # uvicorn returns control to the orchestrator.
    try:
        from app.workers.queue import close_queue_clients

        await close_queue_clients()
    except Exception as exc:  # noqa: BLE001 - shutdown must succeed
        logger.warning("[SHUTDOWN] queue client teardown failed: %s", exc)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Internal lead-gen engine for Yantrix Labs. Discovers local "
            "businesses, audits their websites, scores them with configurable "
            "weights, and generates outreach notes via Groq or NVIDIA NIM."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get(
        "/health",
        tags=["System"],
        summary="Liveness check",
        description="Returns 200 OK when the API process is up.",
    )
    async def health() -> JSONResponse:
        return JSONResponse(
            content={
                "status": "ok",
                "service": settings.APP_NAME,
                "version": settings.APP_VERSION,
            }
        )

    @app.get(
        "/ready",
        tags=["System"],
        summary="Readiness check",
        description="Returns 200 OK only after startup dependency checks pass.",
    )
    async def ready() -> JSONResponse:
        ready_status = all(STARTUP_CHECKS.values())
        return JSONResponse(
            status_code=200 if ready_status else 503,
            content={
                "status": "ready" if ready_status else "not_ready",
                "checks": STARTUP_CHECKS,
            },
        )

    prefix = "/api/v1"
    app.include_router(run_scout.router, prefix=prefix)
    app.include_router(audit_site.router, prefix=prefix)
    app.include_router(leads.router, prefix=prefix)
    app.include_router(configs.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)
    app.include_router(export.router, prefix=prefix)
    app.include_router(reports.router, prefix=prefix)

    return app


app = create_app()
