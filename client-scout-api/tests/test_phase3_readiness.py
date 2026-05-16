import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.configs import delete_config, get_config, list_configs, upsert_config
from app.api.export import export_leads
from app.api.jobs import get_job, list_jobs
from app.api.leads import get_lead, list_leads
from app.api.reports import get_report
from app.api.run_scout import _enforce_hourly_run_limit
from app.models.audit import Audit
from app.models.business import Business
from app.models.config import NicheConfig
from app.models.job import DiscoveryJob
from app.models.pitch import Pitch
from app.models.score import Score
from app.schemas.config import ScoringConfigUpdate, ScoringWeights
from app.schemas.export import ExportFilters, ExportRequest


NOW = datetime.now(timezone.utc)


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class FakeResult:
    def __init__(self, *, rows=None, scalar=None, scalars=None):
        self._rows = rows or []
        self._scalar = scalar
        self._scalars = scalars or []

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return FakeScalarResult(self._scalars)


class FakeSession:
    def __init__(self, *, scalars=None, results=None):
        self._scalars = list(scalars or [])
        self._results = list(results or [])
        self.added = []
        self.deleted = []
        self.commit_calls = 0

    async def scalar(self, _stmt):
        if not self._scalars:
            raise AssertionError("No scalar result queued")
        return self._scalars.pop(0)

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("No execute result queued")
        return self._results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commit_calls += 1

    async def refresh(self, _obj):
        return None


def make_business() -> Business:
    return Business(
        id=uuid.uuid4(),
        name="SmileCare Dental",
        category="dental",
        niche="dental",
        address="MG Road",
        city="Pune",
        state="Maharashtra",
        country="India",
        phone="+919999999999",
        email=None,
        website_url="https://smile.example",
        google_maps_url="https://maps.example",
        rating=Decimal("4.3"),
        review_count=88,
        source="google_maps",
        stage="qualified",
        created_at=NOW,
        updated_at=NOW,
    )


def make_audit(business_id: uuid.UUID) -> Audit:
    return Audit(
        id=uuid.uuid4(),
        business_id=business_id,
        url_checked="https://smile.example",
        has_website=True,
        ssl_valid=True,
        mobile_friendly=True,
        has_forms=False,
        has_cta=True,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        load_time_ms=1200,
        page_speed_score=80,
        has_title=True,
        has_meta_desc=True,
        has_h1=True,
        has_og_tags=False,
        has_facebook=False,
        has_instagram=True,
        has_linkedin=False,
        has_twitter=False,
        tech_stack=["WordPress"],
        screenshot_url=None,
        status="completed",
        error_message=None,
        audited_at=NOW,
    )


def make_score(business_id: uuid.UUID, audit_id: uuid.UUID) -> Score:
    score = Score(
        id=uuid.uuid4(),
        business_id=business_id,
        audit_id=audit_id,
        overall_score=72,
        website_quality=20,
        online_presence=10,
        conversion_readiness=40,
        urgency=20,
        llm_provider="rule_engine",
        llm_model="gap_weighted_v1",
        scored_at=NOW,
    )
    score.score_band = "B"
    return score


def make_pitch(business_id: uuid.UUID, score_id: uuid.UUID) -> Pitch:
    return Pitch(
        id=uuid.uuid4(),
        business_id=business_id,
        score_id=score_id,
        pitch_notes="Add WhatsApp and booking automation.",
        recommended_services=["WhatsApp Integration"],
        objection_handlers=None,
        subject_line="Capture more dental leads",
        tone="professional",
        language="en",
        llm_provider="nvidia",
        llm_model="test-model",
        prompt_version="v2.0",
        exported_to_hubspot=False,
        exported_to_zoho=False,
        generated_at=NOW,
        created_at=NOW,
    )


