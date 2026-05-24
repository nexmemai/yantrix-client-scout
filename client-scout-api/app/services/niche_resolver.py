"""
services/niche_resolver.py - Free-text niche resolution for the scout pipeline.

The /run-scout endpoint used to enforce a hardcoded VALID_NICHES allow-list,
which meant adding a new industry (e.g. "EV charging stations") required a
code change and redeploy. This resolver replaces that allow-list with a
three-stage fallback:

  1. Database lookup against niche_configs.niche / niche_configs.aliases
     (after canonical-key normalisation). Honours is_enabled.
  2. Built-in catalog of legacy phrases so the original 15 niches keep
     producing the exact same gosom queries they always did.
  3. Generic pluralisation as a final safety net so a brand-new niche the
     team hasn't catalogued yet still reaches Google Maps.

Returned `ResolvedNiche` carries:
    - canonical key (`ev_charging`) for analytics + scoring config lookup,
    - display name (free-text from the user) for logs and the dashboard,
    - search_phrase ("EV charging stations") for the gosom payload,
    - the matched NicheConfig if any, so downstream callers can fetch
      weights/prompt template without an extra round-trip.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import NicheConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Built-in catalog
# ---------------------------------------------------------------------------
#
# Source of truth for the legacy 15 niches. The resolver consults this
# AFTER the DB so an operator can override "dental" -> "dentists in india"
# via niche_configs without redeploying. Keep this dict in sync if a new
# niche graduates from "free-text" to "first-class" status.

BUILT_IN_NICHE_PHRASES: dict[str, str] = {
    "dental": "dental clinics",
    "salon": "beauty salons",
    "real_estate": "real estate agents",
    "clinic": "medical clinics",
    "gym": "gyms and fitness centres",
    "restaurant": "restaurants",
    "hotel": "hotels",
    "ca": "chartered accountants",
    "lawyer": "law firms",
    "physiotherapy": "physiotherapy clinics",
    "optician": "opticians",
    "veterinary": "veterinary clinics",
    "pharmacy": "pharmacies",
    "spa": "day spas",
    "coaching": "coaching institutes",
}


# Canonical-key shape: lowercase letters, digits, underscore. Must start
# with a letter so we can tell a key apart from a row id at a glance in logs.
NICHE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
NICHE_KEY_MAX_LEN = 40


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedNiche:
    """The scout pipeline's idea of a niche after free-text resolution."""

    key: str
    display: str
    search_phrase: str
    source: str  # "db" | "built_in" | "generic"
    config: NicheConfig | None = None
    # Per-niche pitch tone resolved from the DB row (when present). None
    # means "fall through to whatever tone the caller passed, or the system
    # default in pitch_generator.DEFAULT_TONE". Kept on ResolvedNiche so
    # callers don't have to peek at config.pitch_tone themselves.
    tone: str | None = None


class InvalidNicheError(ValueError):
    """Raised when the user input cannot be coerced to a valid niche key."""


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def normalize_niche_key(raw: str) -> str:
    """Coerce free-text niche input to a stable canonical key.

    Examples:
        "EV charging stations"   -> "ev_charging_stations"
        "Dental Clinics"         -> "dental_clinics"
        "  real-estate "         -> "real_estate"
        "Coeur d'Alene Dentists" -> "coeur_d_alene_dentists"
        "Café"                   -> "cafe"

    Raises InvalidNicheError when nothing valid remains after stripping.
    """
    if not raw or not raw.strip():
        raise InvalidNicheError("Niche must not be empty.")

    # NFKD strip + ASCII fold so "Café" -> "Cafe", "São Paulo" works.
    cleaned = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    cleaned = cleaned.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    cleaned = cleaned[:NICHE_KEY_MAX_LEN]

    if not cleaned:
        raise InvalidNicheError(
            f"Niche '{raw}' contains no usable letters or digits."
        )
    if not NICHE_KEY_PATTERN.match(cleaned):
        raise InvalidNicheError(
            f"Niche '{raw}' could not be normalised to a valid key (got '{cleaned}')."
        )
    return cleaned


