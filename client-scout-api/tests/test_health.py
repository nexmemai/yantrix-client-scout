"""
tests/test_health.py - Smoke tests for health and lightweight routes.
Run with: pytest tests/ -v
"""

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
    assert data["ssl_valid"] is True
