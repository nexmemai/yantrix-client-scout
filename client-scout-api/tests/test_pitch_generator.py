import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.audit import Audit
from app.models.business import Business
from app.models.config import NicheConfig
from app.models.pitch import Pitch
from app.models.score import Score
from app.services import pitch_generator
from app.services.pitch_generator import (
    PitchDraft,
    generate_and_save_pitch,
    generate_pitch,
)


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeAsyncSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.added = []
        self.commit_calls = 0
        self.refresh_calls = 0

    async def execute(self, _statement):
        if not self._responses:
            raise AssertionError("No fake DB response queued for execute()")
        return FakeResult(self._responses.pop(0))

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_calls += 1

    async def refresh(self, obj):
        self.refresh_calls += 1
        if isinstance(obj, Pitch):
            obj.generated_at = datetime.now(timezone.utc)


def make_business() -> Business:
    return Business(
        id=uuid.uuid4(),
        name="SmileCare Dental",
        category="Dental Clinic",
        niche="dental",
        city="Pune",
        website_url="https://smilecare.example",
        rating=Decimal("4.1"),
        review_count=12,
        source="google_maps",
    )


def make_audit(business_id: uuid.UUID) -> Audit:
    audit = Audit(
        id=uuid.uuid4(),
        business_id=business_id,
        status="completed",
        has_website=True,
        ssl_valid=True,
        mobile_friendly=False,
        has_forms=False,
        has_cta=True,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        has_title=True,
        has_meta_desc=False,
        has_h1=True,
        has_og_tags=False,
        has_facebook=False,
        has_instagram=False,
        has_linkedin=False,
        has_twitter=False,
        page_speed_score=42,
    )
    return audit


def make_score(business_id: uuid.UUID) -> Score:
    return Score(
        id=uuid.uuid4(),
        business_id=business_id,
        overall_score=72,
        llm_provider="rule_engine",
        llm_model="gap_weighted_v1",
    )


def make_config() -> NicheConfig:
    return NicheConfig(
        id=uuid.uuid4(),
        niche="dental",
        display_name="Dental",
        prompt_template="Mention missed appointments and patient inquiries.",
        is_default=False,
    )


def make_settings(**overrides):
    values = {
        "LLM_PROVIDER": "nvidia",
        "LLM_API_KEY": "primary-key",
        "LLM_MODEL_NAME": "primary-model",
        "LLM_MAX_RETRIES": 2,
        "LLM_TIMEOUT_SECONDS": 5.0,
        "NVIDIA_NIM_API_KEY": "legacy-nvidia",
        "NVIDIA_NIM_MODEL": "nvidia-legacy-model",
        "NVIDIA_NIM_BASE_URL": "https://integrate.api.nvidia.com/v1",
        "GROQ_API_KEY": "legacy-groq",
        "GROQ_MODEL": "groq-legacy-model",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_generate_pitch_uses_nvidia_first(monkeypatch):
    business = make_business()
    audit = make_audit(business.id)
    score = make_score(business.id)
    calls = []

    async def fake_nvidia(provider_config, _system_prompt, _user_prompt, _timeout):
        calls.append(provider_config.provider)
        return "Add WhatsApp and booking so SmileCare captures more patient inquiries.", 25

    async def fake_groq(*_args):
        calls.append("groq")
        return "fallback", 10

    monkeypatch.setattr(pitch_generator, "get_settings", lambda: make_settings())
    monkeypatch.setattr(pitch_generator, "_call_nvidia", fake_nvidia)
    monkeypatch.setattr(pitch_generator, "_call_groq", fake_groq)

    draft = await generate_pitch(business, audit, score, make_config())

    assert draft.pitch_notes == "Add WhatsApp and booking so SmileCare captures more patient inquiries."
    assert draft.llm_provider == "nvidia"
    assert draft.llm_model == "primary-model"
    assert calls == ["nvidia"]


@pytest.mark.asyncio
async def test_generate_pitch_falls_back_to_groq_after_rate_limit(monkeypatch):
    business = make_business()
    audit = make_audit(business.id)
    score = make_score(business.id)
    calls = []

    class RateLimitError(Exception):
        status_code = 429

    async def fake_nvidia(provider_config, _system_prompt, _user_prompt, _timeout):
        calls.append(provider_config.provider)
        raise RateLimitError("rate limited")

    async def fake_groq(provider_config, _system_prompt, _user_prompt, _timeout):
        calls.append(provider_config.provider)
        return "Reduce missed calls with WhatsApp capture and automated booking follow-up.", 17

    monkeypatch.setattr(pitch_generator, "get_settings", lambda: make_settings(LLM_MAX_RETRIES=1))
    monkeypatch.setattr(pitch_generator, "_call_nvidia", fake_nvidia)
    monkeypatch.setattr(pitch_generator, "_call_groq", fake_groq)

    draft = await generate_pitch(business, audit, score, None)

    assert draft.llm_provider == "groq"
    assert draft.llm_model == "groq-legacy-model"
    assert "missed calls" in draft.pitch_notes
    assert calls == ["nvidia", "groq"]


@pytest.mark.asyncio
async def test_generate_and_save_pitch_persists_pitch(monkeypatch):
    business = make_business()
    audit = make_audit(business.id)
    score = make_score(business.id)
    config = make_config()
    session = FakeAsyncSession([business, audit, score, config])

    async def fake_generate_pitch(_business, _audit, _score, _niche_config):
        return PitchDraft(
            pitch_notes="Capture more leads with faster follow-up and booking automation.",
            llm_provider="nvidia",
            llm_model="primary-model",
            tokens_used=31,
        )

    monkeypatch.setattr(pitch_generator, "generate_pitch", fake_generate_pitch)

    pitch = await generate_and_save_pitch(business.id, session)

    assert pitch.business_id == business.id
    assert pitch.score_id == score.id
    assert pitch.pitch_notes == "Capture more leads with faster follow-up and booking automation."
    assert pitch.llm_provider == "nvidia"
    assert pitch.llm_model == "primary-model"
    assert pitch.tokens_used == 31
    assert session.added == [pitch]
    assert session.commit_calls == 1
    assert session.refresh_calls == 1
