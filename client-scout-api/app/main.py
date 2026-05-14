"""
main.py — FastAPI application factory.

Responsibilities:
- Create the FastAPI app with metadata for OpenAPI/Swagger docs
- Register CORS middleware
- Mount all API routers under /api/v1
- Expose /health endpoint
- Handle startup/shutdown lifecycle via lifespan context
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api import audit_site, configs, export, jobs, leads, run_scout

settings = get_settings()


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup and shutdown hooks.
    Phase 2+: initialise DB connection pool, warm up Playwright browser pool.
    """
    print(f"[START] {settings.APP_NAME} v{settings.APP_VERSION} starting...")
    # TODO (Phase 2): await database engine.connect(); run pending migrations
    # TODO (Phase 3): initialise Playwright browser pool
    yield
    print("[STOP] Shutting down - cleaning up resources...")
    # TODO: close DB pool, close Playwright browsers


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

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health check ──────────────────────────────────────────────────────────
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

    # ── API v1 routers ────────────────────────────────────────────────────────
    PREFIX = "/api/v1"

    app.include_router(run_scout.router, prefix=PREFIX)
    app.include_router(audit_site.router, prefix=PREFIX)
    app.include_router(leads.router, prefix=PREFIX)
    app.include_router(configs.router, prefix=PREFIX)
    app.include_router(jobs.router, prefix=PREFIX)
    app.include_router(export.router, prefix=PREFIX)

    return app


app = create_app()
