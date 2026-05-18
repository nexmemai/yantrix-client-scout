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
    class FakeSession:
        async def scalar(self, _stmt):
            return 0

        def add(self, _obj):
            return None

        async def commit(self):
            return None

        async def refresh(self, _obj):
            return None

    async def fake_get_db():
        yield FakeSession()

    async def fake_run_scout_job(*_args, **_kwargs):
        return None

    app.dependency_overrides[get_db] = fake_get_db
    monkeypatch.setattr(run_scout_api, "_run_scout_job", fake_run_scout_job)

    response = client.post(
        "/api/v1/run-scout",
        json={"niche": "dental", "city": "Pune"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "job_id" in data
    assert data["discovered"] == 0
    assert data["audited"] == 0
    assert data["scored"] == 0
    assert data["pitched"] == 0
    assert "started" in data["message"].lower()


def test_run_scout_rejects_oversized_request():
    response = client.post(
        "/api/v1/run-scout",
        json={"niche": "dental", "city": "Pune", "max_businesses": 101},
    )

    assert response.status_code == 400


def test_audit_site_returns_200():
    response = client.post(
        "/api/v1/audit-site",
        json={"url": "https://example.com"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["has_website"] is True
    assert data["ssl_valid"] is True
