# Skill: Oracle Cloud Deployment Checklist (yantrix-oracle-deploy)

## Target Environment
*   **Cloud Provider:** Oracle Cloud Infrastructure (OCI) Free Tier.
*   **Instance:** Compute A1 Flex VM.
*   **Architecture:** ARM64 (AArch64). *CRITICAL: All Docker images must support linux/arm64.*
*   **Resources:** 4 OCPUs, 24GB RAM.

## Architecture & Containerization
The deployment relies on `docker-compose.yml`.
1.  **FastAPI Backend:** Runs via Uvicorn. Memory limit: ~4GB.
2.  **PostgreSQL (Supabase Schema):** Official `postgres:16-alpine`. Uses mapped volume `pgdata`.
3.  **Google Maps Scraper:** `gosom/google-maps-scraper`. Uses mapped volume `gmapsdata`.
4.  **Dashboard (React):** Small internal dashboard, served statically or via dev server in Docker.
5.  **Reverse Proxy:** Nginx handling port 80/443, routing traffic to API (`:8000`) and Dashboard (`:3000`).

## Deployment Steps & Requirements
1.  **Environment Variables:**
    *   Never commit `.env`. Ensure a `.env` file is generated on the server from `.env.example`.
    *   Must populate `DB_PASSWORD`, `GROQ_API_KEY`, `NVIDIA_NIM_API_KEY`.
2.  **Docker Setup:**
    *   Install Docker Engine and Docker Compose plugin on Ubuntu 22.04.
    *   Ensure the `scout` user runs containers (non-root configuration in Dockerfiles).
3.  **Playwright Dependencies:**
    *   The FastAPI Dockerfile must install system dependencies for Chromium (`libnss3`, `libasound2`, etc.).
    *   Must run `playwright install chromium` inside the container build process.
    *   Keep browser concurrency tight because Playwright is one of the main RAM pressure sources on the VM.
4.  **Network & Security:**
    *   Oracle Cloud uses strict Ingress rules. Ensure ports 80, 443, and 8000 are open in the OCI Security List.
    *   Ensure UFW / iptables on the VM allow traffic on these ports.

## Agent Instructions
*   Read `CODEX_PROMPT.md` for product-level priorities before changing deployment assumptions.
*   When modifying `docker-compose.yml` or `Dockerfile`, always consider the 24GB RAM limit. Do not over-provision workers.
*   Remember that Playwright and Postgres are memory-hungry. Keep concurrency limits tight.
*   If diagnosing build failures on the server, check for ARM64 compatibility issues first.
*   Preserve the single-VM Docker Compose deployment model unless explicitly asked to redesign infrastructure.
