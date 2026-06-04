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
import os
import re
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
# Custom exceptions
# ---------------------------------------------------------------------------


class GosomJobStuckPendingError(RuntimeError):
    """Raised when a gosom job remains in `pending` state past a threshold.

    Carries the gosom job ID so callers and log aggregators can correlate
    with scraper-side logs without parsing the message string.
    """

    def __init__(self, job_id: str, elapsed: float, last_status: dict[str, Any]) -> None:
        self.job_id = job_id
        self.elapsed = elapsed
        self.last_status = last_status
        super().__init__(
            f"Gosom job {job_id} stuck in 'pending' for {elapsed:.0f}s. "
            f"Scraper may have failed to start the crawl. "
            f"Last status response: {last_status!r}"
        )


class GosomJobTimeoutError(TimeoutError):
    """Raised when a gosom job does not reach a terminal state within max_wait.

    Preserves the gosom job ID for diagnostics.
    """

    def __init__(self, job_id: str, max_wait: float, last_state: str) -> None:
        self.job_id = job_id
        self.max_wait = max_wait
        self.last_state = last_state
        super().__init__(
            f"Gosom job {job_id} did not complete within {max_wait:.0f}s "
            f"(last state: {last_state!r}). "
            f"Check scraper logs: docker logs gmaps-scraper 2>&1 | grep {job_id}"
        )


