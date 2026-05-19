"""Cheap best-effort contact enrichment from audited website HTML."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.models.business import Business

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
MAILTO_RE = re.compile(r"(?i)mailto:([^\"'>?\s]+)")
TEL_RE = re.compile(r"(?i)tel:([^\"'>]+)")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
LINKEDIN_RE = re.compile(r"(?i)https?://(?:www\.)?linkedin\.com/(?:in|company)/[^\s\"'<>]+")
RECENT_YEAR_RE = re.compile(r"\b(202[5-9]|203\d)\b")
TITLE_RE = re.compile(
    r"(?i)\b(owner|founder|director|manager|principal|partner|doctor|dentist|clinic manager)\b"
)
NAME_WITH_TITLE_RE = re.compile(
    r"(?i)\b(?:Dr\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*[-,|]\s*"
    r"(Owner|Founder|Director|Manager|Principal|Partner|Doctor|Dentist|Clinic Manager)\b"
)
TITLE_WITH_NAME_RE = re.compile(
    r"(?i)\b(Owner|Founder|Director|Manager|Principal|Partner|Doctor|Dentist|Clinic Manager)"
    r"\s*[-:,]\s*(?:Dr\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b"
)

GENERIC_EMAIL_PREFIXES = {"admin", "contact", "hello", "hi", "info", "office", "support"}
CONTACT_PATHS = ("/contact", "/contact-us", "/about", "/about-us")


@dataclass(frozen=True)
class ContactEnrichmentResult:
    contact_name: str | None = None
    contact_title: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    contact_linkedin_url: str | None = None
    contact_confidence: int = 0
    primary_language: str | None = None
    has_recent_updates: bool | None = None


async def enrich_contact_from_site(
    business: Business,
    homepage_html: str,
    base_url: str,
) -> ContactEnrichmentResult:
    """Extract contact signals from homepage and at most one contact/about page."""
    homepage = _clean_html_text(homepage_html)
    candidate_pages = [homepage_html]

    if not _has_strong_contact(candidate_pages[0]):
        extra_html = await _fetch_first_contact_page(base_url)
        if extra_html:
            candidate_pages.append(extra_html)

    combined_html = "\n".join(candidate_pages)
    combined_text = _clean_html_text(combined_html)
    email = _first_email(combined_html)
    phone = _first_phone(combined_html)
    linkedin = _first_match(LINKEDIN_RE, combined_html)
    contact_name, contact_title = _extract_name_title(combined_text)
    primary_language = _detect_primary_language(combined_text)

    return ContactEnrichmentResult(
        contact_name=contact_name,
        contact_title=contact_title,
        contact_email=email,
        contact_phone=phone,
        contact_linkedin_url=linkedin,
        contact_confidence=_confidence(email, phone, linkedin, contact_name, contact_title),
        primary_language=primary_language,
        has_recent_updates=bool(RECENT_YEAR_RE.search(combined_text)),
    )


def apply_contact_enrichment(business: Business, result: ContactEnrichmentResult) -> None:
    """Apply only non-empty enrichment fields to the business row."""
    if result.contact_name:
        business.contact_name = result.contact_name
    if result.contact_title:
        business.contact_title = result.contact_title
    if result.contact_email:
        business.contact_email = result.contact_email
    if result.contact_phone:
        business.contact_phone = result.contact_phone
    if result.contact_linkedin_url:
        business.contact_linkedin_url = result.contact_linkedin_url
    if result.contact_confidence:
        business.contact_confidence = result.contact_confidence
    if result.primary_language:
        business.primary_language = result.primary_language
    if result.has_recent_updates is not None:
        business.has_recent_updates = result.has_recent_updates


async def _fetch_first_contact_page(base_url: str) -> str | None:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return None

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        for path in CONTACT_PATHS:
            try:
                response = await client.get(urljoin(base_url, path))
                content_type = response.headers.get("content-type", "")
                if response.status_code < 400 and "text/html" in content_type:
                    return response.text
            except httpx.HTTPError:
                continue
    return None


def _has_strong_contact(raw_html: str) -> bool:
    return bool(MAILTO_RE.search(raw_html) or LINKEDIN_RE.search(raw_html))


def _first_email(raw_html: str) -> str | None:
    mailto = _first_match(MAILTO_RE, raw_html)
    if mailto:
        return _normalise_email(mailto)
    emails = [_normalise_email(match.group(0)) for match in EMAIL_RE.finditer(raw_html)]
    emails = [email for email in emails if email]
    if not emails:
        return None
    return sorted(emails, key=_email_rank)[0]


def _first_phone(raw_html: str) -> str | None:
    tel = _first_match(TEL_RE, raw_html)
    if tel:
        return _normalise_phone(tel)
    for match in PHONE_RE.finditer(raw_html):
        phone = _normalise_phone(match.group(0))
        if phone and len(re.sub(r"\D", "", phone)) >= 8:
            return phone
    return None


def _extract_name_title(text: str) -> tuple[str | None, str | None]:
    match = NAME_WITH_TITLE_RE.search(text)
    if match:
        return _clean_person(match.group(1)), _clean_title(match.group(2))
    match = TITLE_WITH_NAME_RE.search(text)
    if match:
        return _clean_person(match.group(2)), _clean_title(match.group(1))
    title_match = TITLE_RE.search(text)
    if title_match:
        return None, _clean_title(title_match.group(1))
    return None, None


def _confidence(
    email: str | None,
    phone: str | None,
    linkedin: str | None,
    name: str | None,
    title: str | None,
) -> int:
    if email and name and title:
        return 90
    if email and (linkedin or title):
        return 75
    if email:
        return 45 if _is_generic_email(email) else 60
    if phone and (name or title):
        return 45
    if phone or linkedin or name or title:
        return 25
    return 0


def _detect_primary_language(text: str) -> str | None:
    ascii_letters = sum(1 for char in text if "a" <= char.lower() <= "z")
    non_ascii_letters = sum(1 for char in text if char.isalpha() and ord(char) > 127)
    if ascii_letters == 0 and non_ascii_letters == 0:
        return None
    return "en" if ascii_letters >= non_ascii_letters else "other"


def _clean_html_text(raw_html: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html)
    text = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _first_match(pattern: re.Pattern[str], value: str) -> str | None:
    match = pattern.search(value)
    return match.group(1 if pattern is MAILTO_RE or pattern is TEL_RE else 0).strip() if match else None


def _normalise_email(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().strip(".,;:").lower()


def _normalise_phone(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", value.strip().strip(".,;:"))


def _email_rank(email: str) -> tuple[int, str]:
    return (1 if _is_generic_email(email) else 0, email)


def _is_generic_email(email: str) -> bool:
    prefix = email.split("@", 1)[0].lower()
    return prefix in GENERIC_EMAIL_PREFIXES


def _clean_person(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    cleaned = re.sub(r"(?i)\s+(Email|Call|Phone|Contact)$", "", cleaned).strip()
    return cleaned


def _clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().title()
