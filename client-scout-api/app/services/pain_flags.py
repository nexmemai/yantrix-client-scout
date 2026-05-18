"""Derived audit pain flags used by sales scoring and dashboard highlights."""

from __future__ import annotations

from typing import Any

SLOW_LOAD_THRESHOLD_MS = 3_000

CMS_CANDIDATES = {
    "wordpress": "WordPress",
    "shopify": "Shopify",
    "wix": "Wix",
    "squarespace": "Squarespace",
    "webflow": "Webflow",
    "joomla": "Joomla",
    "drupal": "Drupal",
}


def build_pain_flags(audit_like: Any) -> dict[str, bool]:
    """Build stable pain flags from audit booleans without changing source fields."""
    load_time_ms = getattr(audit_like, "load_time_ms", None) or 0
    has_website = bool(getattr(audit_like, "has_website", False))
    return {
        "pain_no_website": not has_website,
        "pain_no_booking": not bool(getattr(audit_like, "has_booking", False)),
        "pain_no_whatsapp": not bool(getattr(audit_like, "has_whatsapp", False)),
        "pain_no_form": not bool(getattr(audit_like, "has_forms", False)),
        "pain_no_ssl": not bool(getattr(audit_like, "ssl_valid", False)),
        "pain_not_mobile": not bool(getattr(audit_like, "mobile_friendly", False)),
        "pain_slow_load": load_time_ms > SLOW_LOAD_THRESHOLD_MS,
        "pain_no_cta": not bool(getattr(audit_like, "has_cta", False)),
        "pain_no_chatbot": not bool(getattr(audit_like, "has_chatbot", False)),
        "pain_no_facebook": not bool(getattr(audit_like, "has_facebook", False)),
        "pain_no_instagram": not bool(getattr(audit_like, "has_instagram", False)),
    }


def detect_cms(tech_stack: list[str] | None) -> str | None:
    """Return the first recognised CMS from the existing tech stack list."""
    if not tech_stack:
        return None
    for item in tech_stack:
        normalized = item.strip().lower()
        if normalized in CMS_CANDIDATES:
            return CMS_CANDIDATES[normalized]
    return None
