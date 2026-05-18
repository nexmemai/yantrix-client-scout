"""Rule-based agency-fit scoring layered on top of the existing score model."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.audit import Audit
from app.models.business import Business

HOT_BUCKET = "hot"
WARM_BUCKET = "warm"
COLD_BUCKET = "cold"
SKIP_BUCKET = "skip"

HIGH_VALUE_NICHES = {
    "clinic",
    "coaching",
    "dental",
    "hotel",
    "lawyer",
    "physiotherapy",
    "real_estate",
    "salon",
    "spa",
    "veterinary",
}


@dataclass(frozen=True)
class AgencyFitResult:
    agency_fit_score: int
    agency_fit_bucket: str
    opportunity_types: list[str]
    estimated_deal_value: int


def calculate_agency_fit(business: Business, audit: Audit) -> AgencyFitResult:
    """Calculate agency opportunity using visible business and audit signals."""
    score = 0
    opportunities: list[str] = []

    if not audit.has_booking:
        score += 15
        opportunities.append("booking_system")
    if not audit.has_whatsapp:
        score += 10
        opportunities.append("whatsapp_integration")
    if not audit.has_chatbot:
        score += 10
        opportunities.append("chatbot")
    if not audit.has_forms:
        score += 12
        opportunities.append("lead_capture_form")
    if not audit.has_cta:
        score += 8
        opportunities.append("conversion_cta")
    if _is_slow(audit):
        score += 10
        opportunities.append("speed_optimization")
    if not audit.mobile_friendly:
        score += 15
        opportunities.append("mobile_optimization")
    if not audit.ssl_valid:
        score += 8
        opportunities.append("ssl_fix")
    if _has_tech(audit, "WordPress"):
        score += 8
        opportunities.append("website_rebuild")
    if (business.review_count or 0) > 100:
        score += 10
    if _as_float(business.rating) >= 4.2:
        score += 8
    if _is_high_value_niche(business):
        score += 10

    agency_fit_score = min(100, max(0, score))
    bucket = bucket_for_agency_fit(agency_fit_score)
    return AgencyFitResult(
        agency_fit_score=agency_fit_score,
        agency_fit_bucket=bucket,
        opportunity_types=_dedupe(opportunities),
        estimated_deal_value=estimate_deal_value(bucket, _is_high_value_niche(business)),
    )


def bucket_for_agency_fit(score: int) -> str:
    if score >= 75:
        return HOT_BUCKET
    if score >= 50:
        return WARM_BUCKET
    if score >= 25:
        return COLD_BUCKET
    return SKIP_BUCKET


def estimate_deal_value(bucket: str, high_value_niche: bool) -> int:
    if bucket == HOT_BUCKET:
        return 150_000 if high_value_niche else 100_000
    if bucket == WARM_BUCKET:
        return 75_000 if high_value_niche else 50_000
    if bucket == COLD_BUCKET:
        return 25_000
    return 0


def _is_slow(audit: Audit) -> bool:
    if audit.page_speed_score is not None:
        return audit.page_speed_score < 50
    return (audit.load_time_ms or 0) > 3_000


def _has_tech(audit: Audit, tech_name: str) -> bool:
    return tech_name.lower() in {item.lower() for item in (audit.tech_stack or [])}


def _is_high_value_niche(business: Business) -> bool:
    niche = (business.niche or "").strip().lower()
    if niche in HIGH_VALUE_NICHES:
        return True
    category = (business.category or "").strip().lower()
    return any(keyword in category for keyword in HIGH_VALUE_NICHES)


def _as_float(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
