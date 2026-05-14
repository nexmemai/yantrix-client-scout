# scrapers/

This directory contains the Google Maps scraper sidecar configuration.

## How it works

The `gosom/google-maps-scraper` Docker image is run in **Web UI / REST API mode**.
It exposes a full REST API on port `8080` for our FastAPI backend to call.

## Endpoints used by the backend

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/jobs` | Submit a new scraping job |
| GET | `/api/v1/jobs/{id}` | Poll job status |
| GET | `/api/v1/jobs/{id}/download` | Download CSV results |

## Running standalone (dev)

```bash
docker compose -f docker-compose.scraper.yml up -d
```

Then access the Web UI at http://localhost:8080
