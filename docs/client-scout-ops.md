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

`city`, `category`, `niche`, `bucket`, `agency_fit_bucket`, `lead_status`,
`priority_rank`, `created_after`, `source`, `search`, `min_score`, `page`, and
`limit`.

Example:

```text
/api/v1/leads?niche=dental&city=Pune&bucket=high&created_after=2026-05-01T00:00:00Z&page=1&limit=25
```

## Smart lead fields

New runs now enrich leads with additive smart-lead fields where available:

- Contact: `contact_name`, `contact_title`, `contact_email`, `contact_phone`,
  `contact_linkedin_url`, `contact_confidence`
- Reliability: `rating`, `review_count`, `primary_language`,
  `has_recent_updates`, `budget_tier`, `reliability`
- Pain: `audit.pain_flags`, `audit.cms_detected`
- Agency fit: `agency_fit_score`, `agency_fit_bucket`, `opportunity_types`,
  `estimated_deal_value`

These fields are best-effort. Missing values should be treated as unknown, not
as pipeline failures.

## Mini-CRM workflow

Update lightweight sales fields:

```http
PATCH /api/v1/leads/{id}/sales
```

```json
{
  "lead_status": "contacted",
  "follow_up_at": "2026-05-20T10:00:00Z",
  "sales_notes": "Follow up Friday.",
  "priority_rank": 1,
  "assigned_to": "founder"
}
```

Record a manual outreach attempt:

```http
POST /api/v1/leads/{id}/contact-attempt
```

Lead statuses are `new`, `contacted`, `replied`, `meeting_set`,
`proposal_sent`, `won`, `lost`, and `ignored`.

## Daily action summary

`GET /api/v1/leads/summary` returns:

```json
{
  "followups_today": 4,
  "new_hot_leads": 12,
  "stale_contacted": 7
}
```

The dashboard shows this at the top of the Leads page.

## Manual outreach helpers

Lead detail responses include:

- `whatsapp_link`
- `email_subject`
- `email_body`

The dashboard uses these for **Send via WhatsApp** and **Copy email pitch**.
There is no email API integration yet.

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
