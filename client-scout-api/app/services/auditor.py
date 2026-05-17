"""
services/auditor.py — Core website audit engine using Playwright.

Given a website_url, this module:
  1. Navigates with desktop viewport to collect all signals
  2. Navigates again with 375px mobile viewport for mobile-friendliness
  3. Evaluates 15+ signals (HTTPS, forms, WhatsApp, booking, tel, SEO, social, speed)
  4. Returns an AuditSignals dataclass ready for DB persistence

Concurrency is controlled externally via asyncio.Semaphore in the worker.
"""

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field

from playwright.async_api import (
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

logger = logging.getLogger(__name__)

DNS_ERROR_MARKERS = (
    "ERR_NAME_NOT_RESOLVED",
    "ERR_DNS_TIMED_OUT",
    "ERR_DNS_MALFORMED_RESPONSE",
)

# ---------------------------------------------------------------------------
# Booking widget fingerprints (iframe src / script src / link href)
# ---------------------------------------------------------------------------

BOOKING_PATTERNS: list[str] = [
    "calendly.com",
    "acuityscheduling.com",
    "appointy.com",
    "simplybook.me",
    "setmore.com",
    "square.site",
    "booksy.com",
    "practo.com",
    "zocdoc.com",
    "docprime.com",
    "healthifyme.com",
    "lybrate.com",
    "styleseat.com",
    "fresha.com",
    "vagaro.com",
    "mindbodyonline.com",
    "10to8.com",
    "book.ly",
    "hubspot.*meetings",
]

# Social link patterns
SOCIAL_PATTERNS: dict[str, list[str]] = {
    "facebook": ["facebook.com", "fb.com"],
    "instagram": ["instagram.com"],
    "linkedin": ["linkedin.com"],
    "twitter": ["twitter.com", "x.com"],
    "whatsapp": ["wa.me", "api.whatsapp.com", "whatsapp.com/send"],
}

# Common chatbot fingerprints (script src / iframe src)
CHATBOT_PATTERNS: list[str] = [
    "tawk.to",
    "intercom.io",
    "crisp.chat",
    "freshchat.com",
    "drift.com",
    "tidio.com",
    "livechat.com",
    "zendesk.com/embeddable",
    "zoho.com/salesiq",
    "chatbot.com",
]

# Tech stack detection (script src / meta generator)
TECH_PATTERNS: dict[str, list[str]] = {
    "WordPress": ["wp-content", "wp-includes"],
    "Wix": ["wix.com", "_wix_"],
    "Shopify": ["shopify.com", "myshopify.com"],
    "Squarespace": ["squarespace.com"],
    "Webflow": ["webflow.com"],
    "React": ["react.production.min.js", "__next"],
    "Angular": ["ng-version", "angular.min.js"],
    "Vue": ["vue.min.js", "__vue__"],
    "Joomla": ["/joomla/", "Joomla!"],
    "Drupal": ["/sites/default/files/", "Drupal.settings"],
    "Bootstrap": ["bootstrap.min.css", "bootstrap.bundle"],
}


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class AuditSignals:
    """All collected audit signals. Maps 1:1 to the Audit ORM model."""

    url_checked: str
    has_website: bool = True

    # Connectivity
    ssl_valid: bool = False
    final_url: str = ""              # URL after redirects (detect HTTPS upgrade)
    https_redirected: bool = False   # HTTP → HTTPS redirect happened

    # Above-the-fold UX
    has_forms: bool = False          # <form> visible in top 768px
    has_cta: bool = False            # CTA button text detected
    has_whatsapp: bool = False       # wa.me / whatsapp link anywhere on page
    has_booking: bool = False        # known booking widget iframe/script
    has_chatbot: bool = False        # known chatbot widget

    # Contact signals
    has_tel_links: bool = False      # <a href="tel:...">
    tel_numbers: list[str] = field(default_factory=list)

    # Mobile
    mobile_friendly: bool = False    # viewport meta + no horizontal overflow
    mobile_overflow_px: int = 0      # pixels of horizontal overflow at 375px

    # Performance (heuristic, not real Lighthouse)
    load_time_ms: int = 0           # wall-clock ms from navigationStart to loadEventEnd
    dom_content_loaded_ms: int = 0  # navigationStart → domContentLoadedEventEnd
    page_speed_score: int | None = None  # reserved for PSI (set later)

    # SEO
    has_title: bool = False
    title_text: str = ""
    has_meta_desc: bool = False
    has_h1: bool = False
    has_og_tags: bool = False

    # Social
    has_facebook: bool = False
    has_instagram: bool = False
    has_linkedin: bool = False
    has_twitter: bool = False

    # Tech & raw
    tech_stack: list[str] = field(default_factory=list)
    raw_html_hash: str = ""          # SHA-256 of homepage HTML
    raw_html: str = ""               # full HTML (stored to disk, not DB)

    # Audit metadata
    status: str = "completed"
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------


async def audit_website(url: str, timeout_ms: int = 30_000) -> AuditSignals:
    """
    Audit a website URL using Playwright (Chromium, headless).

    :param url:        The website URL to audit (http:// or https://).
    :param timeout_ms: Per-navigation timeout in milliseconds.
    :returns:          AuditSignals with all collected signals.
    """
    signals = AuditSignals(url_checked=url)

    try:
        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )

            try:
                # ── Pass 1: Desktop (1280×800) ── collect all signals ──────
                page = await browser.new_page(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    java_script_enabled=True,
                )

                t0 = time.monotonic()
                resp = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                dom_loaded_ms = int((time.monotonic() - t0) * 1000)

                # Wait briefly for lazy-loaded elements
                try:
                    await page.wait_for_load_state("networkidle", timeout=5_000)
                except PlaywrightTimeoutError:
                    pass  # Page is slow; proceed with what we have

                load_ms = int((time.monotonic() - t0) * 1000)

                final_url = page.url
                html = await page.content()
                html_lower = html.lower()

                # ── Timing ────────────────────────────────────────────────
                signals.load_time_ms = load_ms
                signals.dom_content_loaded_ms = dom_loaded_ms

                # ── HTTPS / redirect ──────────────────────────────────────
                signals.final_url = final_url
                signals.ssl_valid = final_url.startswith("https://")
                signals.https_redirected = (
                    url.startswith("http://") and final_url.startswith("https://")
                )

                # ── Raw HTML hash ─────────────────────────────────────────
                signals.raw_html = html
                signals.raw_html_hash = hashlib.sha256(html.encode()).hexdigest()

                # ── Forms above the fold ──────────────────────────────────
                signals.has_forms = await _has_forms_above_fold(page)

                # ── CTA buttons ───────────────────────────────────────────
                signals.has_cta = await _detect_cta(page)

                # ── WhatsApp ──────────────────────────────────────────────
                signals.has_whatsapp = _detect_pattern(html_lower, SOCIAL_PATTERNS["whatsapp"])

                # ── Tel links ─────────────────────────────────────────────
                signals.has_tel_links, signals.tel_numbers = await _detect_tel_links(page)

                # ── Booking widget ────────────────────────────────────────
                signals.has_booking = _detect_pattern(html_lower, BOOKING_PATTERNS)

                # ── Chatbot ───────────────────────────────────────────────
                signals.has_chatbot = _detect_pattern(html_lower, CHATBOT_PATTERNS)

                # ── Social links ──────────────────────────────────────────
                signals.has_facebook = _detect_pattern(html_lower, SOCIAL_PATTERNS["facebook"])
                signals.has_instagram = _detect_pattern(html_lower, SOCIAL_PATTERNS["instagram"])
                signals.has_linkedin = _detect_pattern(html_lower, SOCIAL_PATTERNS["linkedin"])
                signals.has_twitter = _detect_pattern(html_lower, SOCIAL_PATTERNS["twitter"])

                # ── SEO ───────────────────────────────────────────────────
                title = await page.title()
                signals.has_title = bool(title.strip())
                signals.title_text = title[:255]

                meta_desc = await page.query_selector("meta[name='description']")
                signals.has_meta_desc = meta_desc is not None

                h1 = await page.query_selector("h1")
                signals.has_h1 = h1 is not None

                og_title = await page.query_selector("meta[property='og:title']")
                signals.has_og_tags = og_title is not None

                # ── Tech stack ────────────────────────────────────────────
                signals.tech_stack = _detect_tech_stack(html_lower)

                await page.close()

                # ── Pass 2: Mobile (375×812) ── check overflow ────────────
                mobile_page = await browser.new_page(
                    viewport={"width": 375, "height": 812},
                    user_agent=(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Mobile/15E148 Safari/604.1"
                    ),
                )
                try:
                    await mobile_page.goto(final_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    await mobile_page.wait_for_load_state("networkidle", timeout=5_000)
                except PlaywrightTimeoutError:
                    pass

                overflow_px, mobile_friendly = await _check_mobile_overflow(mobile_page)
                signals.mobile_overflow_px = overflow_px
                signals.mobile_friendly = mobile_friendly
                await mobile_page.close()

            finally:
                await browser.close()

    except PlaywrightTimeoutError as exc:
        logger.warning("Timeout auditing %s: %s", url, exc)
        signals.status = "failed"
        signals.error_message = f"Timeout: {exc}"

    except Exception as exc:  # noqa: BLE001
        logger.error("Error auditing %s: %s", url, exc, exc_info=True)
        signals.status = "failed"
        message = str(exc)
        if is_dns_resolution_error(message):
            signals.error_message = f"DNS resolution failed: {message[:1900]}"
        else:
            signals.error_message = message[:2000]

    return signals


def is_dns_resolution_error(message: str | None) -> bool:
    """Return True when Playwright reports a DNS resolution failure."""
    if not message:
        return False
    return any(marker in message for marker in DNS_ERROR_MARKERS)


# ---------------------------------------------------------------------------
# Signal extraction helpers
# ---------------------------------------------------------------------------


async def _has_forms_above_fold(page: Page) -> bool:
    """
    Check if any <form> element is visible within the top 768px of the page.
    Uses JS evaluate to get bounding boxes.
    """
    return await page.evaluate("""() => {
        const forms = document.querySelectorAll('form');
        for (const form of forms) {
            const rect = form.getBoundingClientRect();
            if (rect.top < 768 && rect.bottom > 0 && rect.width > 0 && rect.height > 0) {
                return true;
            }
        }
        return false;
    }""")


async def _detect_cta(page: Page) -> bool:
    """
    Detect CTA buttons/links with common action keywords.
    Checks <button>, <a>, and elements with role=button.
    """
    cta_keywords = [
        "book", "schedule", "appointment", "consult", "contact",
        "call us", "get started", "enquire", "enquiry", "whatsapp",
        "chat", "free", "demo", "quote", "register",
    ]
    return await page.evaluate(f"""() => {{
        const keywords = {cta_keywords};
        const selectors = 'button, a, [role="button"], input[type="submit"]';
        const elements = document.querySelectorAll(selectors);
        for (const el of elements) {{
            const text = (el.innerText || el.value || el.ariaLabel || '').toLowerCase();
            if (keywords.some(kw => text.includes(kw))) {{
                return true;
            }}
        }}
        return false;
    }}""")


async def _detect_tel_links(page: Page) -> tuple[bool, list[str]]:
    """Extract all tel: href links from the page."""
    numbers: list[str] = await page.evaluate("""() => {
        const links = document.querySelectorAll('a[href^="tel:"]');
        return Array.from(links).map(a => a.href.replace('tel:', '').trim());
    }""")
    unique = list(dict.fromkeys(numbers))[:5]  # dedupe, cap at 5
    return bool(unique), unique


async def _check_mobile_overflow(page: Page) -> tuple[int, bool]:
    """
    Simulate a 375px viewport and measure horizontal scroll overflow.

    Returns (overflow_pixels, is_mobile_friendly).
    A page is considered mobile-friendly if:
      - It has a viewport meta tag
      - Horizontal overflow is <= 20px (small tolerance for shadows/borders)
    """
    has_viewport_meta: bool = await page.evaluate("""() => {
        const meta = document.querySelector('meta[name="viewport"]');
        return meta !== null && meta.content.includes('width');
    }""")

    scroll_width: int = await page.evaluate("""() => {
        return Math.max(
            document.body.scrollWidth,
            document.documentElement.scrollWidth
        );
    }""")

    overflow_px = max(0, scroll_width - 375)
    mobile_friendly = has_viewport_meta and overflow_px <= 20

    return overflow_px, mobile_friendly


def _detect_pattern(html_lower: str, patterns: list[str]) -> bool:
    """Return True if any pattern string appears in the lowercased HTML."""
    return any(p.lower() in html_lower for p in patterns)


def _detect_tech_stack(html_lower: str) -> list[str]:
    """Return a list of detected technologies based on HTML fingerprints."""
    detected: list[str] = []
    for tech, fingerprints in TECH_PATTERNS.items():
        if _detect_pattern(html_lower, fingerprints):
            detected.append(tech)
    return detected