def make_config(niche: str = "_default", *, is_default: bool = True) -> NicheConfig:
    return NicheConfig(
        id=uuid.uuid4(),
        niche=niche,
        display_name=niche,
        weights={"weak_website": 10, "lead_capture_gap": 30},
        prompt_template=None,
        is_default=is_default,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_list_leads_uses_db_rows():
    business = make_business()
    session = FakeSession(
        scalars=[1],
        results=[FakeResult(rows=[(business, True, 72)])],
    )

    response = await list_leads(
        city=None,
        category=None,
        niche="dental",
        bucket="mid",
        created_after=NOW,
        source=None,
        search="Smile",
        min_score=None,
        sort="score_desc",
        page=1,
        limit=25,
        db=session,
    )

    assert response["total"] == 1
    assert response["items"][0].name == "SmileCare Dental"
    assert response["items"][0].overall_score == 72


@pytest.mark.asyncio
async def test_get_lead_returns_nested_audit_score_and_latest_pitch():
    business = make_business()
    audit = make_audit(business.id)
    score = make_score(business.id, audit.id)
    pitch = make_pitch(business.id, score.id)
    business.audit = audit
    business.score = score
    session = FakeSession(results=[FakeResult(scalar=business), FakeResult(scalar=pitch)])

    response = await get_lead(business.id, db=session)

    assert response["id"] == str(business.id)
    assert response["audit"]["has_website"] is True
    assert response["score"]["pitch_notes"] == "Add WhatsApp and booking automation."


@pytest.mark.asyncio
async def test_configs_are_db_backed_and_gap_weighted():
    config = make_config()
    session = FakeSession(results=[FakeResult(scalars=[config])])

    response = await list_configs(db=session)

    assert response[0].niche == "_default"
    assert response[0].weights["weak_website"] == 10
    assert response[0].weights["automation_gap"] == 15


@pytest.mark.asyncio
async def test_config_missing_raises_404():
    session = FakeSession(results=[FakeResult(scalar=None)])

    with pytest.raises(HTTPException) as exc:
        await get_config("missing", db=session)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_config_upsert_creates_new_row():
    session = FakeSession(results=[FakeResult(scalar=None)])
    payload = ScoringConfigUpdate(
        weights=ScoringWeights(
            weak_website=1,
            lead_capture_gap=2,
            outdated_contact=3,
            high_ticket=4,
            trust_gap=5,
            automation_gap=6,
        )
    )

    response = await upsert_config("lawyer", payload, db=session)

    assert response.niche == "lawyer"
    assert response.weights["automation_gap"] == 6
    assert session.added
    assert session.commit_calls == 1


@pytest.mark.asyncio
async def test_delete_default_config_rejected():
    session = FakeSession(results=[FakeResult(scalar=make_config())])

    with pytest.raises(HTTPException) as exc:
        await delete_config("_default", db=session)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_jobs_list_and_detail_use_real_schema():
    job = DiscoveryJob(
        id=uuid.uuid4(),
        query="dental clinics in Pune",
        city="Pune",
        source="google_maps",
        niche="dental",
        status="completed",
        total_discovered=10,
        total_audited=8,
        total_scored=7,
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
    )
    list_session = FakeSession(scalars=[1], results=[FakeResult(scalars=[job])])
    detail_session = FakeSession(results=[FakeResult(scalar=job)])

    listing = await list_jobs(
        status_filter=None,
        city=None,
        niche=None,
        page=1,
        limit=25,
        db=list_session,
    )
    detail = await get_job(job.id, db=detail_session)

    assert listing["items"][0].total_scored == 7
    assert detail.total_discovered == 10


@pytest.mark.asyncio
async def test_json_export_returns_dry_run_ready_items():
    business = make_business()
    audit = make_audit(business.id)
    score = make_score(business.id, audit.id)
    pitch = make_pitch(business.id, score.id)
    session = FakeSession(results=[FakeResult(rows=[(business, True, 72, "B", pitch)])])
    payload = ExportRequest(
        destination="hubspot",
        filters=ExportFilters(city="Pune", min_score=60, unexported_only=True),
    )

    response = await export_leads(payload, db=session)

    assert response.status == "dry_run"
    assert response.lead_count == 1
    assert response.items[0].pitch_notes == "Add WhatsApp and booking automation."


@pytest.mark.asyncio
async def test_format_json_export_returns_array():
    business = make_business()
    audit = make_audit(business.id)
    score = make_score(business.id, audit.id)
    pitch = make_pitch(business.id, score.id)
    session = FakeSession(results=[FakeResult(rows=[(business, True, 72, "B", pitch)])])
    payload = ExportRequest(format="json", niche="dental", city="Pune", bucket="high")

    response = await export_leads(payload, db=session)

    assert response.status_code == 200
    assert response.body


@pytest.mark.asyncio
async def test_hourly_run_limit_rejects_at_cap():
    session = FakeSession(scalars=[2])

    with pytest.raises(HTTPException) as exc:
        await _enforce_hourly_run_limit("dental", "Pune", NOW, 2, session)

    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_report_endpoint_renders_html():
    business = make_business()
    audit = make_audit(business.id)
    score = make_score(business.id, audit.id)
    pitch = make_pitch(business.id, score.id)
    business.audit = audit
    business.score = score
    session = FakeSession(results=[FakeResult(scalar=business), FakeResult(scalar=pitch)])

    response = await get_report(business.id, db=session)

    assert response.status_code == 200
    assert "Yantrix Client Scout report" in response.body.decode()
    assert "WhatsApp inquiry automation" in response.body.decode()
