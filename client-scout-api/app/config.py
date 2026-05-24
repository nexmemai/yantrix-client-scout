"""
config.py — Centralised settings loaded from environment variables.

All secrets and tunable parameters live in .env (never committed).
Use `Settings()` anywhere via the cached `get_settings()` dependency.
"""

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────
    APP_NAME: str = "Yantrix Client Scout API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Comma-separated list of allowed origins, e.g. http://localhost:3000
    CORS_ORIGINS: List[str] | str = ["http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, str):
            import json
            return json.loads(v)
        return v

    # ── Database ─────────────────────────────────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "clientscout"
    DB_USER: str = "scout"
    DB_PASSWORD: str = "changeme"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ── Google Maps Scraper sidecar ───────────────────────────────────
    GMAPS_SCRAPER_URL: str = "http://gmaps-scraper:8080"

    # ── LLM Providers ────────────────────────────────────────────────
    LLM_PROVIDER: str = "nvidia"  # nvidia | groq
    LLM_API_KEY: str = ""
    LLM_MODEL_NAME: str = ""
    LLM_MAX_RETRIES: int = 3
    LLM_TIMEOUT_SECONDS: float = 30.0

    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    NVIDIA_NIM_API_KEY: str = ""
    NVIDIA_NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_NIM_MODEL: str = "meta/llama-3.3-70b-instruct"

    # ── Google PageSpeed Insights ─────────────────────────────────────
    PSI_API_KEY: str = ""  # optional — leave empty to skip PSI checks

    # ── CRM ──────────────────────────────────────────────────────────
    HUBSPOT_ACCESS_TOKEN: str = ""
    ZOHO_CLIENT_ID: str = ""
    ZOHO_CLIENT_SECRET: str = ""
    ZOHO_REFRESH_TOKEN: str = ""
    LEAD_WEBHOOK_DEFAULT_URL: str = ""
    RUN_SCOUT_HOURLY_LIMIT: int = 10

    # ── Redis / ARQ queue ────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"
    # Maximum jobs a single ARQ worker process executes concurrently.
    # On Oracle A1 (4 OCPU, 24 GB) 8 is a safe default; raise it if you have
    # CPU headroom and Playwright RSS is bounded.
    WORKER_MAX_JOBS: int = 8
    # Hard ceiling per task. Discovery + audit + score + pitch in one go on a
    # 100-lead batch typically finishes in 15-25 minutes; 30 minutes leaves
    # headroom for transient slowness without orphaning the entire run.
    WORKER_JOB_TIMEOUT_SECONDS: int = 30 * 60
    # How often a running task writes `last_heartbeat = now()` on its job row.
    WORKER_HEARTBEAT_INTERVAL_SECONDS: int = 15
    # Reaper threshold. Any DiscoveryJob in `running` state whose heartbeat is
    # older than this is presumed dead and flipped to `failed`.
    WORKER_STALE_JOB_THRESHOLD_SECONDS: int = 5 * 60

    # ── Worker concurrency ────────────────────────────────────────────
    AUDIT_CONCURRENCY: int = 5   # max parallel Playwright browsers
    SCRAPER_CONCURRENCY: int = 2  # max parallel JustDial crawlers

    # ── Snapshot storage ──────────────────────────────────────────────
    SNAPSHOT_BACKEND: str = "local"
    SNAPSHOT_DIR: str = "/app/snapshots"

    # ── JustDial (optional, feature-flagged) ─────────────────────────
    JUSTDIAL_ENABLED: bool = False


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call once per process, reuse everywhere."""
    return Settings()
