"""
services/pain_translator.py - Translate boolean audit pain flags into
human-readable, business-impact sentences for the LLM prompt.

The pitch generator used to feed the LLM a literal flag dict like
``{"pain_no_form": true, "pain_slow_load": true}``. That produced robotic,
feature-heavy copy ("the website lacks a form"). Instead, we hand the LLM
*outcome statements* the SDR can paraphrase verbatim:

    "Visitors have no way to enquire from the homepage, so warm interest
    likely converts to phone calls competitors get instead."

This module is the single source of truth for that translation so prompt,
fallback rule-based copy, and test fixtures all stay aligned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

# ---------------------------------------------------------------------------
# Per-flag copy (plain language / impact / niche flavour)
#
# Each entry is intentionally a SENTENCE, not a label. The LLM is instructed
# to use these as inspiration, not literal text, but if it falls through to
# the rule-based fallback the copy still reads like a human wrote it.
# ---------------------------------------------------------------------------

PAIN_TRANSLATIONS: dict[str, dict[str, str]] = {
    "pain_no_website": {
        "headline": "no working website",
        "impact": (
            "Prospective customers cannot research or pre-qualify the business "
            "before calling, so most warm interest never reaches the inbox."
        ),
    },
    "pain_no_booking": {
        "headline": "no online booking path",
        "impact": (
            "Visitors who decide to book have to make a phone call during "
            "business hours, which loses high-intent leads who arrive after "
            "hours or prefer self-serve."
        ),
    },
    "pain_no_whatsapp": {
        "headline": "no WhatsApp follow-up",
        "impact": (
            "Mobile prospects expect a WhatsApp reply; without it, follow-up "
            "lag costs deals to whichever competitor responds first."
        ),
    },
    "pain_no_form": {
        "headline": "no enquiry form on the homepage",
        "impact": (
            "Warm visitors have no low-friction way to leave details, so the "
            "homepage is leaking interested traffic that never converts."
        ),
    },
    "pain_no_ssl": {
        "headline": "site is not served over HTTPS",
        "impact": (
            "Modern browsers flag the site as Not Secure, which silently kills "
            "trust at the worst possible moment - the form fill."
        ),
    },
    "pain_not_mobile": {
        "headline": "mobile experience is broken",
        "impact": (
            "More than half of local search traffic is on mobile; a broken "
            "mobile layout means most visitors bounce before they understand "
            "what is on offer."
        ),
    },
    "pain_slow_load": {
        "headline": "homepage takes more than 3s to load",
        "impact": (
            "Every additional second of load time loses roughly 10% of "
            "visitors. A slow homepage is an invisible advertising tax."
        ),
    },
    "pain_no_cta": {
        "headline": "no clear next-step button",
        "impact": (
            "Visitors do not know what to do next - call, book, or message - "
            "so attention dies before a decision is made."
        ),
    },
    "pain_no_chatbot": {
        "headline": "no automated first-response on the site",
        "impact": (
            "After-hours and weekend enquiries go unanswered until Monday, "
            "by which point the prospect has booked elsewhere."
        ),
    },
    "pain_no_facebook": {
        "headline": "no visible Facebook presence",
        "impact": (
            "Local trust signals are thin - prospects lose confidence when "
            "the business cannot be cross-checked on Facebook."
        ),
    },
    "pain_no_instagram": {
        "headline": "no visible Instagram presence",
        "impact": (
            "Visual proof - photos, reels, before/after - is missing, which "
            "matters for niches where buying decisions are visual."
        ),
    },
}


# Order in which we surface pain points to the LLM. The first three are the
# strongest "money is leaving" signals; we only fall back to softer ones if
# nothing severe is present.
PAIN_PRIORITY: tuple[str, ...] = (
    "pain_no_website",
    "pain_slow_load",
    "pain_no_form",
    "pain_no_booking",
    "pain_no_cta",
    "pain_not_mobile",
    "pain_no_whatsapp",
    "pain_no_chatbot",
    "pain_no_ssl",
    "pain_no_facebook",
    "pain_no_instagram",
)


@dataclass(frozen=True)
class TranslatedPain:
    """One pain flag rendered into human-readable bullets."""

    flag: str
    headline: str
    impact: str

    def as_sentence(self) -> str:
        """Single sentence the LLM (or fallback) can paraphrase."""
        return f"- {self.headline.capitalize()}. {self.impact}"


def translate_pain_flags(
    flags: Mapping[str, bool] | None,
    *,
    limit: int = 3,
) -> list[TranslatedPain]:
    """Pick the most impactful active pains and render them human-readable.

    The pitch prompt only forwards a small slice of the audit so the model
    can stay focused; `limit` defaults to 3 because longer pain stacks make
    cold outreach feel accusatory.
    """
    if not flags:
        return []
    out: list[TranslatedPain] = []
    for key in PAIN_PRIORITY:
        if not flags.get(key):
            continue
        copy = PAIN_TRANSLATIONS.get(key)
        if not copy:
            continue
        out.append(TranslatedPain(flag=key, headline=copy["headline"], impact=copy["impact"]))
        if len(out) >= limit:
            break
    return out


def render_pain_block(pains: Iterable[TranslatedPain]) -> str:
    """Format a list of pains as the prompt's `pain_points` text block.

    The output is a markdown-bullet block so the LLM can quote it back
    almost verbatim into an email body without further formatting work.
    """
    lines = [pain.as_sentence() for pain in pains]
    return "\n".join(lines) if lines else "- No critical conversion gaps detected; lead with a softer educational angle."


__all__ = [
    "PAIN_PRIORITY",
    "PAIN_TRANSLATIONS",
    "TranslatedPain",
    "render_pain_block",
    "translate_pain_flags",
]