class GosomJobFailedError(RuntimeError):
    """Raised when a gosom job reaches a terminal failure state."""

    def __init__(self, job_id: str, state: str, status_body: dict[str, Any]) -> None:
        self.job_id = job_id
        self.state = state
        self.status_body = status_body
        super().__init__(
            f"Gosom job {job_id} ended with status: {state!r}. "
            f"Full response: {status_body!r}"
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

# Column names returned by gosom's CSV download endpoint (reference only —
# used by parse_gmaps_csv via row.get() calls, not looked up from this dict).
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

# How long a job can sit in "pending" before we consider it stuck and attempt
# a resubmit.  Gosom processes jobs on-demand when the HTTP endpoint is hit,
# so jobs that haven't transitioned within 30s are likely stuck.
_STUCK_PENDING_THRESHOLD_SECONDS = 30.0

# Terminal states that mean the scraper will never produce results.
_TERMINAL_SUCCESS_STATES = frozenset({"completed", "ok", "done"})
_TERMINAL_FAILURE_STATES = frozenset({"failed", "cancelled", "error", "timeout"})


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
        self._timeout = httpx.Timeout(60.0, read=600.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit_scrape_job(
        self,
        query: str,
        job_name: str,
        depth: int = 5,
    ) -> str:
        """
        Submit a scrape job via POST /scrape (form endpoint).
        
        IMPORTANT: Must use /scrape, NOT /api/v1/jobs.
        The /api/v1/jobs endpoint creates a DB record but the scrapemate
        crawler worker is only triggered by the /scrape form endpoint.
        Jobs submitted via /api/v1/jobs stay 'pending' forever.
        """
        payload = {
            "name": job_name,
            "keywords": query,
            "lang": "en",
            "depth": str(depth),
            "maxtime": "10m",
            "zoom": "15",
        }
        logger.info(
            "[GMAPS] submit_scrape_job url=%s payload=%r",
            f"{self._base_url}/scrape",
            payload,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/scrape",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )
            response.raise_for_status()
            
            # /scrape returns an HTML row — extract the job ID from the response
            # or immediately query GET /api/v1/jobs to find the newest pending job
            return await self.get_latest_job_id(job_name)

    async def get_latest_job_id(self, job_name: str) -> str:
        """Poll GET /api/v1/jobs to find the job just submitted."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for _ in range(10):
                await asyncio.sleep(2)
                resp = await client.get(f"{self._base_url}/api/v1/jobs")
                jobs = resp.json()
                if jobs:
                    for job in jobs:
                        if job.get("Name") == job_name and job.get("Status") in ("pending", "working"):
                            return job["ID"]
        raise RuntimeError(f"Could not find submitted job '{job_name}' in Gosom queue")

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Return the raw job status dict from the gosom API."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/api/v1/jobs/{job_id}")
            resp.raise_for_status()
            return resp.json()

    async def download_results_csv(self, job_id: str) -> list["GmapsRawBusiness"]:
        """Download and parse the CSV results for a completed job."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/api/v1/jobs/{job_id}/download")
            logger.info(
                "[GMAPS] download job=%s http_status=%d content_length=%d first_200=%s",
                job_id,
                resp.status_code,
                len(resp.text),
                repr(resp.text[:200]),
            )
            resp.raise_for_status()

            # Check for local CSV fallback if the download endpoint returns
            # empty.  Gosom writes CSVs to /gmapsdata/{job_id}.csv; when the
            # API download returns nothing we try the file as a fallback.
            csv_text = resp.text
            if not csv_text or csv_text.strip() == "":
                logger.warning(
                    "[GMAPS] download endpoint returned empty body for job %s — "
                    "attempting local /gmapsdata fallback",
                    job_id,
                )
                csv_text = self._try_local_csv(job_id)

            if not csv_text or csv_text.strip() == "":
                logger.warning(
                    "[GMAPS] no CSV data available for job %s from API or local file",
                    job_id,
                )
                return []

            return parse_gmaps_csv(csv_text)

    async def wait_for_results(
        self,
        job_id: str,
        poll_interval: float = 3.0,
        max_wait: float = 60.0,
    ) -> list["GmapsRawBusiness"]:
        """
        Poll until the job is complete, then return parsed results.

        Raises ``GosomJobStuckPendingError`` if the job stays in ``pending``
        past ``_STUCK_PENDING_THRESHOLD_SECONDS`` (30s).  Callers that want
        automatic resubmit on stuck-pending should use
        :meth:`wait_for_results_with_retry` instead.

        The scrapemate container processes jobs on-demand and may exit after
        completing a batch — this is normal behaviour.  The short poll interval
        (3s default) and tight max_wait (60s default) ensure we fail fast and
        resubmit rather than burning the full worker timeout.

        :raises GosomJobTimeoutError: if the job does not complete within max_wait seconds.
        :raises GosomJobFailedError: if the job reaches a terminal failure state.
        :raises GosomJobStuckPendingError: if the job stays in pending past the threshold.
        """
        elapsed = 0.0
        last_state = ""
        stuck_pending_warned = False

        while elapsed < max_wait:
            try:
                status = await self.get_job_status(job_id)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                # Transient HTTP / network error — log and retry on next tick
                logger.warning(
                    "[GMAPS] transient error polling job %s (%.0fs elapsed): %s",
                    job_id, elapsed, exc,
                )
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                continue

            # Guard against non-dict / malformed responses
            if not isinstance(status, dict):
                logger.warning(
                    "[GMAPS] unexpected non-dict status for job %s: %r",
                    job_id, status,
                )
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                continue

            # Normalise: accept both "Status" and "status" keys; coerce to str
            raw_state = status.get("status") or status.get("Status") or ""
            state: str = str(raw_state).strip().lower()
            last_state = state

            logger.info(
                "[GMAPS] poll job=%s state=%r elapsed=%.0fs raw_response=%s",
                job_id, state, elapsed, status,
            )

            if state in _TERMINAL_SUCCESS_STATES:
                return await self.download_results_csv(job_id)

            if state in _TERMINAL_FAILURE_STATES:
                raise GosomJobFailedError(job_id, state, status)

            # Detect stuck-pending: warn once, then raise once past threshold.
            # Scrapemate processes jobs on-demand; if a job hasn't left
            # "pending" within 30s it's almost certainly stuck.
            if state == "pending" and elapsed > _STUCK_PENDING_THRESHOLD_SECONDS:
                if not stuck_pending_warned:
                    logger.warning(
                        "[GMAPS] job %s still 'pending' after %.0fs — scraper may "
                        "have silently dropped the job. Full status: %s",
                        job_id, elapsed, status,
                    )
                    stuck_pending_warned = True

                # Cancel and raise immediately so the retry loop can resubmit.
                if elapsed > _STUCK_PENDING_THRESHOLD_SECONDS:
                    raise GosomJobStuckPendingError(job_id, elapsed, status)

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise GosomJobTimeoutError(job_id, max_wait, last_state)

    async def wait_for_results_with_retry(
        self,
        query: str,
        niche: str,
        city: str,
        depth: int = 1,
        poll_interval: float = 3.0,
        max_wait: float = 120.0,
        max_attempts: int = 2,
    ) -> list["GmapsRawBusiness"]:
        """Submit, poll, and retry once if the first job gets stuck pending.

        This wraps :meth:`submit_job` + :meth:`wait_for_results` in a
        retry loop that catches ``GosomJobStuckPendingError`` and resubmits.
        Other errors (terminal failures, timeouts after running) propagate
        immediately because retrying won't help.

        The per-attempt ``max_wait`` is divided evenly across attempts so the
        total wall-clock time never exceeds the caller's budget.
        """
        per_attempt_wait = max_wait / max_attempts
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            job_name = f"scout_{niche}_{city}"
            job_id = await self.submit_scrape_job(query, job_name, depth=depth)
            logger.info(
                "[GMAPS] attempt %d/%d — submitted job %s for query %r",
                attempt, max_attempts, job_id, query,
            )
            try:
                return await self.wait_for_results(
                    job_id,
                    poll_interval=poll_interval,
                    max_wait=per_attempt_wait,
                )
            except GosomJobStuckPendingError as exc:
                logger.warning(
                    "[GMAPS] attempt %d/%d — job %s stuck pending, will %s. %s",
                    attempt,
                    max_attempts,
                    job_id,
                    "retry" if attempt < max_attempts else "give up",
                    exc,
                )
                last_exc = exc
                # Fall through to retry
            # GosomJobFailedError / GosomJobTimeoutError propagate immediately

        # All attempts exhausted
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _try_local_csv(job_id: str) -> str:
        """Best-effort read of the gosom CSV from the shared /gmapsdata volume.

        The gosom scraper writes output to ``/gmapsdata/{job_id}.csv``.
        When the API ``/download`` endpoint returns empty (a known gosom
        race condition), this fallback reads directly from the filesystem.

        NOTE: This only works if the ``gmaps_data`` Docker volume is
        mounted into the api/worker container.  The default
        docker-compose.yml does NOT mount it there (only the
        gmaps-scraper service has it).  If /gmapsdata is not present
        this method returns "" immediately.
        """
        gmapsdata_dir = "/gmapsdata"
        if not os.path.isdir(gmapsdata_dir):
            logger.debug(
                "[GMAPS] local CSV fallback skipped: %s not mounted in this container",
                gmapsdata_dir,
            )
            return ""

        for candidate in (
            f"{gmapsdata_dir}/{job_id}.csv",
            f"{gmapsdata_dir}/{job_id}",
        ):
            try:
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                    with open(candidate, encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    logger.info(
                        "[GMAPS] local CSV fallback success: path=%s size=%d",
                        candidate, len(content),
                    )
                    return content
            except OSError as exc:
                logger.warning(
                    "[GMAPS] local CSV fallback failed for %s: %s", candidate, exc,
                )
        return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_gmaps_csv(raw_csv: str) -> list[GmapsRawBusiness]:
    """Parse a gosom/google-maps-scraper CSV blob into raw business DTOs."""
    results: list[GmapsRawBusiness] = []

    if not raw_csv or not raw_csv.strip():
        logger.warning("[GMAPS] parse_gmaps_csv called with empty input")
        return results

    reader = csv.DictReader(io.StringIO(raw_csv))

    if not reader.fieldnames:
        logger.error(
            "[GMAPS] CSV has no header row. First 200 chars: %s",
            repr(raw_csv[:200]),
        )
        return results

    logger.info("[GMAPS] CSV headers: %s", list(reader.fieldnames))

    for row in reader:
        try:
            rating = _parse_optional_float(row.get("rating", ""))
            review_count = _parse_optional_int(row.get("reviews_count", ""))

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
            logger.warning(
                "[GMAPS] failed to parse CSV row %d: %s — row=%s",
                reader.line_num, exc, dict(row),
                exc_info=True,
            )

    logger.info("[GMAPS] parsed %d businesses from gosom CSV", len(results))
    return results


def _parse_optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None
    return float(cleaned)


def _parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^\d]", "", value)
    if not cleaned:
        return None
    return int(cleaned)


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
