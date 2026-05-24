"""
services/outreach_sender.py - Pluggable senders for autonomous outreach.

Two channels, two drivers each:

* Email
    - SmtpEmailSender:    standard SMTP+STARTTLS via aiosmtplib. Used in
                          production when SMTP_HOST is set.
    - DryRunEmailSender:  no-op that logs the payload and returns 'dry_run'.
                          Used in dev / when creds are missing so demos and
                          tests still exercise the full pipeline.

* WhatsApp
    - WhatsAppCloudSender: Meta WhatsApp Business Cloud API
                           (graph.facebook.com/v20.0/{phone_id}/messages).
                           Selected when WHATSAPP_PROVIDER='meta_cloud' and
                           WHATSAPP_PHONE_NUMBER_ID + WHATSAPP_ACCESS_TOKEN
                           are both set.
    - DryRunWhatsAppSender: same shape, returns 'dry_run'. Default fallback.

Both interfaces return an ``OutreachSendResult`` so the calling service
records identical metadata (provider, provider_message_id, status, error)
into outreach_attempts regardless of which driver ran.

Why a small custom interface instead of pulling Celery/Resend SDKs:

* The hot path needs only "send one short message, get a result" - heavy
  abstractions add startup time on every ARQ worker boot.
* Both drivers must be safely no-op'd in dev: returning a structured
  dry-run result keeps the calling service trivially testable.
* Keeping the dependencies loose (aiosmtplib, httpx) means a future swap
  to SES / SendGrid is one new class, not a refactor.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Literal, Protocol

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

OutreachChannel = Literal["email", "whatsapp", "sms"]
AttemptStatus = Literal["pending", "sent", "failed", "skipped"]
OutreachStatus = Literal[
    "idle", "pending", "sent", "partial", "failed", "skipped"
]


@dataclass(frozen=True)
class OutreachSendResult:
    """Structured outcome of one send attempt.

    Mirrors the columns the calling service writes into outreach_attempts so
    the persistence layer is a 1:1 copy from this struct - no per-driver
    branching downstream.
    """

    status: AttemptStatus
    provider: str
    provider_message_id: str | None = None
    error_message: str | None = None
    is_dry_run: bool = False


# ---------------------------------------------------------------------------
# Email senders
# ---------------------------------------------------------------------------


class EmailSender(Protocol):
    """Send one email and report what happened."""

    name: str

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
    ) -> OutreachSendResult:  # pragma: no cover - Protocol contract
        ...


@dataclass(frozen=True)
class SmtpEmailSender:
    """Production email path. Uses aiosmtplib for non-blocking SMTP+STARTTLS."""

    host: str
    port: int
    username: str | None
    password: str | None
    use_tls: bool
    from_address: str
    timeout_seconds: float
    name: str = "smtp"

    async def send(self, *, to: str, subject: str, body: str) -> OutreachSendResult:
        # aiosmtplib is imported lazily so the API container does not pay
        # the import cost at boot - only the worker process actually sends.
        try:
            import aiosmtplib  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            return OutreachSendResult(
                status="failed",
                provider=self.name,
                error_message=(
                    "aiosmtplib is not installed. Add `aiosmtplib` to "
                    "client-scout-api/requirements.txt to enable real SMTP."
                ),
            )

        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = to
        message["Subject"] = subject
        # Stable Message-Id helps the receiving MTA dedupe and lets the
        # calling service record provider_message_id even when the SMTP
        # server doesn't echo one back.
        message_id = f"<{uuid.uuid4()}@yantrix-client-scout>"
        message["Message-Id"] = message_id
        message.set_content(body)

        try:
            response = await aiosmtplib.send(
                message,
                hostname=self.host,
                port=self.port,
                username=self.username or None,
                password=self.password or None,
                start_tls=self.use_tls,
                timeout=self.timeout_seconds,
            )
            logger.info(
                "[OUTREACH][EMAIL] sent to=%s subject=%r smtp_response=%r",
                to,
                subject,
                response,
            )
            return OutreachSendResult(
                status="sent",
                provider=self.name,
                provider_message_id=message_id,
            )
        except Exception as exc:  # noqa: BLE001 - any SMTP error must surface
            logger.warning("[OUTREACH][EMAIL] send failed to=%s: %s", to, exc)
            return OutreachSendResult(
                status="failed",
                provider=self.name,
                provider_message_id=message_id,
                error_message=_truncate(str(exc), 500),
            )


@dataclass(frozen=True)
class DryRunEmailSender:
    """Logs the payload and pretends to succeed.

    Why we still mark status='sent' (not 'skipped') in dry-run: the worker
    pipeline should treat the autosend stage as having completed so the
    UI can render "Sent (dry run)" instead of "Skipped". The is_dry_run
    flag on the row preserves the truth for ops dashboards.
    """

    from_address: str
    name: str = "dry_run"

    async def send(self, *, to: str, subject: str, body: str) -> OutreachSendResult:
        logger.info(
            "[OUTREACH][EMAIL][DRYRUN] from=%s to=%s subject=%r body_chars=%d",
            self.from_address,
            to,
            subject,
            len(body or ""),
        )
        return OutreachSendResult(
            status="sent",
            provider=self.name,
            provider_message_id=f"dryrun-{uuid.uuid4()}",
            is_dry_run=True,
        )


# ---------------------------------------------------------------------------
# WhatsApp senders
# ---------------------------------------------------------------------------


class WhatsAppSender(Protocol):
    name: str

    async def send(
        self,
        *,
        to_phone: str,
        body: str,
    ) -> OutreachSendResult:  # pragma: no cover - Protocol contract
        ...


@dataclass(frozen=True)
class WhatsAppCloudSender:
    """Meta WhatsApp Business Cloud API driver.

    Endpoint: POST https://graph.facebook.com/{api_version}/{phone_number_id}/messages
    Auth:     Bearer access_token
    Body:     {messaging_product: "whatsapp", to, type: "text", text: {body}}
    """

    access_token: str
    phone_number_id: str
    api_version: str
    timeout_seconds: float
    name: str = "whatsapp_cloud"

    async def send(self, *, to_phone: str, body: str) -> OutreachSendResult:
        url = (
            f"https://graph.facebook.com/{self.api_version}/"
            f"{self.phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            # Meta returns useful JSON in the body on errors; surface a
            # condensed version so the ops dashboard shows the actual
            # WhatsApp error code (e.g. recipient not opted-in).
            try:
                detail = exc.response.json().get("error", {})
                msg = detail.get("message") or str(exc)
            except Exception:  # noqa: BLE001
                msg = str(exc)
            logger.warning(
                "[OUTREACH][WHATSAPP] HTTP error to=%s status=%s detail=%s",
                to_phone,
                exc.response.status_code,
                msg,
            )
            return OutreachSendResult(
                status="failed",
                provider=self.name,
                error_message=_truncate(msg, 500),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[OUTREACH][WHATSAPP] send failed to=%s: %s", to_phone, exc)
            return OutreachSendResult(
                status="failed",
                provider=self.name,
                error_message=_truncate(str(exc), 500),
            )

        # Cloud API echoes message ids in messages[0].id.
        message_id: str | None = None
        try:
            message_id = data.get("messages", [{}])[0].get("id")
        except Exception:  # noqa: BLE001
            message_id = None

        logger.info(
            "[OUTREACH][WHATSAPP] sent to=%s message_id=%s",
            to_phone,
            message_id,
        )
        return OutreachSendResult(
            status="sent",
            provider=self.name,
            provider_message_id=message_id,
        )


@dataclass(frozen=True)
class DryRunWhatsAppSender:
    name: str = "dry_run"

    async def send(self, *, to_phone: str, body: str) -> OutreachSendResult:
        logger.info(
            "[OUTREACH][WHATSAPP][DRYRUN] to=%s body_chars=%d",
            to_phone,
            len(body or ""),
        )
        return OutreachSendResult(
            status="sent",
            provider=self.name,
            provider_message_id=f"dryrun-{uuid.uuid4()}",
            is_dry_run=True,
        )


# ---------------------------------------------------------------------------
# Factories - selected once per worker process at startup-ish.
# ---------------------------------------------------------------------------


def build_email_sender() -> EmailSender:
    """Return the EmailSender configured by the environment.

    Selection rules (intentionally explicit to make ops auditable):
      1. If OUTREACH_DRY_RUN=true -> DryRunEmailSender unconditionally.
      2. Else if SMTP_HOST and SMTP_FROM are both set -> SmtpEmailSender.
      3. Else fall back to DryRunEmailSender (with a warning log) so the
         pipeline keeps working without breaking dev environments.
    """
    settings = get_settings()
    if settings.OUTREACH_DRY_RUN:
        logger.info("[OUTREACH] email driver=dry_run (forced via OUTREACH_DRY_RUN)")
        return DryRunEmailSender(from_address=settings.SMTP_FROM or "no-reply@local")

    if settings.SMTP_HOST and settings.SMTP_FROM:
        logger.info(
            "[OUTREACH] email driver=smtp host=%s port=%d tls=%s from=%s",
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            settings.SMTP_USE_TLS,
            settings.SMTP_FROM,
        )
        return SmtpEmailSender(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME or None,
            password=settings.SMTP_PASSWORD or None,
            use_tls=settings.SMTP_USE_TLS,
            from_address=settings.SMTP_FROM,
            timeout_seconds=settings.SMTP_TIMEOUT_SECONDS,
        )

    logger.warning(
        "[OUTREACH] email driver=dry_run (SMTP_HOST or SMTP_FROM missing). "
        "Set both env vars to enable real email sends."
    )
    return DryRunEmailSender(from_address=settings.SMTP_FROM or "no-reply@local")


def build_whatsapp_sender() -> WhatsAppSender:
    """Return the WhatsApp sender configured by the environment.

    Selection rules:
      1. If OUTREACH_DRY_RUN=true -> DryRunWhatsAppSender unconditionally.
      2. Else if WHATSAPP_PROVIDER='meta_cloud' AND both
         WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN are set ->
         WhatsAppCloudSender.
      3. Else fall back to DryRunWhatsAppSender.
    """
    settings = get_settings()
    if settings.OUTREACH_DRY_RUN:
        logger.info("[OUTREACH] whatsapp driver=dry_run (forced via OUTREACH_DRY_RUN)")
        return DryRunWhatsAppSender()

    if (
        settings.WHATSAPP_PROVIDER == "meta_cloud"
        and settings.WHATSAPP_PHONE_NUMBER_ID
        and settings.WHATSAPP_ACCESS_TOKEN
    ):
        logger.info(
            "[OUTREACH] whatsapp driver=meta_cloud phone_id=%s api=%s",
            settings.WHATSAPP_PHONE_NUMBER_ID,
            settings.WHATSAPP_API_VERSION,
        )
        return WhatsAppCloudSender(
            access_token=settings.WHATSAPP_ACCESS_TOKEN,
            phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID,
            api_version=settings.WHATSAPP_API_VERSION,
            timeout_seconds=settings.WHATSAPP_TIMEOUT_SECONDS,
        )

    logger.warning(
        "[OUTREACH] whatsapp driver=dry_run "
        "(WHATSAPP_PROVIDER or credentials not configured)."
    )
    return DryRunWhatsAppSender()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


PHONE_DIGITS_RE = re.compile(r"\D")


def normalise_phone(raw: str | None) -> str | None:
    """Reduce a free-text phone string to a digits-only E.164-ish form.

    Returns None when the result is too short to be a real number. Meta's
    Cloud API requires the number with country code, no leading '+' and
    no separators - this matches that format.
    """
    if not raw:
        return None
    digits = PHONE_DIGITS_RE.sub("", raw)
    return digits if len(digits) >= 8 else None


EMAIL_BASIC_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_email(raw: str | None) -> bool:
    """Cheap email validation - sufficient gate before SMTP.

    Full RFC compliance is the SMTP server's job; we only need to reject
    obvious typos and empty strings before paying the round-trip.
    """
    return bool(raw) and bool(EMAIL_BASIC_RE.match(raw or ""))


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


__all__ = [
    "AttemptStatus",
    "DryRunEmailSender",
    "DryRunWhatsAppSender",
    "EmailSender",
    "OutreachChannel",
    "OutreachSendResult",
    "OutreachStatus",
    "SmtpEmailSender",
    "WhatsAppCloudSender",
    "WhatsAppSender",
    "build_email_sender",
    "build_whatsapp_sender",
    "is_email",
    "normalise_phone",
]


# Silence pyflakes for the asyncio import - kept available for future
# rate limiting helpers without churn.
_ = asyncio
