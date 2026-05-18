"""
services/gmaps_client.py — Async HTTP client for the gosom/google-maps-scraper REST API.

Gosom runs as a Docker sidecar exposing:
  POST   /api/v1/jobs             – submit a new scrape job
  GET    /api/v1/jobs/{id}        – poll job status
  GET    /api/v1/jobs/{id}/download – download results as CSV

Docs: http://<scraper-host>:8080/api/docs
"""

import asyncio
import csv
import io
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class GmapsRawBusiness:
    """Normalised subset of the gosom CSV row we care about."""

    input_id: str
    title: str
    category: str | None
    address: str | None
    city: str | None
    phone: str | None
    website: str | None
    google_maps_url: str | None
    rating: float | None
    review_count: int | None
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

# Column names returned by gosom's CSV download endpoint.
# Run `GET /api/v1/jobs/{id}/download` to see the exact headers.
_GOSOM_CSV_COLUMNS = {
    "input_id": "input_id",
    "link": "link",           # Google Maps URL
    "title": "title",
    "category": "category",
    "address": "address",
    "phone": "phone",
    "website": "website",
    "rating": "rating",
    "reviews_count": "reviews_count",
}


class GmapsScraperClient:
    """
    Thin async wrapper around the gosom REST API.

    Usage:
        client = GmapsScraperClient()
        job_id = await client.submit_job("dental clinics in Pune")
        results = await client.wait_for_results(job_id)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.GMAPS_SCRAPER_URL.rstrip("/")
        self._timeout = httpx.Timeout(60.0, read=300.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit_job(self, query: str, depth: int = 1) -> str:
        """
        Submit a scraping job.
        Returns the job ID string.

        :param query: Human-readable search string, e.g. "dental clinics in Pune"
        :param depth: Pagination depth (1 = first page only; increase for more results)
        """
        payload = {
            "name": f"scout_{query[:40].replace(' ', '_')}",
            "keywords": [query],
            "lang": "en",
            "depth": depth,
            "max_time": 180,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/api/v1/jobs", json=payload)
            resp.raise_for_status()
            data = resp.json()
            job_id: str = data["id"]
            logger.info("Submitted gosom job %s for query: %r", job_id, query)
            return job_id

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Return the raw job status dict from the gosom API."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/api/v1/jobs/{job_id}")
            resp.raise_for_status()
            return resp.json()

    async def download_results_csv(self, job_id: str) -> list[GmapsRawBusiness]:
        """Download and parse the CSV results for a completed job."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/api/v1/jobs/{job_id}/download")
            resp.raise_for_status()
            return parse_gmaps_csv(resp.text)

    async def wait_for_results(
        self,
        job_id: str,
        poll_interval: float = 15.0,
        max_wait: float = 900.0,
    ) -> list[GmapsRawBusiness]:
        """
        Poll until the job is complete, then return parsed results.

        :raises TimeoutError: if the job does not complete within max_wait seconds.
        :raises RuntimeError: if the job fails.
        """
        elapsed = 0.0
        while elapsed < max_wait:
            try:
                status = await self.get_job_status(job_id)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                # Transient HTTP / network error — log and retry on next tick
                logger.warning(
                    "Transient error polling job %s (%.0fs elapsed): %s",
                    job_id, elapsed, exc,
                )
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                continue

            # Guard against non-dict / malformed responses
            if not isinstance(status, dict):
                logger.warning(
                    "Unexpected non-dict status response for job %s: %r",
                    job_id, status,
                )
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                continue

            # Normalise: accept both "Status" and "status" keys; coerce to str
            raw_state = status.get("status") or status.get("Status") or ""
            state: str = str(raw_state).strip().lower()
            logger.debug("Job %s status: %s (%.0fs elapsed)", job_id, state, elapsed)

            if state in ("completed", "ok"):
                return await self.download_results_csv(job_id)
            if state in ("failed", "cancelled", "error"):
                raise RuntimeError(f"Gosom job {job_id} ended with status: {state}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"Gosom job {job_id} did not complete within {max_wait}s")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_csv(raw_csv: str) -> list[GmapsRawBusiness]:
        return parse_gmaps_csv(raw_csv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_gmaps_csv(raw_csv: str) -> list[GmapsRawBusiness]:
    """Parse a gosom/google-maps-scraper CSV blob into raw business DTOs."""
    results: list[GmapsRawBusiness] = []
    reader = csv.DictReader(io.StringIO(raw_csv))

    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")

    for row in reader:
        try:
            rating_str = row.get("rating", "").strip()
            rating = float(rating_str) if rating_str else None

            reviews_str = row.get("reviews_count", "").strip()
            review_count = int(reviews_str) if reviews_str else None

            address = row.get("address", "").strip() or None
            city = _extract_city(address)

            results.append(
                GmapsRawBusiness(
                    input_id=row.get("input_id", ""),
                    title=row.get("title", "").strip(),
                    category=row.get("category", "").strip() or None,
                    address=address,
                    city=city,
                    phone=row.get("phone", "").strip() or None,
                    website=row.get("website", "").strip() or None,
                    google_maps_url=row.get("link", "").strip() or None,
                    rating=rating,
                    review_count=review_count,
                    raw=dict(row),
                )
            )
        except Exception as exc:  # noqa: BLE001 - log and continue on bad row
            logger.warning("Failed to parse gosom row: %s - %s", row, exc)

    logger.info("Parsed %d businesses from gosom CSV", len(results))
    return results


def _extract_city(address: str | None) -> str | None:
    """
    Heuristic: the city is typically the second-to-last comma-separated segment.
    Example: "123 MG Road, Koregaon Park, Pune, Maharashtra 411001, India"
             → "Pune"
    """
    if not address:
        return None
    parts = [p.strip() for p in address.split(",")]
    # We want the part before "State PINCODE"
    if len(parts) >= 3:
        # Third-from-last usually contains "City"
        return parts[-3].strip() or None
    if len(parts) >= 2:
        return parts[-2].strip() or None
    return None
