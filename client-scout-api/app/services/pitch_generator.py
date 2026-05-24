"""
services/pitch_generator.py - LLM-backed pitch generation.

Generates short, business-outcome focused pitch notes and persists them in the
pitches table. NVIDIA NIM is the default provider, with Groq available as an
optional fallback through legacy provider-specific env vars.

Phase 2 overhaul (May 2026):
  * System prompt rewritten around a problem -> consequence -> question
    framework instead of feature lists. The model is explicitly told NOT to
    repeat the prospect's company name and to keep WhatsApp <= 90 words.
  * Pain flags are translated into human-readable consequence sentences via
    `app.services.pain_translator` before they ever reach the model.
  * Output is constrained to a strict three-field JSON schema
    (`StructuredPitchOutput`) so the SDR-facing email subject, the WhatsApp
    body, and the internal "why this works" angle are always populated.
  * The caller's tone (`professional` / `friendly` / `urgent` / `consultative`)
    drives a tone block injected into the system prompt.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import Audit
from app.models.business import Business
from app.models.config import NicheConfig
from app.models.pitch import Pitch
from app.models.score import Score
from app.services.pain_translator import render_pain_block, translate_pain_flags
from app.services.pitch_context import build_pitch_context
from app.services.pitch_schema import (
    StructuredPitchOutput,
    parse_strict_pitch,
    pitch_response_format,
)
from app.services.pitch_strategy import (
    StructuredPitch,
    build_rule_based_pitch,
    build_structured_pitch_prompt,
    structured_pitch_metadata,
)

logger = logging.getLogger(__name__)

ProviderName = Literal["nvidia", "groq"]

PROMPT_VERSION = "v4.0"
DEFAULT_TONE = "professional"

# Allowed tone keys + a short style directive each. The directive is dropped
# verbatim into the system prompt so different tones produce visibly
# different copy without any branching at the call site.
TONE_DIRECTIVES: dict[str, str] = {
    "professional": (
        "Write like a respected senior B2B consultant emailing a peer. "
        "Calm, confident, zero hype, no exclamation marks."
    ),
    "friendly": (
        "Write like a helpful local agency owner introducing themselves. "
        "Warm, lightly informal, one short personal observation allowed."
    ),
    "urgent": (
        "Write like an SDR who has spotted a real, time-sensitive revenue "
        "leak. Direct, specific, never alarmist or salesy."
    ),
    "consultative": (
        "Write like a strategist diagnosing a problem before recommending "
        "anything. Lead with observations, ask one sharp diagnostic question."
    ),
}

# The system prompt is the single most important lever for output quality.
# We keep it terse and mechanical because:
#   * Llama-style models follow numbered rules better than narrative prose.
#   * Negative constraints ("never do X") only stick when listed explicitly.
#   * The structured-output JSON schema enforces the shape; the prompt
#     enforces the *substance*.
SYSTEM_PROMPT_BASE = (
    "You are a senior B2B sales strategist writing cold outbound copy on "
    "behalf of Yantrix Labs, an AI automation and website systems studio.\n"
    "\n"
    "FRAMEWORK (use this for every message):\n"
    "  1. Lead with ONE specific, concrete observation about the prospect's "
    "online presence. Use only the facts in `pain_points` and `context`.\n"
    "  2. Translate the observation into a business consequence in the "
    "prospect's own world: missed bookings, slow follow-up, lost mobile "
    "traffic, etc. Talk in revenue and customers, never in features.\n"
    "  3. Hint at how Yantrix can fix it in ONE clause - do not pitch a "
    "package, do not list services, do not mention pricing.\n"
    "  4. Close with ONE clear, low-pressure question that moves the "
    "conversation forward (a 10-minute call, a quick sketch, a comparison).\n"
    "\n"
    "HARD RULES:\n"
    "  - Mention the prospect's company name AT MOST ONCE across the whole "
    "WhatsApp message. Never use it in the email subject.\n"
    "  - WhatsApp message must be 50-90 words. Email subject must be under "
    "60 characters. Strategy angle must be exactly one sentence.\n"
    "  - No emoji, no marketing adjectives ('amazing', 'cutting-edge'), "
    "no buzzwords ('synergy', 'revolutionize'), no exclamation marks.\n"
    "  - Never invent traffic numbers, revenue figures, contact names, or "
    "rankings that are not in the provided context.\n"
    "  - Never mention scraping, audits, scores, or that you are an AI.\n"
    "\n"
    "OUTPUT: return strict JSON matching the provided schema with exactly "
    "these keys: email_subject, whatsapp_message, strategy_angle. The "
    "strategy_angle is for the SDR's eyes only - say in one sentence why "
    "this specific angle will land for this specific lead."
)


class PitchGenerationError(RuntimeError):
    """Raised when all configured LLM providers fail."""


class PitchContextMissingError(RuntimeError):
    """Raised when a lead cannot be pitched because required data is absent."""


class BusinessNotFoundError(RuntimeError):
    """Raised when the requested lead does not exist."""


@dataclass(frozen=True)
class PitchDraft:
    pitch_notes: str
    llm_provider: str
    llm_model: str
    tokens_used: int | None = None
    subject_line: str | None = None
    recommended_services: list[str] = field(default_factory=list)
    objection_handlers: str | None = None


@dataclass(frozen=True)
class ProviderConfig:
    provider: ProviderName
    api_key: str
    model: str


async def generate_pitch(
    business: Business,
    audit: Audit,
    score: Score,
    niche_config: NicheConfig | None = None,
    tone: str = DEFAULT_TONE,
) -> PitchDraft:
    """Generate structured channel-specific outreach from loaded ORM context.

    Tone selection drives a directive injected into the system prompt; the
    JSON output schema is the same for all tones so downstream rendering
    code never has to branch.
    """
    settings = get_settings()
    pitch_context = build_pitch_context(business, audit, score)

    # Translate raw audit pain flags into consequence sentences BEFORE the
    # LLM ever sees them. This is the single biggest contributor to
    # non-robotic copy: the model is asked to paraphrase, not invent.
    translated_pains = translate_pain_flags(audit.pain_flags, limit=3)
    pain_block = render_pain_block(translated_pains)

    user_prompt = build_structured_pitch_prompt(
        pitch_context,
        niche_config.prompt_template if niche_config else None,
    )
    # Append the human-readable pain block + tone hint AFTER the existing
    # JSON-formatted context so the model sees machine-friendly facts first
    # and human-friendly framing last (which is what it should imitate).
    augmented_user_prompt = (
        f"{user_prompt}\n\n"
        "PAIN POINTS, RANKED BY REVENUE IMPACT:\n"
        f"{pain_block}\n"
    )
    system_prompt = _system_prompt_for_tone(tone)

    for provider_config in _provider_chain(settings):
        try:
            text, tokens = await _complete_with_retries(
                provider_config=provider_config,
                system_prompt=system_prompt,
                user_prompt=augmented_user_prompt,
                max_retries=max(1, settings.LLM_MAX_RETRIES),
                timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            )
            try:
                strict = parse_strict_pitch(text)
            except ValueError as schema_exc:
                logger.warning(
                    "Pitch JSON schema mismatch provider=%s model=%s: %s",
                    provider_config.provider,
                    provider_config.model,
                    schema_exc,
                )
                # Strict-mode failure: try the next provider rather than
                # silently shipping a half-formed pitch.
                continue

            structured = _structured_pitch_from_strict(strict, pitch_context)
            return PitchDraft(
                pitch_notes=structured.email_body,
                llm_provider=provider_config.provider,
                llm_model=provider_config.model,
                tokens_used=tokens,
                subject_line=structured.email_subject,
                recommended_services=structured.recommended_services,
                objection_handlers=structured_pitch_metadata(structured),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Pitch provider failed provider=%s model=%s error=%s",
                provider_config.provider,
                provider_config.model,
                exc,
            )

    structured = build_rule_based_pitch(pitch_context)
    logger.warning("All configured LLM providers failed; using rule-based pitch fallback.")
    return PitchDraft(
        pitch_notes=structured.email_body,
        llm_provider="rule_engine",
        llm_model="structured_fallback_v4",
        subject_line=structured.email_subject,
        recommended_services=structured.recommended_services,
        objection_handlers=structured_pitch_metadata(structured),
    )


async def generate_and_save_pitch(
    business_id: uuid.UUID | str,
    db: AsyncSession,
    tone: str = DEFAULT_TONE,
    language: str = "en",
) -> Pitch:
    """
    Load lead context, generate a pitch, and persist a new Pitch row.

    The `tone` and `language` parameters are retained for pipeline
    compatibility; the prompt remains focused on concise business outcomes.
    """
    if isinstance(business_id, str):
        business_id = uuid.UUID(business_id)

    business = await _load_one(Business, Business.id == business_id, db)
    if business is None:
        raise BusinessNotFoundError(f"Business {business_id} not found.")

    audit = await _load_one(Audit, Audit.business_id == business_id, db)
    if audit is None or audit.status != "completed":
        raise PitchContextMissingError("A completed audit is required before generating a pitch.")

    score = await _load_one(Score, Score.business_id == business_id, db)
    if score is None:
        raise PitchContextMissingError("A score is required before generating a pitch.")

    niche_config = await _load_niche_config(business.niche, db)
    # When the caller asks for "auto" (the default), fall through to the
    # niche's configured tone if there is one. This way the LeadDetailPage
    # "Regenerate pitch" button and the single-pitch ARQ task both get the
    # right voice without needing to pass tone explicitly.
    effective_tone = tone
    if effective_tone == "auto" and niche_config is not None:
        configured = (niche_config.pitch_tone or "").strip().lower()
        if configured:
            effective_tone = configured

    draft = await generate_pitch(business, audit, score, niche_config, tone=effective_tone)

    pitch = Pitch(
        id=uuid.uuid4(),
        business_id=business_id,
        score_id=score.id,
        pitch_notes=draft.pitch_notes,
        subject_line=draft.subject_line,
        recommended_services=draft.recommended_services,
        objection_handlers=draft.objection_handlers,
        tone=effective_tone if effective_tone != "auto" else DEFAULT_TONE,
        language=language,
        llm_provider=draft.llm_provider,
        llm_model=draft.llm_model,
        tokens_used=draft.tokens_used,
        prompt_version=PROMPT_VERSION,
    )
    db.add(pitch)
    await db.commit()
    await db.refresh(pitch)

    logger.info(
        "Generated pitch business=%s provider=%s model=%s",
        business_id,
        draft.llm_provider,
        draft.llm_model,
    )
    return pitch


async def _load_one(model: type[Any], where_clause: Any, db: AsyncSession) -> Any | None:
    result = await db.execute(select(model).where(where_clause))
    return result.scalar_one_or_none()


async def _load_niche_config(niche: str | None, db: AsyncSession) -> NicheConfig | None:
    if niche:
        result = await db.execute(select(NicheConfig).where(NicheConfig.niche == niche))
        config = result.scalar_one_or_none()
        if config is not None:
            return config

    result = await db.execute(select(NicheConfig).where(NicheConfig.is_default.is_(True)))
    return result.scalar_one_or_none()


def _provider_chain(settings: Any) -> list[ProviderConfig]:
    provider = str(settings.LLM_PROVIDER or "nvidia").lower().strip()
    if provider not in {"nvidia", "groq"}:
        provider = "nvidia"

    primary = _provider_config(provider, settings, primary=True)
    fallback_provider = "groq" if provider == "nvidia" else "nvidia"
    fallback = _provider_config(fallback_provider, settings, primary=False)

    chain = []
    if primary:
        chain.append(primary)
    if fallback:
        chain.append(fallback)
    return chain


def _provider_config(
    provider: str,
    settings: Any,
    *,
    primary: bool,
) -> ProviderConfig | None:
    if provider == "nvidia":
        api_key = settings.LLM_API_KEY if primary else settings.NVIDIA_NIM_API_KEY
        model = (
            settings.LLM_MODEL_NAME
            if primary and settings.LLM_MODEL_NAME
            else settings.NVIDIA_NIM_MODEL
        )
        return ProviderConfig("nvidia", api_key, model) if api_key else None

    api_key = settings.LLM_API_KEY if primary else settings.GROQ_API_KEY
    model = settings.LLM_MODEL_NAME if primary and settings.LLM_MODEL_NAME else settings.GROQ_MODEL
    return ProviderConfig("groq", api_key, model) if api_key else None


async def _complete_with_retries(
    provider_config: ProviderConfig,
    system_prompt: str,
    user_prompt: str,
    max_retries: int,
    timeout_seconds: float,
) -> tuple[str, int | None]:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await _complete_once(
                provider_config,
                system_prompt,
                user_prompt,
                timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == max_retries - 1 or not _is_retryable_error(exc):
                raise
            await asyncio.sleep(min(2.0, 0.4 * (2**attempt)))

    raise PitchGenerationError(str(last_error) if last_error else "LLM call failed.")


async def _complete_once(
    provider_config: ProviderConfig,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: float,
) -> tuple[str, int | None]:
    if provider_config.provider == "nvidia":
        return await _call_nvidia(provider_config, system_prompt, user_prompt, timeout_seconds)
    return await _call_groq(provider_config, system_prompt, user_prompt, timeout_seconds)


async def _call_nvidia(
    provider_config: ProviderConfig,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: float,
) -> tuple[str, int | None]:
    settings = get_settings()
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=provider_config.api_key,
        base_url=settings.NVIDIA_NIM_BASE_URL,
        timeout=timeout_seconds,
    )

    # Try the structured json_schema response_format first; if the deployed
    # NIM model rejects it (older builds), fall back to plain json_object,
    # then to no constraint. parse_strict_pitch validates either way.
    create_kwargs: dict[str, Any] = {
        "model": provider_config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.35,
        "max_tokens": 700,
    }
    for response_format in (pitch_response_format(), {"type": "json_object"}, None):
        kwargs = dict(create_kwargs)
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            response = await client.chat.completions.create(**kwargs)
            return _extract_completion(response)
        except Exception as exc:  # noqa: BLE001
            # Only swallow shape errors here; auth / rate limit must surface.
            name = exc.__class__.__name__.lower()
            if any(token in name for token in ("badrequest", "validation", "format")):
                logger.info(
                    "NVIDIA NIM rejected response_format=%s; trying next variant",
                    response_format,
                )
                continue
            raise
    raise RuntimeError("NVIDIA NIM rejected every supported response_format variant.")


async def _call_groq(
    provider_config: ProviderConfig,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: float,
) -> tuple[str, int | None]:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=provider_config.api_key, timeout=timeout_seconds)
    # Groq supports json_object only (no json_schema yet, May 2026). The
    # schema is still enforced on our side via parse_strict_pitch.
    response = await client.chat.completions.create(
        model=provider_config.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.35,
        max_tokens=700,
        response_format={"type": "json_object"},
    )
    return _extract_completion(response)


def _extract_completion(response: Any) -> tuple[str, int | None]:
    text = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if getattr(response, "usage", None) else None
    return text, tokens


def _is_retryable_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 409, 429, 500, 502, 503, 504}:
        return True
    name = exc.__class__.__name__.lower()
    return any(token in name for token in ("rate", "timeout", "connection", "server"))


def _system_prompt_for_tone(tone: str) -> str:
    """Compose the system prompt for the requested tone.

    `auto` keeps the default professional directive but signals to operators
    in logs that the caller didn't pick a tone. Anything outside the known
    set falls back to professional with a debug log.
    """
    key = tone.lower().strip() or DEFAULT_TONE
    if key == "auto":
        key = DEFAULT_TONE
    directive = TONE_DIRECTIVES.get(key)
    if directive is None:
        logger.debug("Unknown pitch tone %r; defaulting to professional", tone)
        directive = TONE_DIRECTIVES[DEFAULT_TONE]
    return f"{SYSTEM_PROMPT_BASE}\n\nTONE:\n  {directive}"


def _structured_pitch_from_strict(
    strict: StructuredPitchOutput,
    pitch_context: Any,
) -> StructuredPitch:
    """Bridge the new strict 3-field schema to the existing 8-field DB shape.

    The wider DB shape (`StructuredPitch`) still drives outreach rendering
    elsewhere in the app; rather than redesign every consumer, we hydrate the
    extra fields from the deterministic rule-based pitch (built from the same
    pitch_context) and overwrite the LLM-authored slots. This keeps the
    contract stable while letting the model focus on what humans actually
    read.
    """
    fallback = build_rule_based_pitch(pitch_context)

    whatsapp = strict.whatsapp_message.strip()
    subject = strict.email_subject.strip()
    # Use the LLM's WhatsApp message as the email body too: the message is
    # already the right length and tone, and the prospect is more likely to
    # read 80 words than 200 in a cold email.
    email_body = whatsapp

    return StructuredPitch(
        whatsapp_message=whatsapp,
        whatsapp_follow_up=fallback.whatsapp_follow_up,
        email_subject=subject,
        email_body=email_body,
        call_opener=fallback.call_opener,
        pain_points_used=fallback.pain_points_used,
        recommended_services=fallback.recommended_services,
        # Stash the SDR-only strategy angle in personalization_notes so the
        # dashboard's "why this works" chip can render it without us widening
        # the persisted model. First entry is the new field; existing notes
        # follow.
        personalization_notes=[strict.strategy_angle.strip(), *fallback.personalization_notes],
    )
