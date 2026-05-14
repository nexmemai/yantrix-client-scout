"""
tests/test_health.py — Smoke tests for the health check and placeholder routes.
Run with: pytest tests/ -v
"""

import pytest
from fastapi.testclient import TestClient

from app.api import run_scout as run_scout_api
from app.database import get_db
from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "service" in data


def test_run_scout_returns_summary(monkeypatch):
    business_id = "11111111-1111-1111-1111-111111111111"

    class FakeSession:
        def add(self, _obj):
            return None

        async def commit(self):
            return None

        async def refresh(self, _obj):
            return None

    async def fake_get_db():
        yield FakeSession()

    async def fake_discover_businesses(*_args, **_kwargs):
        return [business_id]

    async def fake_process_businesses(*_args, **_kwargs):
        return [
            run_scout_api.BusinessPipelineResult(
                business_id=business_id,
                audited=True,
                scored=True,
                pitched=True,
                fit_bucket="high-fit",
                total_score=72,
            )
        ]

    app.dependency_overrides[get_db] = fake_get_db
    monkeypatch.setattr(run_scout_api, "discover_businesses", fake_discover_businesses)
    monkeypatch.setattr(run_scout_api, "_process_businesses", fake_process_businesses)

    response = client.post(
        "/api/v1/run-scout",
        json={"niche": "dental", "city": "Pune"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "job_id" in data
    assert data["discovered"] == 1
    assert data["audited"] == 1
    assert data["scored"] == 1
    assert data["pitched"] == 1
    assert data["high_fit_lead_ids"] == [business_id]


def test_audit_site_returns_200():
    response = client.post(
        "/api/v1/audit-site",
        json={"url": "https://example.com"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["has_website"] is True
    assert data["ssl_valid"] is True   # https URL → True in stub


def test_leads_list_returns_200():
    response = client.get("/api/v1/leads")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


def test_leads_filter_by_city():
    response = client.get("/api/v1/leads?city=Pune")
    assert response.status_code == 200
    data = response.json()
    for item in data["items"]:
        assert item["city"].lower() == "pune"


def test_leads_filter_min_score():
    response = client.get("/api/v1/leads?min_score=50")
    assert response.status_code == 200
    data = response.json()
    for item in data["items"]:
        assert (item.get("overall_score") or 0) >= 50


def test_configs_list_returns_defaults():
    response = client.get("/api/v1/configs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    niches = [c["niche"] for c in data]
    assert "default" in niches


def test_config_get_specific_niche():
    response = client.get("/api/v1/configs/healthcare")
    assert response.status_code == 200
    data = response.json()
    assert data["niche"] == "healthcare"
    assert "weights" in data


def test_config_get_missing_niche():
    response = client.get("/api/v1/configs/nonexistent_niche_xyz")
    assert response.status_code == 404


def test_config_upsert_new_niche():
    weights = {
        "has_website": 10, "mobile_friendly": 10, "has_forms": 10,
        "has_cta": 10, "has_whatsapp": 10, "has_booking": 10,
        "ssl_valid": 10, "page_speed": 10, "seo_basics": 10, "social_presence": 10,
    }
    response = client.put(
        "/api/v1/configs/real_estate",
        json={"weights": weights},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["niche"] == "real_estate"


def test_config_delete_niche():
    response = client.delete("/api/v1/configs/real_estate")
    assert response.status_code == 204


def test_config_delete_default_rejected():
    response = client.delete("/api/v1/configs/default")
    assert response.status_code == 400
