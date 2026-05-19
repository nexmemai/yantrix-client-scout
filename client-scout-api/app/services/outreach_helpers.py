"""Manual outreach helpers derived from business contact data and pitch text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

from app.models.business import Business
from app.models.pitch import Pitch
from app.services.pitch_strategy import structured_pitch_from_metadata


@dataclass(frozen=True)
class OutreachPayload:
    whatsapp_link: str | None
    whatsapp_message: str
    whatsapp_follow_up: str | None
    email_subject: str
    email_body: str
    call_opener: str | None
    pain_points_used: list[str]
    recommended_services: list[str]
    personalization_notes: list[str]


def build_outreach_payload(business: Business, pitch: Pitch | None) -> OutreachPayload:
    structured = structured_pitch_from_metadata(pitch.objection_handlers if pitch else None)
    pitch_text = _pitch_text(business, pitch)
    whatsapp_message = (
        structured.whatsapp_message.strip()
        if structured and structured.whatsapp_message.strip()
        else pitch_text
    )
    email_subject = (
        structured.email_subject.strip()
        if structured and structured.email_subject.strip()
        else (pitch.subject_line.strip() if pitch and pitch.subject_line else f"Quick idea for {business.name}")
    )
    email_body = (
        structured.email_body.strip()
        if structured and structured.email_body.strip()
        else pitch_text
    )
    phone = business.contact_phone or business.phone
    return OutreachPayload(
        whatsapp_link=_whatsapp_link(phone, whatsapp_message),
        whatsapp_message=whatsapp_message,
        whatsapp_follow_up=structured.whatsapp_follow_up.strip()
        if structured and structured.whatsapp_follow_up.strip()
        else None,
        email_subject=email_subject,
        email_body=email_body,
        call_opener=structured.call_opener.strip()
        if structured and structured.call_opener.strip()
        else None,
        pain_points_used=structured.pain_points_used if structured else [],
        recommended_services=(
            structured.recommended_services
            if structured and structured.recommended_services
            else (pitch.recommended_services if pitch and pitch.recommended_services else [])
        ),
        personalization_notes=structured.personalization_notes if structured else [],
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
