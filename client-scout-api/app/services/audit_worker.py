"""
services/audit_worker.py — Worker orchestrator for website auditing.

Public API:
    run_audit_for_business(business_id, db)
        1. Fetches the Business row from the DB.
        2. Creates or resets an Audit row (status=running).
        3. Calls audit_website() to collect all signals.
        4. Saves the raw HTML snapshot (disk or S3).
        5. Persists the AuditSignals into the Audit row.
        6. Returns the completed Audit ORM object.

Concurrency:
    The module exposes a module-level _SEMAPHORE that gates parallel
    Playwright browser launches. Set AUDIT_CONCURRENCY in env (default: 3).
    This prevents OOM on the AWS t3.micro (1GB RAM).

Usage (from a background task or queue worker):
    from app.services.audit_worker import run_audit_for_business
    audit = await run_audit_for_business(business_id, db)
"""

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import Audit
from app.models.business import Business
from app.services.snapshot_store import save_snapshot

if TYPE_CHECKING:
    from app.services.auditor import AuditSignals

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Concurrency gate (module-level so it's shared across all background tasks)
# ---------------------------------------------------------------------------

def _get_semaphore() -> asyncio.Semaphore:
    """Lazily create the semaphore using the current event loop."""
    from app.config import get_settings
    concurrency = int(getattr(get_settings(), "AUDIT_CONCURRENCY", 3))
    return asyncio.Semaphore(concurrency)


# Created on first use (can't create at import time before event loop starts)
_semaphore: asyncio.Semaphore | None = None


def _semaphore_instance() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = _get_semaphore()
    return _semaphore


# ---------------------------------------------------------------------------
# Public worker function
# ---------------------------------------------------------------------------


async def run_audit_for_business(
    business_id: uuid.UUID | str,
    db: AsyncSession,
) -> Audit | None:
    """
    Run a full website audit for a given business.

    :param business_id: UUID of the Business to audit.
    :param db:          Async SQLAlchemy session.
    :returns:           The completed Audit ORM object, or None if no website.

    Steps:
      1. Look up Business, get website_url.
      2. Create/reset Audit row with status='running'.
      3. Acquire semaphore to limit concurrent Playwright browsers.
      4. Run audit_website() to collect all signals.
      5. Save HTML snapshot to disk/S3.
      6. Map AuditSignals → Audit ORM and persist.
    """
    if isinstance(business_id, str):
        business_id = uuid.UUID(business_id)

    # ── Step 1: Fetch business ────────────────────────────────────────────
    result = await db.execute(
        select(Business).where(Business.id == business_id)
    )
    business: Business | None = result.scalar_one_or_none()

    if business is None:
        logger.error("[AUDIT] Business %s not found — skipping audit", business_id)
        return None

    if not business.website_url:
        logger.info(
            "[AUDIT] Business %s (%s) has no website_url — marking as skipped",
            business_id, business.name,
        )
        return await _create_skipped_audit(business, db)

    url = _ensure_scheme(business.website_url)
    logger.info("[AUDIT] starting for business=%s url=%r", business_id, url)

    # ── Step 2: Create or reset Audit row ─────────────────────────────────
    audit = await _get_or_create_audit(business_id=business_id, db=db)
    audit.status = "running"
    audit.url_checked = url
    audit.error_message = None
    await db.flush()

    # ── Step 3 & 4: Semaphore-gated Playwright audit ───────────────────────
    from app.services.auditor import audit_website

    async with _semaphore_instance():
        signals: AuditSignals = await audit_website(url)

    # ── Step 5: Save snapshot ─────────────────────────────────────────────
    snapshot_path: str | None = None
    if signals.raw_html and signals.raw_html_hash:
        snapshot_path = await save_snapshot(
            business_id=str(business_id),
            url=url,
            html=signals.raw_html,
            html_hash=signals.raw_html_hash,
        )

    # ── Step 6: Persist signals ───────────────────────────────────────────
    _apply_signals_to_audit(audit, signals, snapshot_path)
    await db.commit()
    await db.refresh(audit)

    logger.info(
        "[AUDIT] complete: business=%s status=%s mobile=%s forms=%s wa=%s booking=%s load=%dms",
        business_id, audit.status, audit.mobile_friendly,
        audit.has_forms, audit.has_whatsapp, audit.has_booking, audit.load_time_ms or 0,
    )
    return audit


# ---------------------------------------------------------------------------
# Batch worker
# ---------------------------------------------------------------------------


async def run_audits_for_job(
    job_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, int]:
    """
    Audit all businesses linked to a discovery job that haven't been audited yet.
    Returns a summary dict: {total, completed, failed, skipped}.
    """
    from app.models.audit import Audit as AuditModel

    result = await db.execute(
        select(Business.id)
        .outerjoin(AuditModel, AuditModel.business_id == Business.id)
        .where(
            Business.discovery_job_id == job_id,
            # Only businesses with no audit or failed/pending audit
            (AuditModel.id.is_(None)) | (AuditModel.status.in_(["pending", "failed"])),
        )
    )
    business_ids: list[uuid.UUID] = [row[0] for row in result.all()]
    logger.info("[AUDIT] found %d businesses to audit for job %s", len(business_ids), job_id)

    stats = {"total": len(business_ids), "completed": 0, "failed": 0, "skipped": 0}

    for bid in business_ids:
        try:
            audit = await run_audit_for_business(bid, db)
            if audit is None:
                stats["skipped"] += 1
            elif audit.status == "completed":
                stats["completed"] += 1
            else:
                stats["failed"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("[AUDIT] uncaught error auditing %s: %s", bid, exc)
            stats["failed"] += 1

    logger.info("[AUDIT] batch audit done for job %s: %s", job_id, stats)
    return stats


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_or_create_audit(
    business_id: uuid.UUID,
    db: AsyncSession,
) -> Audit:
    """Return existing Audit row or create a fresh one."""
    result = await db.execute(
        select(Audit).where(Audit.business_id == business_id)
    )
    audit = result.scalar_one_or_none()
    if audit is None:
        audit = Audit(id=uuid.uuid4(), business_id=business_id, status="pending")
        db.add(audit)
        await db.flush()
    return audit


async def _create_skipped_audit(business: Business, db: AsyncSession) -> Audit:
    """Create an audit row with status=skipped for businesses without a website."""
    audit = await _get_or_create_audit(business.id, db)
    audit.status = "skipped"
    audit.has_website = False
    audit.error_message = "No website_url available for this business."
    await db.commit()
    return audit


def _apply_signals_to_audit(
    audit: Audit,
    signals: "AuditSignals",
    snapshot_path: str | None,
) -> None:
    """Map AuditSignals dataclass → Audit ORM fields."""
    audit.url_checked = signals.url_checked
    audit.has_website = signals.has_website
    audit.ssl_valid = signals.ssl_valid
    audit.mobile_friendly = signals.mobile_friendly
    audit.has_forms = signals.has_forms
    audit.has_cta = signals.has_cta
    audit.has_whatsapp = signals.has_whatsapp
    audit.has_booking = signals.has_booking
    audit.has_chatbot = signals.has_chatbot
    audit.load_time_ms = signals.load_time_ms
    audit.page_speed_score = signals.page_speed_score
    audit.has_title = signals.has_title
    audit.has_meta_desc = signals.has_meta_desc
    audit.has_h1 = signals.has_h1
    audit.has_og_tags = signals.has_og_tags
    audit.has_facebook = signals.has_facebook
    audit.has_instagram = signals.has_instagram
    audit.has_linkedin = signals.has_linkedin
    audit.has_twitter = signals.has_twitter
    audit.tech_stack = signals.tech_stack or []
    audit.raw_html_hash = signals.raw_html_hash or None
    audit.screenshot_url = snapshot_path
    audit.status = signals.status
    audit.error_message = signals.error_message


def _ensure_scheme(url: str) -> str:
    """Ensure the URL has a scheme. Defaults to https://."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url
