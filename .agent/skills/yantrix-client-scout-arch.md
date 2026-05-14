# Skill: Yantrix Client Scout Architecture (yantrix-client-scout-arch)

## Project Overview
Yantrix Client Scout is an internal lead generation engine for Yantrix Labs. It discovers local businesses (via Google Maps, CSV, or JustDial), performs automated website audits using Playwright, scores the leads using LLMs (Groq/NVIDIA), and generates pitch-ready notes for the sales team to export to CRM (HubSpot/Zoho).

The core pipeline is:

`discover -> normalize -> persist -> audit -> score -> pitch -> export`

## Core Stack
*   **Backend:** FastAPI (Python 3.11+). Exposes REST APIs (`/run-scout`, `/audit-site`, `/leads`, `/configs`, `/export`).
*   **Frontend:** React, Vite, TanStack Router/Table. Runs locally or behind Nginx.
*   **Database:** PostgreSQL (Supabase-compatible schema), managed via Async SQLAlchemy.
*   **Deployment:** Oracle Cloud A1 Flex VM (ARM64) using Docker Compose.

## Key Services
1.  **Discovery Layer:**
    *   Primary: `gosom/google-maps-scraper` running as a Docker sidecar (REST API on port `8080`).
    *   Secondary: CSV uploads or optional JustDial Playwright crawlers.
2.  **Audit Worker (Playwright):**
    *   Visits discovered business websites using `async_playwright`.
    *   Checks for: mobile viewport meta tags, `<form>` elements, CTA buttons, WhatsApp links (`wa.me`), booking widgets (Calendly, etc.), SSL, and basic SEO tags.
3.  **LLM Scorer:**
    *   Primary: **Groq API** (Llama 3.3 70B).
    *   Fallback: **NVIDIA NIM API**.
    *   Applies configurable, niche-specific weighting to audit signals to generate a composite score (0-100).
    *   LLM output should enhance summaries and pitch notes, not replace deterministic scoring.
4.  **CRM Exporter:**
    *   Pushes qualified leads to HubSpot (Contacts/Deals) or Zoho CRM, or exports to JSON/CSV.

## Database Schema (Key Tables)
*   `discovery_jobs`: Tracks pipeline runs.
*   `businesses`: Core lead data (Name, City, Phone, Source). Unique on `(name, city, address)`.
*   `audits`: 1:1 with businesses. Stores binary signals (has_forms, mobile_friendly) and metrics.
*   `scores`: 1:1 with businesses. Stores composite scores and provider metadata.
*   `pitches`: AI-generated outreach notes that can be regenerated independently from scoring.
*   `niche_configs`: Niche-specific weight definitions and prompt customization.

## Product Boundaries
*   Collect public business information only.
*   Never collect end-customer PII or scrape authenticated/private areas.
*   Never bypass logins, CAPTCHAs, or access controls.

## API Expectations
Primary APIs should remain centered around:
*   `POST /api/v1/run-scout`
*   `POST /api/v1/audit-site`
*   `GET /api/v1/leads`
*   `GET /api/v1/leads/{id}`
*   `GET /api/v1/configs`
*   `PUT /api/v1/configs/{niche}`
*   `GET /api/v1/jobs`

## Agent Instructions
*   Always refer to `ARCHITECTURE.md` in the root for the definitive architecture diagram and schema definitions.
*   Use `CODEX_PROMPT.md` as the higher-level implementation brief when deciding tradeoffs.
*   When adding new features, ensure they fit into the async worker pipeline design (Discovery -> Audit -> Score -> Export).
*   When behavior is ambiguous, prefer correctness of lead data, reliability of the pipeline, and maintainability over feature sprawl.
