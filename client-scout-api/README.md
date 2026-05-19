# Client Scout API operations

## Google Maps CSV ingestion

Pre-scraped `gosom/google-maps-scraper` CSV exports can be ingested through the
same normalization and deduplication path used by live discovery. The script:

1. creates a `discovery_jobs` row with `source=csv`
2. parses the CSV into `GmapsRawBusiness` rows
3. calls `app.services.discovery.ingest_raw_businesses(...)`
4. attaches inserted businesses to the CSV discovery job
5. optionally runs audit, scoring, and pitch generation for the new businesses

Example for the repo-root `sioux_falls_dental.csv` mounted into the API
container at `/app/sioux_falls_dental.csv`:

```bash
docker exec -it clientscout-api python scripts/ingest_gmaps_csv.py \
  --file /app/sioux_falls_dental.csv \
  --niche dental \
  --city "Sioux Falls"
```

Run the full post-ingest pipeline:

```bash
docker exec -it clientscout-api python scripts/ingest_gmaps_csv.py \
  --file /app/sioux_falls_dental.csv \
  --niche dental \
  --city "Sioux Falls" \
  --run-audit \
  --run-score \
  --run-pitches
```

For a smaller test batch, add `--max-businesses 10`. The script prints a concise
summary with rows parsed, new businesses inserted, duplicates skipped, and the
created `job_id`.

## Scout job status API

`POST /api/v1/run-scout` creates a `discovery_jobs` row and returns immediately
with `job_id` and initial `status=running`. The pipeline continues in the
background using the existing discovery, audit, score, and pitch services.

Poll `GET /api/v1/jobs/{job_id}` to show job progress. The response includes
`total_discovered`, `total_audited`, `total_scored`, derived `total_pitched`,
and `last_updated_at`.

## Smart lead engine fields

Migration `004_smart_lead_engine.sql` adds nullable/default-safe fields for:

- person-level contact enrichment on `businesses`
- mini-CRM status, follow-up, attempts, and notes on `businesses`
- `pain_flags` and `cms_detected` on `audits`
- `agency_fit_score`, `agency_fit_bucket`, `opportunity_types`, and
  `estimated_deal_value` on `scores`

The existing score model remains compatible. `overall_score`, score breakdowns,
audit booleans, and lead routes are still present.

Useful endpoints:

```text
GET   /api/v1/leads/summary
PATCH /api/v1/leads/{id}/sales
POST  /api/v1/leads/{id}/contact-attempt
```
