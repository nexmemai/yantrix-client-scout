# Skill: Yantrix Backend Code Style (yantrix-backend-style)

## Tech Stack & Tooling
*   **Language:** Python 3.11+
*   **Framework:** FastAPI
*   **ORM:** SQLAlchemy 2.0 (Async mode with `asyncpg`)
*   **Validation:** Pydantic V2
*   **Formatter/Linter:** Ruff (`charliermarsh.ruff`)

## Directory Structure
Follow this standard FastAPI layout inside `client-scout-api/app/`:
*   `api/`: FastAPI routers and endpoint definitions. Keep logic light here.
*   `services/`: Core business logic, external API integrations, and scraping orchestrators.
*   `models/`: SQLAlchemy ORM classes (for example `business.py`, `audit.py`, `score.py`).
*   `schemas/`: Pydantic models for request/response validation.
*   Background task orchestration should live in service-layer modules or dedicated worker modules only when needed.

## Coding Patterns
1.  **Dependency Injection:**
    *   Use `Depends(get_db)` to inject database sessions into routes.
    *   Use `get_settings()` (which is `@lru_cache` wrapped) for all configuration access.
2.  **Async Everything:**
    *   Never use synchronous blocking calls (e.g., standard `requests`). Use `httpx` for HTTP calls.
    *   Use `async_playwright` for scraping.
    *   Database queries must use `await session.execute(select(...))`.
3.  **Error Handling:**
    *   Raise `fastapi.HTTPException` for client-facing errors (400, 404).
    *   For internal service failures (like LLM timeouts), catch exceptions, log them, and either retry or return a graceful degraded state. Do not crash the worker.
4.  **Logging:**
    *   Use the standard `logging` module. Configure it in `main.py`.
    *   Use structured, descriptive logs: `logger.info("Starting audit for %s", url)`.
5.  **Configuration:**
    *   No hardcoded secrets or tuning params. Everything goes through `pydantic-settings` in `config.py` and is loaded from `.env`.

## Delivery Rules
*   Reuse the existing repository structure unless there is a concrete reason to change it.
*   Treat discovery, audit, scoring, pitch generation, and export as separate pipeline stages with explicit boundaries.
*   When a change affects data contracts, update ORM models, Pydantic schemas, API responses, and tests together.
*   When a change affects runtime behavior, also update config, migrations, Docker assumptions, or docs as needed.

## Database Practices
*   Use UUIDs (`uuid.uuid4`) for all primary keys.
*   Always define relationships (`relationship(back_populates=...)`) properly in SQLAlchemy models.
*   Keep the schema compatible with Postgres and Supabase expectations.
*   Follow the active migration approach used by the repo and avoid introducing a new migration toolchain unless explicitly requested.

## Agent Instructions
*   Read `CODEX_PROMPT.md` and `ARCHITECTURE.md` when task scope or architecture intent is unclear.
*   Before writing code, verify imports match the project structure.
*   Ensure all new Python files run through the `ruff` formatter.
*   Keep route handlers concise; delegate complex logic to `services/`.
*   Default to production-leaning implementations rather than placeholders unless scaffolding is explicitly requested.
