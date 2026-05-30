"""
services/discovery.py — Discovery orchestrator.

This is the single entry-point for Phase 2 (Discovery) of the pipeline:

    discover_businesses(niche, city, db)
        1. Submit a query to the gosom sidecar
        2. Poll until results are ready
        3. Normalise each row into our `businesses` schema
        4. Upsert into Postgres, skipping duplicates on website_url or phone
        5. Return the list of newly inserted business UUIDs

The function is called by the /run-scout endpoint (api/run_scout.py)
and runs as a FastAPI background task to avoid blocking the HTTP response.
"""

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business import Business
from app.models.job import DiscoveryJob
from app.services.gmaps_client import (
    GmapsRawBusiness,
    GmapsScraperClient,
    GosomJobFailedError,
    GosomJobStuckPendingError,
    GosomJobTimeoutError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawBusinessIngestResult:
    """Summary returned when raw scraper rows are normalised into businesses."""

    raw_count: int
    inserted_ids: list[uuid.UUID]
    duplicates_skipped: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def discover_businesses(
    niche: str,
    city: str,
    db: AsyncSession,
    job: DiscoveryJob | None = None,
    depth: int = 1,
    max_results: int = 200,
    search_phrase: str | None = None,
) -> list[uuid.UUID]:
    """
    Run the Google Maps discovery pipeline for `niche` in `city`.

    Steps:
      1. Build a natural-language query and submit to gosom sidecar.
      2. Poll until the job completes (max 10 minutes).
      3. Normalise each result row → Business ORM object.
      4. Skip duplicates (by website_url OR phone).
      5. Bulk-insert new businesses.

    :param niche:        Canonical niche key, e.g. "dental", "ev_charging".
                         Stored on each Business row for analytics/scoring.
    :param city:         City name, e.g. "Pune", "Mumbai".
    :param db:           Async SQLAlchemy session (injected by caller).
    :param job:          Optional DiscoveryJob ORM row to update progress.
    :param depth:        gosom depth (1 page ≈ 20 results; depth 5 ≈ 100).
    :param max_results:  Cap total results to protect RAM on Oracle A1.
    :param search_phrase: Resolved natural-language phrase ready for gosom,
                         e.g. "EV charging stations". When None we fall back
                         to the legacy built-in mapping for the 15 catalog
                         niches so older callers keep working unchanged.

    :returns: List of newly inserted business UUIDs (duplicates excluded).
    """
    query = _build_query(search_phrase, niche, city)
    logger.info("[DISCOVERY] starting: query=%r niche=%r city=%r depth=%d", query, niche, city, depth)

    client = GmapsScraperClient()

    # --- Step 1 & 2: Submit and wait (with automatic retry on stuck-pending) ---
    try:
        raw_businesses = await client.wait_for_results_with_retry(
            query=query,
            depth=depth,
            max_wait=900.0,
            max_attempts=2,
        )
    except GosomJobStuckPendingError as exc:
        logger.error(
            "[DISCOVERY] gosom job %s stuck pending after retry: niche=%r city=%r query=%r",
            exc.job_id, niche, city, query,
        )
        if job:
            job.error_message = str(exc)[:2000]
        raise
    except GosomJobTimeoutError as exc:
        logger.error(
            "[DISCOVERY] gosom job %s timed out: niche=%r city=%r query=%r last_state=%r",
            exc.job_id, niche, city, query, exc.last_state,
        )
        if job:
            job.error_message = str(exc)[:2000]
        raise
    except GosomJobFailedError as exc:
        logger.error(
            "[DISCOVERY] gosom job %s failed with state=%r: niche=%r city=%r",
            exc.job_id, exc.state, niche, city,
        )
        if job:
            job.error_message = str(exc)[:2000]
        raise
    except Exception as exc:
        logger.error(
            "[DISCOVERY] unexpected error during scraper interaction: niche=%r city=%r query=%r error=%s",
            niche, city, query, exc,
            exc_info=True,
        )
        raise

    logger.info(
        "[DISCOVERY] scraper returned %d raw results for niche=%r city=%r",
        len(raw_businesses), niche, city,
    )

    # Cap results
    if len(raw_businesses) > max_results:
        logger.warning(
            "[DISCOVERY] capping %d results to %d for niche=%r city=%r",
            len(raw_businesses), max_results, niche, city,
        )
        raw_businesses = raw_businesses[:max_results]

    if job:
        job.total_discovered = len(raw_businesses)
        await db.flush()

    # --- Step 3 & 4: Normalise + deduplicate ---
    ingest_result = await ingest_raw_businesses(
        raw_businesses=raw_businesses,
        niche=niche,
        db=db,
        discovery_job_id=job.id if job else None,
    )

    logger.info(
        "[DISCOVERY] complete: %d raw → %d new businesses for %r in %r",
        len(raw_businesses), len(ingest_result.inserted_ids), niche, city,
    )
    if not ingest_result.inserted_ids:
        logger.info(
            "[DISCOVERY] zero new businesses — all %d results were duplicates or the scraper returned nothing",
            len(raw_businesses),
        )
    return ingest_result.inserted_ids


async def ingest_raw_businesses(
    raw_businesses: list[GmapsRawBusiness],
    niche: str,
    db: AsyncSession,
    discovery_job_id: uuid.UUID | None,
) -> RawBusinessIngestResult:
    """Normalise, deduplicate, and insert raw scraper rows for any source."""
    return await _upsert_businesses(
        raw_businesses=raw_businesses,
        niche=niche,
        db=db,
        discovery_job_id=discovery_job_id,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_query(search_phrase: str | None, niche: str, city: str) -> str:
    """
    Compose the Google Maps search string from a resolved phrase.

    The full free-text resolution lives in app/services/niche_resolver.py;
    this builder only handles the trailing " in <city>" composition so it
    stays cheap and unit-testable.

    Backwards compatibility: if the caller did not pass a `search_phrase`
    (older internal callers, CSV ingestion, future tooling), we keep the
    original built-in catalog so the legacy 15 niches keep producing the
    exact same query strings they always did.
    """
    if search_phrase:
        phrase = search_phrase.strip()
    else:
        legacy: dict[str, str] = {
            "dental": "dental clinics",
            "salon": "beauty salons",
            "real_estate": "real estate agents",
            "clinic": "medical clinics",
            "gym": "gyms and fitness centres",
            "restaurant": "restaurants",
            "hotel": "hotels",
            "ca": "chartered accountants",
            "lawyer": "law firms",
            "physiotherapy": "physiotherapy clinics",
        }
        phrase = legacy.get(niche.lower(), f"{niche.replace('_', ' ')}s")
    return f"{phrase} in {city.strip()}"


async def _upsert_businesses(
    raw_businesses: list[GmapsRawBusiness],
    niche: str,
    db: AsyncSession,
    discovery_job_id: uuid.UUID | None,
) -> RawBusinessIngestResult:
    """
    Normalise, deduplicate, and insert businesses.

    Duplicate detection strategy (OR logic):
      - website_url matches an existing business's website_url, OR
      - phone matches an existing business's phone.

    This is intentionally lenient to avoid missing real-world duplicates
    where one scrape returns a local number and another returns a mobile.
    """
    if not raw_businesses:
        return RawBusinessIngestResult(raw_count=0, inserted_ids=[], duplicates_skipped=0)

    # Collect candidate fingerprints for batch dedup check
    candidate_phones = {r.phone for r in raw_businesses if r.phone}
    candidate_urls = {_normalise_url(r.website) for r in raw_businesses if r.website}

    # Single batch query to find existing rows matching any phone or URL
    existing_stmt = select(Business.website_url, Business.phone).where(
        or_(
            Business.phone.in_(candidate_phones) if candidate_phones else False,
            Business.website_url.in_(candidate_urls) if candidate_urls else False,
        )
    )
    result = await db.execute(existing_stmt)
    existing_rows = result.all()

    existing_phones: set[str] = {row.phone for row in existing_rows if row.phone}
    existing_urls: set[str] = {row.website_url for row in existing_rows if row.website_url}

    inserted_ids: list[uuid.UUID] = []
    duplicates_skipped = 0

    for raw in raw_businesses:
        norm_url = _normalise_url(raw.website)
        norm_phone = raw.phone

        # Skip if duplicate on website OR phone
        if norm_url and norm_url in existing_urls:
            duplicates_skipped += 1
            logger.debug("[DISCOVERY] skipped duplicate reason=url title=%r", raw.title)
            continue
        if norm_phone and norm_phone in existing_phones:
            duplicates_skipped += 1
            logger.debug("[DISCOVERY] skipped duplicate reason=phone title=%r", raw.title)
            continue

        business = _normalise_to_orm(
            raw=raw,
            niche=niche,
            discovery_job_id=discovery_job_id,
        )

        try:
            async with db.begin_nested():
                db.add(business)
                await db.flush()  # get the PK without committing

        except IntegrityError:
            # Race condition: another worker inserted between our check and flush
            duplicates_skipped += 1
            logger.warning("[DISCOVERY] IntegrityError on insert for %r — skipping", raw.title)
            continue

        inserted_ids.append(business.id)
        logger.info(
            "[%s] [DISCOVERY] inserted title=%r website=%r phone=%r",
            business.id,
            business.name,
            business.website_url,
            business.phone,
        )

        # Track in our in-memory sets to catch same-batch duplicates
        if norm_url:
            existing_urls.add(norm_url)
        if norm_phone:
            existing_phones.add(norm_phone)

    await db.commit()
    return RawBusinessIngestResult(
        raw_count=len(raw_businesses),
        inserted_ids=inserted_ids,
        duplicates_skipped=duplicates_skipped,
    )


def _normalise_to_orm(
    raw: GmapsRawBusiness,
    niche: str,
    discovery_job_id: uuid.UUID | None,
) -> Business:
    """Map a GmapsRawBusiness DTO to a Business ORM instance."""
    return Business(
        id=uuid.uuid4(),
        name=raw.title[:255],
        category=raw.category[:100] if raw.category else None,
        niche=niche,
        address=raw.address,
        city=raw.city,
        country="India",
        phone=raw.phone,
        website_url=_normalise_url(raw.website),
        google_maps_url=raw.google_maps_url,
        rating=raw.rating,
        review_count=raw.review_count,
        source="google_maps",
        stage="new",
        discovery_job_id=discovery_job_id,
        raw_data=raw.raw,
    )


def _normalise_url(url: str | None) -> str | None:
    """
    Normalise a URL for deduplication:
      - Lowercase
      - Strip trailing slash
      - Strip 'www.' prefix
      - Strip query strings and fragments

    "https://www.Clinic.com/about?ref=maps" → "clinic.com/about"
    """
    if not url:
        return None
    url = url.lower().strip().rstrip("/")
    # Strip protocol
    url = re.sub(r"^https?://", "", url)
    # Strip www.
    url = re.sub(r"^www\.", "", url)
    # Strip query string and fragment
    url = re.split(r"[?#]", url)[0]
    return url or None
