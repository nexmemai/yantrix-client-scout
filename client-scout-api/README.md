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
