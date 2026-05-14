import uuid
from decimal import Decimal

import pytest

from app.models.audit import Audit
from app.models.business import Business
from app.models.config import NicheConfig
from app.models.score import Score
from app.services.scoring import (
    AUTOMATION_GAP,
    DEFAULT_GAP_WEIGHTS,
    HIGH_FIT_BUCKET,
    HIGH_TICKET,
    LEAD_CAPTURE_GAP,
    LOW_FIT_BUCKET,
    MID_FIT_BUCKET,
    OUTDATED_CONTACT,
    TRUST_GAP,
    WEAK_WEBSITE,
    bucket_for_score,
    compute_gap_breakdown,
    score_business,
    weights_from_config,
)


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeAsyncSession:
    def __init__(self, responses: list[object | None]):
        self._responses = list(responses)
        self.added: list[object] = []
        self.flush_calls = 0
        self.refresh_calls = 0
        self.commit_calls = 0

    async def execute(self, _statement):
        if not self._responses:
            raise AssertionError("No fake DB response queued for execute()")
        return FakeResult(self._responses.pop(0))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flush_calls += 1

    async def refresh(self, obj):
        self.refresh_calls += 1
        if isinstance(obj, Score):
            if obj.overall_score >= 75:
                obj.score_band = "A"
            elif obj.overall_score >= 50:
                obj.score_band = "B"
            elif obj.overall_score >= 25:
                obj.score_band = "C"
            else:
                obj.score_band = "D"

    async def commit(self):
        self.commit_calls += 1


def make_business(
    *,
    niche: str = "dental",
    category: str = "Dental Clinic",
    rating: Decimal | None = Decimal("3.8"),
    review_count: int | None = 5,
    phone: str | None = None,
    email: str | None = None,
) -> Business:
    return Business(
        id=uuid.uuid4(),
        name="Acme Business",
        niche=niche,
        category=category,
        city="Pune",
        phone=phone,
        email=email,
        rating=rating,
        review_count=review_count,
        source="google_maps",
        stage="new",
    )


def make_audit(
    business_id: uuid.UUID,
    *,
    status: str = "completed",
    has_website: bool = True,
    ssl_valid: bool = True,
    mobile_friendly: bool = True,
    has_forms: bool = True,
    has_cta: bool = True,
    has_whatsapp: bool = True,
    has_booking: bool = True,
    has_chatbot: bool = False,
    has_title: bool = True,
    has_meta_desc: bool = True,
    has_h1: bool = True,
    has_og_tags: bool = True,
    has_facebook: bool = False,
    has_instagram: bool = False,
    has_linkedin: bool = False,
    has_twitter: bool = False,
    page_speed_score: int | None = 90,
    load_time_ms: int | None = 1200,
    has_tel_links: bool = False,
) -> Audit:
    audit = Audit(
        id=uuid.uuid4(),
        business_id=business_id,
        status=status,
        has_website=has_website,
        ssl_valid=ssl_valid,
        mobile_friendly=mobile_friendly,
        has_forms=has_forms,
        has_cta=has_cta,
        has_whatsapp=has_whatsapp,
        has_booking=has_booking,
        has_chatbot=has_chatbot,
        has_title=has_title,
        has_meta_desc=has_meta_desc,
        has_h1=has_h1,
        has_og_tags=has_og_tags,
        has_facebook=has_facebook,
        has_instagram=has_instagram,
        has_linkedin=has_linkedin,
        has_twitter=has_twitter,
        page_speed_score=page_speed_score,
        load_time_ms=load_time_ms,
    )
    audit.has_tel_links = has_tel_links
    return audit


def make_config(*, niche: str, is_default: bool = False) -> NicheConfig:
    return NicheConfig(
        id=uuid.uuid4(),
        niche=niche,
        display_name=niche.title(),
        is_default=is_default,
    )


def test_weights_from_config_overrides_gap_weights_per_key():
    config = make_config(niche="dental")
    config.weights = {
        WEAK_WEBSITE: 5,
        LEAD_CAPTURE_GAP: 30,
        "unknown": 100,
        TRUST_GAP: -1,
    }

    weights = weights_from_config(config)

    assert weights[WEAK_WEBSITE] == 5
    assert weights[LEAD_CAPTURE_GAP] == 30
    assert weights[TRUST_GAP] == DEFAULT_GAP_WEIGHTS[TRUST_GAP]
    assert "unknown" not in weights


def test_bucket_for_score_boundaries():
    assert bucket_for_score(39) == LOW_FIT_BUCKET
    assert bucket_for_score(40) == MID_FIT_BUCKET
    assert bucket_for_score(59) == MID_FIT_BUCKET
    assert bucket_for_score(60) == HIGH_FIT_BUCKET


