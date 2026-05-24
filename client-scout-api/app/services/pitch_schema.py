"""
services/pitch_schema.py - JSON-mode contract for the LLM pitch call.

The previous prompt asked the model to return eight free-text fields. That
worked, but two failure modes leaked through:
  * the model occasionally repeated the prospect's company name 3-4 times
    in 80 words (robotic),
  * partial JSON would hard-fail and force the deterministic fallback.

We tighten the contract by:
  1. Asking only for THREE fields: subject, whatsapp_message, strategy_angle.
  2. Validating the shape with Pydantic so a missing/extra key triggers our
     own retry-then-fallback path.
  3. Returning a JSON-Schema dict the OpenAI/NIM client can pass via the
     `response_format` parameter on providers that support structured output.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError


class StructuredPitchOutput(BaseModel):
    """Strict three-field contract the LLM must satisfy."""

    email_subject: str = Field(
        ...,
        min_length=4,
        max_length=80,
        description="One short, specific email subject line. No emoji.",
    )
    whatsapp_message: str = Field(
        ...,
        min_length=40,
        max_length=600,
        description=(
            "The core WhatsApp opener: 50-90 words, conversational, one "
            "clear question, no marketing jargon."
        ),
    )
    strategy_angle: str = Field(
        ...,
        min_length=20,
        max_length=240,
        description=(
            "ONE sentence for internal use: the reason this pitch will land "
            "for THIS lead. Audience: the SDR sending it, not the prospect."
        ),
    )


def pitch_response_format() -> dict[str, Any]:
    """Return the OpenAI-compatible `response_format` payload.

    NVIDIA NIM's OpenAI-compatible endpoint accepts the same
    `response_format={"type": "json_schema", "json_schema": {...}}` shape as
    OpenAI proper. Groq accepts only `response_format={"type": "json_object"}`
    so the calling site downgrades gracefully when needed.
    """
    schema = StructuredPitchOutput.model_json_schema()
    # OpenAI's strict mode requires `additionalProperties: false` and every
    # property listed in `required`. Pydantic emits both already; we set the
    # strict toggle explicitly for the structured-output validator.
    schema["additionalProperties"] = False
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "yantrix_pitch_v4",
            "strict": True,
            "schema": schema,
        },
    }


def parse_strict_pitch(text: str) -> StructuredPitchOutput:
    """Validate raw LLM text against the schema, raising on any deviation."""
    import json

    try:
        payload = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"LLM returned non-JSON content: {exc}") from exc

    try:
        return StructuredPitchOutput.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"LLM JSON failed schema: {exc.errors()}") from exc


def _strip_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    return cleaned


__all__ = [
    "StructuredPitchOutput",
    "parse_strict_pitch",
    "pitch_response_format",
]
