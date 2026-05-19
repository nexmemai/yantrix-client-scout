"""Build data-rich, channel-ready pitch context from Scout lead signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.models.audit import Audit
from app.models.business import Business
from app.models.score import Score


@dataclass(frozen=True)
class PitchPainPoint:
    flag: str
    plain_language: str
    business_impact: str
    service: str


@dataclass(frozen=True)
class PitchContext:
    business_name: str
    niche: str
    city: str | None
    website_url: str | None
    contact_name: str | None
    contact_title: str | None
    contact_confidence: int | None
    rating: float | None
    review_count: int | None
    overall_score: int
    old_fit_bucket: str
    agency_fit_score: int | None
    agency_fit_bucket: str | None
    opportunity_types: list[str]
    estimated_deal_value: int | None
    score_breakdown: dict[str, int | None]
    audit_signals: dict[str, bool]
    load_time_ms: int | None
    page_speed_score: int | None
    tech_stack: list[str]
    cms_detected: str | None
    pain_points: list[PitchPainPoint] = field(default_factory=list)
    recommended_services: list[str] = field(default_factory=list)
    personalization_notes: list[str] = field(default_factory=list)


PAIN_MAP: dict[str, tuple[str, str, str]] = {
    "pain_no_booking": (
        "visitors cannot book appointments directly",
        "missed appointment enquiries",
        "Online booking funnel",
    ),
    "pain_no_whatsapp": (
        "there is no clear WhatsApp follow-up path",
        "slower replies to mobile-first prospects",
        "WhatsApp lead follow-up automation",
    ),
    "pain_no_form": (
        "there is no obvious enquiry form",
        "visitors have fewer ways to become leads",
        "Lead form and CRM capture",
    ),
    "pain_no_ssl": (
        "the site may not show as secure",
        "lower trust before visitors share details",
        "SSL and trust cleanup",
    ),
    "pain_not_mobile": (
        "the mobile experience appears weak",
        "mobile visitors may leave before enquiring",
        "Mobile UX cleanup",
    ),
    "pain_slow_load": (
        "the website appears slow to load",
        "impatient visitors may drop before taking action",
        "Website speed improvement",
    ),
    "pain_no_cta": (
        "the site does not strongly guide visitors to act",
        "interested visitors may not know the next step",
        "Conversion CTA improvement",
    ),
    "pain_no_chatbot": (
        "there is no automated first-response assistant",
        "after-hours enquiries may go unanswered",
        "AI first-response chatbot",
    ),
    "pain_no_facebook": (
        "Facebook trust signals are limited",
        "visitors see fewer proof points",
        "Local trust signal cleanup",
    ),
    "pain_no_instagram": (
        "Instagram trust signals are limited",
        "visual/social proof may be underused",
        "Social proof cleanup",
    ),
}

SERVICE_MAP: dict[str, str] = {
    "booking_system": "Online booking funnel",
    "whatsapp_integration": "WhatsApp lead follow-up automation",
    "chatbot": "AI first-response chatbot",
    "lead_capture_form": "Lead form and CRM capture",
    "speed_optimization": "Website speed improvement",
    "mobile_optimization": "Mobile UX cleanup",
    "ssl_fix": "SSL and trust cleanup",
    "website_rebuild": "Conversion-focused website rebuild",
    "local_seo": "Local SEO visibility improvement",
    "crm_followup": "CRM follow-up automation",
    "conversion_cta": "Conversion CTA improvement",
}


def build_pitch_context(business: Business, audit: Audit, score: Score) -> PitchContext:
    opportunity_types = score.opportunity_types or []
    pain_points = _pain_points_from_audit(audit)
    services = _dedupe(
        [point.service for point in pain_points]
        + [SERVICE_MAP[item] for item in opportunity_types if item in SERVICE_MAP]
    )[:5]
    return PitchContext(
        business_name=business.name,
        niche=business.niche or business.category or "local business",
        city=business.city,
        website_url=business.website_url,
        contact_name=business.contact_name,
        contact_title=business.contact_title,
        contact_confidence=business.contact_confidence,
        rating=_as_float(business.rating),
        review_count=business.review_count,
        overall_score=score.overall_score,
        old_fit_bucket=_old_fit(score.overall_score),
        agency_fit_score=score.agency_fit_score,
        agency_fit_bucket=score.agency_fit_bucket,
        opportunity_types=opportunity_types,
        estimated_deal_value=score.estimated_deal_value,
        score_breakdown={
            "website_quality": score.website_quality,
            "online_presence": score.online_presence,
            "conversion_readiness": score.conversion_readiness,
            "urgency": score.urgency,
        },
        audit_signals={
            "website": audit.has_website,
            "ssl": audit.ssl_valid,
            "mobile": audit.mobile_friendly,
            "form": audit.has_forms,
            "cta": audit.has_cta,
            "whatsapp": audit.has_whatsapp,
            "booking": audit.has_booking,
            "chatbot": audit.has_chatbot,
            "facebook": audit.has_facebook,
            "instagram": audit.has_instagram,
        },
        load_time_ms=audit.load_time_ms,
        page_speed_score=audit.page_speed_score,
        tech_stack=audit.tech_stack or [],
        cms_detected=audit.cms_detected,
        pain_points=pain_points,
        recommended_services=services,
        personalization_notes=_personalization_notes(business, audit, score),
    )


def _pain_points_from_audit(audit: Audit) -> list[PitchPainPoint]:
    flags = audit.pain_flags or {}
    points: list[PitchPainPoint] = []
    for flag, active in flags.items():
        if not active or flag not in PAIN_MAP:
            continue
        plain, impact, service = PAIN_MAP[flag]
        points.append(PitchPainPoint(flag=flag, plain_language=plain, business_impact=impact, service=service))
    if not points:
        fallback_flags = {
            "pain_no_booking": not audit.has_booking,
            "pain_no_whatsapp": not audit.has_whatsapp,
            "pain_no_form": not audit.has_forms,
            "pain_no_cta": not audit.has_cta,
            "pain_no_chatbot": not audit.has_chatbot,
            "pain_not_mobile": not audit.mobile_friendly,
        }
        for flag, active in fallback_flags.items():
            if active:
                plain, impact, service = PAIN_MAP[flag]
                points.append(PitchPainPoint(flag=flag, plain_language=plain, business_impact=impact, service=service))
    return points[:5]


def _personalization_notes(business: Business, audit: Audit, score: Score) -> list[str]:
    notes: list[str] = []
    if business.rating and business.review_count:
        notes.append(f"{business.review_count} reviews with a {float(business.rating):.1f} rating")
    elif business.review_count:
        notes.append(f"{business.review_count} public reviews")
    if audit.cms_detected:
        notes.append(f"site appears to use {audit.cms_detected}")
    elif audit.tech_stack:
        notes.append(f"tech stack includes {', '.join(audit.tech_stack[:2])}")
    if score.agency_fit_bucket:
        notes.append(f"{score.agency_fit_bucket} agency-fit opportunity")
    if score.estimated_deal_value:
        notes.append(f"estimated opportunity value around Rs {score.estimated_deal_value:,}")
    return notes[:4]


def _old_fit(score: int) -> str:
    if score >= 60:
        return "high-fit"
    if score >= 40:
        return "mid-fit"
    return "low-fit"


def _as_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