def test_compute_gap_breakdown_with_all_gaps_present():
    business = make_business()
    audit = make_audit(
        business.id,
        has_website=False,
        ssl_valid=False,
        mobile_friendly=False,
        has_forms=False,
        has_cta=False,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        has_title=False,
        has_meta_desc=False,
        has_h1=False,
        has_og_tags=False,
        has_facebook=False,
        has_instagram=False,
        has_linkedin=False,
        has_twitter=False,
        page_speed_score=20,
        load_time_ms=9000,
        has_tel_links=False,
    )

    breakdown = compute_gap_breakdown(business, audit)

    assert breakdown == {
        WEAK_WEBSITE: DEFAULT_GAP_WEIGHTS[WEAK_WEBSITE],
        LEAD_CAPTURE_GAP: DEFAULT_GAP_WEIGHTS[LEAD_CAPTURE_GAP],
        OUTDATED_CONTACT: DEFAULT_GAP_WEIGHTS[OUTDATED_CONTACT],
        HIGH_TICKET: DEFAULT_GAP_WEIGHTS[HIGH_TICKET],
        TRUST_GAP: DEFAULT_GAP_WEIGHTS[TRUST_GAP],
        AUTOMATION_GAP: DEFAULT_GAP_WEIGHTS[AUTOMATION_GAP],
    }
    assert sum(breakdown.values()) == 100
    assert bucket_for_score(sum(breakdown.values())) == HIGH_FIT_BUCKET


@pytest.mark.asyncio
async def test_score_business_persists_grouped_scores_and_marks_qualified():
    business = make_business()
    audit = make_audit(
        business.id,
        has_website=False,
        ssl_valid=False,
        mobile_friendly=False,
        has_forms=False,
        has_cta=False,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        has_title=False,
        has_meta_desc=False,
        has_h1=False,
        has_og_tags=False,
        page_speed_score=20,
        load_time_ms=9000,
        has_tel_links=False,
    )
    niche_config = make_config(niche="dental")
    session = FakeAsyncSession([business, audit, niche_config, None])

    outcome = await score_business(business.id, session)

    assert outcome is not None
    assert outcome.total_score == 100
    assert outcome.fit_bucket == HIGH_FIT_BUCKET
    assert outcome.breakdown[WEAK_WEBSITE] == 20
    assert outcome.breakdown[LEAD_CAPTURE_GAP] == 25
    assert outcome.breakdown[AUTOMATION_GAP] == 15
    assert outcome.score.overall_score == 100
    assert outcome.score.website_quality == 20
    assert outcome.score.conversion_readiness == 40
    assert outcome.score.online_presence == 20
    assert outcome.score.urgency == 20
    assert outcome.score.niche_config_id == niche_config.id
    assert outcome.score.llm_model == "gap_weighted_v1"
    assert business.stage == "qualified"
    assert session.flush_calls == 1
    assert session.refresh_calls == 1
    assert session.commit_calls == 1
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_score_business_falls_back_to_default_config():
    business = make_business(
        niche="salon",
        category="Beauty Salon",
        rating=Decimal("4.8"),
        review_count=80,
        phone="9999999999",
    )
    audit = make_audit(
        business.id,
        has_forms=False,
        has_cta=True,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        has_facebook=True,
        has_instagram=True,
        has_tel_links=True,
    )
    default_config = make_config(niche="_default", is_default=True)
    session = FakeAsyncSession([business, audit, None, default_config, None])

    outcome = await score_business(business.id, session)

    assert outcome is not None
    assert outcome.total_score == DEFAULT_GAP_WEIGHTS[AUTOMATION_GAP]
    assert outcome.fit_bucket == LOW_FIT_BUCKET
    assert outcome.breakdown == {
        WEAK_WEBSITE: 0,
        LEAD_CAPTURE_GAP: 0,
        OUTDATED_CONTACT: 0,
        HIGH_TICKET: 0,
        TRUST_GAP: 0,
        AUTOMATION_GAP: DEFAULT_GAP_WEIGHTS[AUTOMATION_GAP],
    }
    assert outcome.score.niche_config_id == default_config.id
    assert business.stage == "new"


@pytest.mark.asyncio
async def test_score_business_returns_none_without_completed_audit():
    business = make_business()
    audit = make_audit(business.id, status="failed")
    session = FakeAsyncSession([business, audit])

    outcome = await score_business(business.id, session)

    assert outcome is None
    assert session.flush_calls == 0
    assert session.refresh_calls == 0
    assert session.commit_calls == 0
    assert session.added == []
