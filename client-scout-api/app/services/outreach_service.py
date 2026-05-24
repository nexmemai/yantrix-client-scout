"""
services/outreach_service.py - Orchestrate one outreach send for one lead.

This is the "do the thing" layer. It is driver-agnostic: it asks the
sender factories for whatever is configured (real SMTP / real WhatsApp /
dry-run) and writes the resulting metadata into outreach_attempts plus
the denormalised columns on `businesses`.

Boundaries:
  * INPUT  : a Business id and an optional Pitch id. Resolves both rows
             internally using the supplied AsyncSession.
  * OUTPUT : a structured ``OutreachOutcome`` summary (used by the ARQ
             task to publish a per-lead progress event).

Idempotency:
  * Every call appends new rows to outreach_attempts; the worker is
    expected to enqueue this once per lead per run. ARQ's _job_id key
    deduplicates retries at the queue level (see run_send_outreach_task).
  * Lead summary fields are recomputed each call from the row's known
    state and the outcome of the current attempt - no stale aggregates.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.business import Business
from app.models.outreach import OutreachAttempt
from app.models.pitch import Pitch
from app.services.outreach_helpers import build_outreach_payload
from app.services.outreach_sender import (
    AttemptStatus,
    EmailSender,
    OutreachSendResult,
    OutreachStatus,
    WhatsAppSender,
    build_email_sender,
    build_whatsapp_sender,
    is_email,
    normalise_phone,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutreachOutcome:
    """Aggregated result of one ``send_outreach_for_lead`` call.

    The ARQ task hands this structure to publish_job_event so the dashboard
    can show "3 of 12 leads emailed; 1 failed (no email)" without rereading
    the timeline table per lead.
    """

    business_id: uuid.UUID
    lead_status: OutreachStatus
    email: AttemptStatus | None
    whatsapp: AttemptStatus | None
    error_message: str | None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def send_outreach_for_lead(
    *,
    business_id: uuid.UUID,
    db: AsyncSession,
    job_id: uuid.UUID | None = None,
    email_sender: EmailSender | None = None,
    whatsapp_sender: WhatsAppSender | None = None,
) -> OutreachOutcome:
    """Send pending outreach for one lead and return a structured outcome.

    Behavioural contract:

    1. Loads the business + its newest pitch in one round-trip.
    2. Builds the same OutreachPayload the dashboard's "Copy email" button
       uses, so the autonomous and manual surfaces send the *same* copy.
       This keeps the LLM-generated subject/body as the single source of
       truth for what the lead receives.
    3. Picks recipients:
         - email   -> business.contact_email or business.email
         - whatsapp-> business.contact_phone or business.phone (digits only)
       A channel without a recipient is recorded as a 'skipped' attempt.
    4. Calls the configured sender for each channel - both errors are
       captured per-row, neither blocks the other.
    5. Persists attempts and updates the lead's denormalised summary.
    """
    business = await _load_business_with_pitches(business_id, db)
    if business is None:
        logger.warning("[OUTREACH] lead %s missing - skipping", business_id)
        return OutreachOutcome(
            business_id=business_id,
            lead_status="skipped",
            email=None,
            whatsapp=None,
            error_message="lead_not_found",
        )

    pitch: Pitch | None = business.pitches[0] if business.pitches else None
    payload = build_outreach_payload(business, pitch)

    email_to = business.contact_email or business.email or ""
    phone_to = normalise_phone(business.contact_phone or business.phone)

    sender_email = email_sender or build_email_sender()
    sender_whatsapp = whatsapp_sender or build_whatsapp_sender()

    attempts: list[OutreachAttempt] = []
    now = datetime.now(tz=timezone.utc)

    # ── Email channel ────────────────────────────────────────────────
    if not is_email(email_to):
        # Recording the skip lets the timeline render "no email on file"
        # instead of silently doing nothing - which would make autosend
        # debugging painful when leads are missing data.
        email_attempt = _build_attempt(
            business_id=business.id,
            pitch_id=pitch.id if pitch else None,
            job_id=job_id,
            channel="email",
            status="skipped",
            provider=None,
            recipient=email_to or None,
            payload_subject=payload.email_subject,
            payload_body=payload.email_body,
            error_message="no_email_on_file" if not email_to else "invalid_email_format",
            is_dry_run=False,
            attempted_at=now,
            completed_at=now,
        )
        email_status: AttemptStatus = "skipped"
        email_error = email_attempt.error_message
    else:
        result = await sender_email.send(
            to=email_to,
            subject=payload.email_subject,
            body=payload.email_body,
        )
        email_attempt = _attempt_from_result(
            business=business,
            pitch=pitch,
            job_id=job_id,
            channel="email",
            recipient=email_to,
            subject=payload.email_subject,
            body=payload.email_body,
            result=result,
            attempted_at=now,
        )
        email_status = result.status
        email_error = result.error_message
    attempts.append(email_attempt)

    # ── WhatsApp channel ─────────────────────────────────────────────
    if phone_to is None:
        whatsapp_attempt = _build_attempt(
            business_id=business.id,
            pitch_id=pitch.id if pitch else None,
            job_id=job_id,
            channel="whatsapp",
            status="skipped",
            provider=None,
            recipient=None,
            payload_subject=None,
            payload_body=payload.whatsapp_message,
            error_message="no_phone_on_file",
            is_dry_run=False,
            attempted_at=now,
            completed_at=now,
        )
        whatsapp_status: AttemptStatus = "skipped"
        whatsapp_error = whatsapp_attempt.error_message
    else:
        result = await sender_whatsapp.send(
            to_phone=phone_to,
            body=payload.whatsapp_message,
        )
        whatsapp_attempt = _attempt_from_result(
            business=business,
            pitch=pitch,
            job_id=job_id,
            channel="whatsapp",
            recipient=phone_to,
            subject=None,
            body=payload.whatsapp_message,
            result=result,
            attempted_at=now,
        )
        whatsapp_status = result.status
        whatsapp_error = result.error_message
    attempts.append(whatsapp_attempt)

    db.add_all(attempts)

    # ── Update denormalised summary on the business row ──────────────
    lead_status = _aggregate_lead_status(email_status, whatsapp_status)
    if email_status == "sent":
        business.email_sent_at = now
    if whatsapp_status == "sent":
        business.whatsapp_sent_at = now
    business.outreach_status = lead_status
    business.last_outreach_at = now
    business.last_outreach_error = _pick_error(email_status, email_error, whatsapp_status, whatsapp_error)
    # Bump the existing CRM counter so the manual "Attempts" pill on the
    # Lead Detail page reflects autosent attempts too.
    business.contact_attempts = (business.contact_attempts or 0) + sum(
        1 for s in (email_status, whatsapp_status) if s == "sent"
    )
    if business.contact_attempts and business.lead_status == "new":
        business.lead_status = "contacted"
    if any(s == "sent" for s in (email_status, whatsapp_status)):
        business.last_contacted_at = now

    await db.commit()

    logger.info(
        "[OUTREACH] lead=%s status=%s email=%s whatsapp=%s",
        business.id,
        lead_status,
        email_status,
        whatsapp_status,
    )
    return OutreachOutcome(
        business_id=business.id,
        lead_status=lead_status,
        email=email_status,
        whatsapp=whatsapp_status,
        error_message=business.last_outreach_error,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_business_with_pitches(
    business_id: uuid.UUID,
    db: AsyncSession,
) -> Business | None:
    """Fetch the business with its pitches preloaded (newest first)."""
    result = await db.execute(
        select(Business)
        .options(selectinload(Business.pitches))
        .where(Business.id == business_id)
    )
    return result.scalar_one_or_none()


def _attempt_from_result(
    *,
    business: Business,
    pitch: Pitch | None,
    job_id: uuid.UUID | None,
    channel: str,
    recipient: str,
    subject: str | None,
    body: str,
    result: OutreachSendResult,
    attempted_at: datetime,
) -> OutreachAttempt:
    return _build_attempt(
        business_id=business.id,
        pitch_id=pitch.id if pitch else None,
        job_id=job_id,
        channel=channel,
        status=result.status,
        provider=result.provider,
        provider_message_id=result.provider_message_id,
        recipient=recipient,
        payload_subject=subject,
        payload_body=body,
        error_message=result.error_message,
        is_dry_run=result.is_dry_run,
        attempted_at=attempted_at,
        completed_at=attempted_at,
    )


def _build_attempt(
    *,
    business_id: uuid.UUID,
    pitch_id: uuid.UUID | None,
    job_id: uuid.UUID | None,
    channel: str,
    status: AttemptStatus,
    provider: str | None,
    provider_message_id: str | None = None,
    recipient: str | None,
    payload_subject: str | None,
    payload_body: str | None,
    error_message: str | None,
    is_dry_run: bool,
    attempted_at: datetime,
    completed_at: datetime | None,
) -> OutreachAttempt:
    return OutreachAttempt(
        business_id=business_id,
        pitch_id=pitch_id,
        job_id=job_id,
        channel=channel,
        status=status,
        provider=provider,
        provider_message_id=provider_message_id,
        recipient=recipient,
        payload_subject=payload_subject,
        payload_body=payload_body,
        error_message=error_message,
        is_dry_run=is_dry_run,
        attempted_at=attempted_at,
        completed_at=completed_at,
    )


def _aggregate_lead_status(
    email_status: AttemptStatus,
    whatsapp_status: AttemptStatus,
) -> OutreachStatus:
    """Roll up two channel statuses into the lead-level status string.

    The mapping is intentionally explicit so the Communication Log header
    matches what the operator expects:

        sent + sent       -> 'sent'
        sent + failed     -> 'partial'
        sent + skipped    -> 'sent'   (a skipped channel doesn't count as a failure)
        failed + failed   -> 'failed'
        failed + skipped  -> 'failed'
        skipped + skipped -> 'skipped' (no contact channel at all)
    """
    statuses: tuple[AttemptStatus, AttemptStatus] = (email_status, whatsapp_status)
    if any(s == "sent" for s in statuses) and any(s == "failed" for s in statuses):
        return "partial"
    if any(s == "sent" for s in statuses):
        return "sent"
    if all(s == "skipped" for s in statuses):
        return "skipped"
    if any(s == "failed" for s in statuses):
        return "failed"
    return "pending"


def _pick_error(
    email_status: AttemptStatus,
    email_error: str | None,
    whatsapp_status: AttemptStatus,
    whatsapp_error: str | None,
) -> str | None:
    """Surface the most actionable error on the lead summary.

    A 'failed' status beats a 'skipped' status (skipped means "we never
    tried", failed means "the provider rejected us"). The frontend shows
    this string verbatim under the lead's outreach badge.
    """
    if email_status == "failed" and email_error:
        return email_error
    if whatsapp_status == "failed" and whatsapp_error:
        return whatsapp_error
    if email_status == "skipped" and email_error:
        return email_error
    if whatsapp_status == "skipped" and whatsapp_error:
        return whatsapp_error
    return None


# Quiet pyflakes for the unused Iterable import - exported for future
# bulk send helpers.
_ = Iterable
