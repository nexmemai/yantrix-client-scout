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
from typing import Any

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business import Business
from app.models.job import DiscoveryJob
from app.services.gmaps_client import GmapsRawBusiness, GmapsScraperClient

logger = logging.getLogger(__name__)


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
) -> list[uuid.UUID]:
    """
    Run the Google Maps discovery pipeline for `niche` in `city`.

    Steps:
      1. Build a natural-language query and submit to gosom sidecar.
      2. Poll until the job completes (max 10 minutes).
      3. Normalise each result row → Business ORM object.
      4. Skip duplicates (by website_url OR phone).
      5. Bulk-insert new businesses.

    :param niche:       Niche label, e.g. "dental", "salon", "real_estate".
    :param city:        City name, e.g. "Pune", "Mumbai".
    :param db:          Async SQLAlchemy session (injected by caller).
    :param job:         Optional DiscoveryJob ORM row to update progress.
    :param depth:       gosom depth (1 page ≈ 20 results; depth 5 ≈ 100).
    :param max_results: Cap total results to protect RAM on AWS t3.micro (1GB).

    :returns: List of newly inserted business UUIDs (duplicates excluded).
    """
    query = _build_query(niche, city)
    logger.info("[DISCOVERY] starting: query=%r niche=%r city=%r", query, niche, city)

    client = GmapsScraperClient()

    # --- Step 1 & 2: Submit and wait ---
    job_id = await client.submit_job(query, depth=depth)
    raw_businesses = await client.wait_for_results(job_id)

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
    new_business_ids = await _upsert_businesses(
        raw_businesses=raw_businesses,
        niche=niche,
        db=db,
        discovery_job_id=job.id if job else None,
    )

    if job:
        job.total_discovered = len(raw_businesses)
        await db.flush()

    logger.info(
        "[DISCOVERY] complete: %d raw → %d new businesses for %r in %r",
        len(raw_businesses), len(new_business_ids), niche, city,
    )
    if not new_business_ids:
        logger.info(
            "[DISCOVERY] zero new businesses — all %d results were duplicates or the scraper returned nothing",
            len(raw_businesses),
        )
    return new_business_ids


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_query(niche: str, city: str) -> str:
    """
    Build a natural-language search query for gosom.

    Examples:
      ("dental", "Pune")  →  "dental clinics in Pune"
      ("salon", "Mumbai") →  "salons in Mumbai"
    """
    niche_phrases: dict[str, str] = {
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
    phrase = niche_phrases.get(niche.lower(), f"{niche.replace('_', ' ')}s")
    return f"{phrase} in {city}"


async def _upsert_businesses(
    raw_businesses: list[GmapsRawBusiness],
    niche: str,
    db: AsyncSession,
    discovery_job_id: uuid.UUID | None,
) -> list[uuid.UUID]:
    """
    Normalise, deduplicate, and insert businesses.

    Duplicate detection strategy (OR logic):
      - website_url matches an existing business's website_url, OR
      - phone matches an existing business's phone.

    This is intentionally lenient to avoid missing real-world duplicates
    where one scrape returns a local number and another returns a mobile.
    """
    if not raw_businesses:
        return []

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

    for raw in raw_businesses:
        norm_url = _normalise_url(raw.website)
        norm_phone = raw.phone

        # Skip if duplicate on website OR phone
        if norm_url and norm_url in existing_urls:
            logger.debug("[DISCOVERY] skipped duplicate reason=url title=%r", raw.title)
            continue
        if norm_phone and norm_phone in existing_phones:
            logger.debug("[DISCOVERY] skipped duplicate reason=phone title=%r", raw.title)
            continue

        business = _normalise_to_orm(
            raw=raw,
            niche=niche,
            discovery_job_id=discovery_job_id,
        )

        try:
            db.add(business)
            await db.flush()  # get the PK without committing
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

        except IntegrityError:
            # Race condition: another worker inserted between our check and flush
            await db.rollback()
            logger.warning("[DISCOVERY] IntegrityError on insert for %r — skipping", raw.title)

    await db.commit()
    return inserted_ids


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
