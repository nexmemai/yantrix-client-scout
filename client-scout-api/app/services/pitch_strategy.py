"""Structured pitch strategy for channel-specific Yantrix outreach."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from app.services.pitch_context import PitchContext


@dataclass(frozen=True)
class StructuredPitch:
    whatsapp_message: str
    whatsapp_follow_up: str
    email_subject: str
    email_body: str
    call_opener: str
    pain_points_used: list[str]
    recommended_services: list[str]
    personalization_notes: list[str]


def build_structured_pitch_prompt(context: PitchContext, niche_guidance: str | None = None) -> str:
    payload = {
        "company": "Yantrix Labs",
        "instruction": (
            "Write professional outbound sales copy using only provided facts. "
            "Do not invent revenue, traffic, rankings, or contact names. "
            "Do not mention scraping, internal scores, field names, or audit pipeline."
        ),
        "required_json_keys": [
            "whatsapp_message",
            "whatsapp_follow_up",
            "email_subject",
            "email_body",
            "call_opener",
            "pain_points_used",
            "recommended_services",
            "personalization_notes",
        ],
        "style_rules": {
            "whatsapp_message": "50-90 words, direct, useful, one clear question",
            "email_body": "120-220 words, specific observations, bullet list allowed, clear CTA",
            "tone": "professional, helpful, specific, not pushy",
        },
        "context": _context_payload(context),
    }
    if niche_guidance:
        payload["niche_guidance"] = niche_guidance
    return json.dumps(payload, ensure_ascii=True, indent=2)


def parse_structured_pitch(text: str, context: PitchContext) -> StructuredPitch:
    """Parse LLM JSON, falling back to deterministic copy when invalid."""
    try:
        payload = json.loads(_strip_json_fence(text))
        return _coerce_structured_pitch(payload, context)
    except Exception:
        return build_rule_based_pitch(context)


def build_rule_based_pitch(context: PitchContext) -> StructuredPitch:
    pains = context.pain_points[:3]
    pain_phrases = [point.plain_language for point in pains] or ["a few conversion gaps on the website"]
    impacts = [point.business_impact for point in pains] or ["missed enquiries"]
    services = context.recommended_services[:3] or ["lead capture automation", "website conversion cleanup"]
    greeting = context.contact_name or context.business_name
    city_phrase = f" in {context.city}" if context.city else ""
    trust_line = _trust_line(context)
    cms_line = _cms_line(context)

    whatsapp = (
        f"Hi {greeting}, I was looking at {context.business_name}'s online presence and noticed "
        f"{_join_phrase(pain_phrases[:2])}. For a {context.niche}{city_phrase}, that can mean "
        f"{impacts[0]}. Yantrix Labs can help with {_join_phrase(services[:2])}. "
        "Worth a quick 10-minute chat this week?"
    )

    bullets = "\n".join(f"- {phrase}" for phrase in pain_phrases)
    email = (
        f"Hi {greeting},\n\n"
        f"I was reviewing {context.business_name}'s online presence and noticed a few specific conversion gaps:\n\n"
        f"{bullets}\n\n"
        f"For a {context.niche}{city_phrase}, these gaps can quietly reduce enquiries from visitors who are already interested. "
        f"{trust_line}{cms_line}\n\n"
        f"Yantrix Labs can help with {_join_phrase(services)} so more visitors become booked appointments or qualified leads "
        "without adding more manual follow-up work.\n\n"
        "Would it be worth a quick 10-minute call this week?"
    )

    return StructuredPitch(
        whatsapp_message=_limit_words(whatsapp, 95),
        whatsapp_follow_up=(
            f"Just checking if improving {_join_phrase(services[:2])} is a priority for {context.business_name} this month."
        ),
        email_subject=f"Quick idea for {context.business_name}",
        email_body=email,
        call_opener=(
            f"I noticed {context.business_name} has demand signals, but visitors may not have a fast path to enquire or book."
        ),
        pain_points_used=pain_phrases,
        recommended_services=services,
        personalization_notes=context.personalization_notes,
    )


def structured_pitch_metadata(pitch: StructuredPitch) -> str:
    return json.dumps(asdict(pitch), ensure_ascii=True)


def structured_pitch_from_metadata(value: str | None) -> StructuredPitch | None:
    if not value:
        return None
    try:
        payload = json.loads(value)
        return StructuredPitch(
            whatsapp_message=str(payload.get("whatsapp_message") or ""),
            whatsapp_follow_up=str(payload.get("whatsapp_follow_up") or ""),
            email_subject=str(payload.get("email_subject") or ""),
            email_body=str(payload.get("email_body") or ""),
            call_opener=str(payload.get("call_opener") or ""),
            pain_points_used=_string_list(payload.get("pain_points_used")),
            recommended_services=_string_list(payload.get("recommended_services")),
            personalization_notes=_string_list(payload.get("personalization_notes")),
        )
    except Exception:
        return None


def _coerce_structured_pitch(payload: dict[str, Any], context: PitchContext) -> StructuredPitch:
    fallback = build_rule_based_pitch(context)
    return StructuredPitch(
        whatsapp_message=_require_text(payload.get("whatsapp_message"), fallback.whatsapp_message),
        whatsapp_follow_up=_require_text(payload.get("whatsapp_follow_up"), fallback.whatsapp_follow_up),
        email_subject=_require_text(payload.get("email_subject"), fallback.email_subject),
        email_body=_require_text(payload.get("email_body"), fallback.email_body),
        call_opener=_require_text(payload.get("call_opener"), fallback.call_opener),
        pain_points_used=_string_list(payload.get("pain_points_used")) or fallback.pain_points_used,
        recommended_services=_string_list(payload.get("recommended_services")) or fallback.recommended_services,
        personalization_notes=_string_list(payload.get("personalization_notes")) or fallback.personalization_notes,
    )


def _context_payload(context: PitchContext) -> dict[str, Any]:
    return {
        "business_name": context.business_name,
        "niche": context.niche,
        "city": context.city,
        "website_url": context.website_url,
        "contact_name": context.contact_name,
        "contact_title": context.contact_title,
        "contact_confidence": context.contact_confidence,
        "rating": context.rating,
        "review_count": context.review_count,
        "old_score": context.overall_score,
        "old_fit_bucket": context.old_fit_bucket,
        "agency_fit_score": context.agency_fit_score,
        "agency_fit_bucket": context.agency_fit_bucket,
        "opportunity_types": context.opportunity_types,
        "estimated_deal_value": context.estimated_deal_value,
        "score_breakdown": context.score_breakdown,
        "audit_signals": context.audit_signals,
        "load_time_ms": context.load_time_ms,
        "page_speed_score": context.page_speed_score,
        "tech_stack": context.tech_stack,
        "cms_detected": context.cms_detected,
        "pain_points": [asdict(point) for point in context.pain_points],
        "recommended_services": context.recommended_services,
        "personalization_notes": context.personalization_notes,
    }


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    return cleaned


def _require_text(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _trust_line(context: PitchContext) -> str:
    if context.rating and context.review_count:
        return (
            f"With {context.review_count} reviews and a {context.rating:.1f} rating, "
            "there is already trust; the missing piece appears to be conversion. "
        )
    if context.review_count:
        return f"With {context.review_count} reviews, there is already public proof to build on. "
    return ""


def _cms_line(context: PitchContext) -> str:
    if context.cms_detected:
        return f"Since the site appears to use {context.cms_detected}, some fixes may be possible without a full rebuild. "
    return ""


def _join_phrase(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _limit_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(".,") + "."
