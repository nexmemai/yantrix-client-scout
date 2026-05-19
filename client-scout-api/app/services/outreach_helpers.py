"""Manual outreach helpers derived from business contact data and pitch text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

from app.models.business import Business
from app.models.pitch import Pitch


@dataclass(frozen=True)
class OutreachPayload:
    whatsapp_link: str | None
    email_subject: str
    email_body: str


def build_outreach_payload(business: Business, pitch: Pitch | None) -> OutreachPayload:
    pitch_text = _pitch_text(business, pitch)
    phone = business.contact_phone or business.phone
    return OutreachPayload(
        whatsapp_link=_whatsapp_link(phone, pitch_text),
        email_subject=f"Quick idea for {business.name}",
        email_body=pitch_text,
    )


def _pitch_text(business: Business, pitch: Pitch | None) -> str:
    if pitch and pitch.pitch_notes:
        return pitch.pitch_notes.strip()
    niche = business.niche or business.category or "your business"
    return (
        f"Hi {business.name}, I noticed a few quick wins that could help your "
        f"{niche} get more enquiries and bookings online. Would you be open to "
        "a short call this week?"
    )


def _whatsapp_link(phone: str | None, message: str) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 8:
        return None
    return f"https://wa.me/{digits}?text={quote(message)}"
