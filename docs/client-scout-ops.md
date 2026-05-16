# Yantrix Client Scout Operator Guide

> **Note**: For new setups, prefer Google Cloud (GCP) e2-medium instructions in `docs/gcp-compute-setup.md`; AWS and Oracle notes are legacy.
## Run a scout job

`POST /api/v1/run-scout` starts discovery, audit, scoring, and pitch generation.

```json
{
  "niche": "dental",
  "city": "Jaipur",
  "depth": 1,
  "max_businesses": 25,
  "auto_audit": true,
  "auto_score": true,
  "auto_pitch": true,
  "pitch_tone": "professional"
}
```

`max_businesses` must be `100` or lower. Runs are also capped per niche and city by `RUN_SCOUT_HOURLY_LIMIT`.

## Filter leads

`GET /api/v1/leads` supports pagination plus composable filters:

`city`, `category`, `niche`, `bucket`, `created_after`, `source`, `search`, `min_score`, `page`, and `limit`.

Example:

```text
/api/v1/leads?niche=dental&city=Pune&bucket=high&created_after=2026-05-01T00:00:00Z&page=1&limit=25
```

## Export data

`POST /api/v1/export` exports matching leads as CSV or JSON.

```json
{
  "niche": "dental",
  "city": "Jaipur",
  "bucket": "high",
  "score_min": 60,
  "format": "csv"
}
```

For JSON, set `"format": "json"`. CSV returns `text/csv`; JSON returns an array with the same lead fields.

## Send a webhook

`POST /api/v1/leads/{id}/webhook` sends the lead payload and latest pitch to a CRM/webhook URL.

The URL comes from the request query/body parameter `webhook_url` when supplied, then the lead-level `webhook_url`, then `LEAD_WEBHOOK_DEFAULT_URL`. Delivery status is stored on the business as `last_sync_at` and `last_sync_status`.

## Open a report

Open `/api/v1/reports/{business_id}` in a browser. The report shows business basics, audit findings, score breakdown, the current pitch, and 3-5 Yantrix Labs automation recommendations based on the audit gaps and score bucket.
