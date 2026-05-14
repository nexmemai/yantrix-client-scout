"""
config.py — Centralised settings loaded from environment variables.

All secrets and tunable parameters live in .env (never committed).
Use `Settings()` anywhere via the cached `get_settings()` dependency.
"""

from functools import lru_cache
from typing import List

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

    # ── CORS ─────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins, e.g. http://localhost:3000
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

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

    # ── Worker concurrency ────────────────────────────────────────────
    AUDIT_CONCURRENCY: int = 5   # max parallel Playwright browsers
    SCRAPER_CONCURRENCY: int = 2  # max parallel JustDial crawlers

    # ── JustDial (optional, feature-flagged) ─────────────────────────
    JUSTDIAL_ENABLED: bool = False


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call once per process, reuse everywhere."""
    return Settings()
