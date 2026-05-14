"""
services/pitch_generator.py - LLM-backed pitch generation.

Generates short, business-outcome focused pitch notes and persists them in the
pitches table. NVIDIA NIM is the default provider, with Groq available as an
optional fallback through legacy provider-specific env vars.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import Audit
from app.models.business import Business
from app.models.config import NicheConfig
from app.models.pitch import Pitch
from app.models.score import Score
from app.services.scoring import bucket_for_score

logger = logging.getLogger(__name__)

ProviderName = Literal["nvidia", "groq"]

PROMPT_VERSION = "v2.0"
DEFAULT_TONE = "professional"
SYSTEM_PROMPT = (
    "You are a sales analyst for Yantrix Labs, an AI automation/website "
    "systems studio in Jaipur. Write a 2-3 line pitch to this business based "
    "on the audit findings, focusing on business outcomes: more leads, fewer "
    "missed calls, and better automation."
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
) -> PitchDraft:
    """Generate a short pitch from loaded ORM context."""
    settings = get_settings()
    user_prompt = _build_user_prompt(business, audit, score, niche_config)

    for provider_config in _provider_chain(settings):
        try:
            text, tokens = await _complete_with_retries(
                provider_config=provider_config,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_retries=max(1, settings.LLM_MAX_RETRIES),
                timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            )
            return PitchDraft(
                pitch_notes=_clean_pitch_text(text),
                llm_provider=provider_config.provider,
                llm_model=provider_config.model,
                tokens_used=tokens,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Pitch provider failed provider=%s model=%s error=%s",
                provider_config.provider,
                provider_config.model,
                exc,
            )

    raise PitchGenerationError("All configured LLM providers failed.")


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
    draft = await generate_pitch(business, audit, score, niche_config)

    pitch = Pitch(
        id=uuid.uuid4(),
        business_id=business_id,
        score_id=score.id,
        pitch_notes=draft.pitch_notes,
        subject_line=None,
        recommended_services=[],
        objection_handlers=None,
        tone=tone,
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
    response = await client.chat.completions.create(
        model=provider_config.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.35,
        max_tokens=180,
    )
    return _extract_completion(response)


async def _call_groq(
    provider_config: ProviderConfig,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: float,
) -> tuple[str, int | None]:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=provider_config.api_key, timeout=timeout_seconds)
    response = await client.chat.completions.create(
        model=provider_config.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.35,
        max_tokens=180,
    )
    return _extract_completion(response)


def _extract_completion(response: Any) -> tuple[str, int | None]:
    text = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if getattr(response, "usage", None) else None
    return text, tokens


def _build_user_prompt(
    business: Business,
    audit: Audit,
    score: Score,
    niche_config: NicheConfig | None,
) -> str:
    findings = _audit_findings(audit)
    niche_guidance = niche_config.prompt_template if niche_config else None
    fit_bucket = bucket_for_score(score.overall_score)

    lines = [
        f"Business: {business.name}",
        f"Category: {business.category or business.niche or 'local business'}",
        f"City: {business.city or 'unknown'}",
        f"Website: {business.website_url or 'not found'}",
        f"Rating: {float(business.rating or 0):.1f}",
        f"Review count: {business.review_count or 0}",
        f"Score: {score.overall_score}/100 ({fit_bucket})",
        f"Audit findings: {', '.join(findings) if findings else 'No major gaps detected.'}",
    ]
    if niche_guidance:
        lines.append(f"Niche guidance: {niche_guidance}")

    lines.append(
        "Write only the pitch text. Keep it to 2-3 short lines. Do not invent facts."
    )
    return "\n".join(lines)


def _audit_findings(audit: Audit) -> list[str]:
    findings: list[str] = []
    if not audit.has_website:
        findings.append("no public website found")
    if audit.has_website and not audit.ssl_valid:
        findings.append("website is not secure")
    if not audit.mobile_friendly:
        findings.append("website is not mobile friendly")
    if not audit.has_forms:
        findings.append("no inquiry form")
    if not audit.has_cta:
        findings.append("weak call to action")
    if not audit.has_whatsapp:
        findings.append("no WhatsApp lead capture")
    if not audit.has_booking:
        findings.append("no online booking")
    if not audit.has_chatbot:
        findings.append("no automated chat")
    if not (audit.has_facebook or audit.has_instagram or audit.has_linkedin or audit.has_twitter):
        findings.append("limited social trust signals")
    if audit.page_speed_score is not None and audit.page_speed_score < 50:
        findings.append("slow page speed")
    elif audit.load_time_ms and audit.load_time_ms > 5000:
        findings.append("slow website load time")
    return findings


def _clean_pitch_text(text: str) -> str:
    text = text.strip().strip('"').strip("'")
    text = text.replace("```", "").strip()
    lines = [line.strip(" -") for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:3]) if lines else text


def _is_retryable_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 409, 429, 500, 502, 503, 504}:
        return True
    name = exc.__class__.__name__.lower()
    return any(token in name for token in ("rate", "timeout", "connection", "server"))