async def resolve_niche(raw: str, db: AsyncSession) -> ResolvedNiche:
    """Resolve any user-supplied niche string to a search phrase.

    Resolution order:
      1. niche_configs row matching key OR alias (where is_enabled=True)
      2. BUILT_IN_NICHE_PHRASES
      3. Generic pluralisation of the user's display string

    The returned ResolvedNiche is the contract `discover_businesses` and the
    scoring/pitch lookup share, so any caller can rely on `key` (for DB
    storage) and `search_phrase` (for the scraper) being non-empty.
    """
    display = raw.strip()
    key = normalize_niche_key(display)

    config = await _lookup_config(key, db)
    if config is not None:
        # search_phrase wins; fall back to display_name then the catalog.
        phrase = (
            (config.search_phrase or "").strip()
            or (config.display_name or "").strip()
            or BUILT_IN_NICHE_PHRASES.get(key)
            or _generic_phrase(display)
        )
        # Tone comes from the same row when set; the resolver intentionally
        # does NOT fall back to a hardcoded niche-tone map because the whole
        # point of the column is to make this DB-driven and editable.
        tone = (config.pitch_tone or None)
        if tone is not None:
            tone = tone.strip().lower() or None
        logger.debug(
            "[NICHE] resolved key=%s via=db phrase=%r tone=%s",
            key, phrase, tone,
        )
        return ResolvedNiche(
            key=key,
            display=display,
            search_phrase=phrase,
            source="db",
            config=config,
            tone=tone,
        )

    if key in BUILT_IN_NICHE_PHRASES:
        phrase = BUILT_IN_NICHE_PHRASES[key]
        logger.debug("[NICHE] resolved key=%s via=built_in phrase=%r", key, phrase)
        return ResolvedNiche(
            key=key,
            display=display,
            search_phrase=phrase,
            source="built_in",
            config=None,
            tone=None,
        )

    phrase = _generic_phrase(display)
    logger.info(
        "[NICHE] resolved key=%s via=generic phrase=%r (no DB row, no built-in)",
        key,
        phrase,
    )
    return ResolvedNiche(
        key=key,
        display=display,
        search_phrase=phrase,
        source="generic",
        config=None,
        tone=None,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _lookup_config(key: str, db: AsyncSession) -> NicheConfig | None:
    """Find a niche_configs row by canonical key OR alias.

    Both lookups are filtered on is_enabled so a soft-disabled row never wins.
    The alias check uses Postgres' `ANY()` against the TEXT[] column, which
    rides the GIN index added in 006_dynamic_niches.sql.
    """
    direct = await db.execute(
        select(NicheConfig).where(
            NicheConfig.niche == key,
            NicheConfig.is_enabled.is_(True),
        )
    )
    config = direct.scalar_one_or_none()
    if config is not None:
        return config

    # Aliases are stored as-typed; normalise both sides so case doesn't matter.
    alias = await db.execute(
        select(NicheConfig)
        .where(
            NicheConfig.is_enabled.is_(True),
            func.lower(func.array_to_string(NicheConfig.aliases, "|"))
            .like(f"%{key}%"),
        )
    )
    candidate = alias.scalar_one_or_none()
    if candidate is None:
        return None

    # Defensive: the LIKE above can substring-match (e.g. "spa" inside
    # "spanish"). Re-check with an exact alias compare in Python before
    # returning.
    aliases = [a.strip().lower() for a in (candidate.aliases or [])]
    if key in aliases:
        return candidate
    return None


def _generic_phrase(display: str) -> str:
    """Last-resort phrase when neither DB nor catalog matches.

    If the display string already contains spaces we trust it; gosom + Google
    Maps handle multi-word queries better than any auto-pluralisation. For a
    bare single word we add an "s" only when the input doesn't already end in
    one, to avoid producing "doctorss".
    """
    text = display.strip()
    if " " in text or "-" in text:
        return text
    bare = text.replace("_", " ").strip()
    if not bare:
        return text
    if bare.lower().endswith("s"):
        return bare
    return f"{bare}s"
