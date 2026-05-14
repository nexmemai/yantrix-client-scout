import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import leads as leads_api
from app.database import get_db
from app.main import app
from app.services.pitch_generator import BusinessNotFoundError

client = TestClient(app)


async def fake_get_db():
    yield SimpleNamespace()


def test_regenerate_pitch_route_returns_pitch(monkeypatch):
    lead_id = uuid.uuid4()
    pitch_id = uuid.uuid4()

    async def fake_generate_and_save_pitch(requested_id, _db):
        assert requested_id == lead_id
        return SimpleNamespace(
            id=pitch_id,
            business_id=lead_id,
            pitch_notes="Add WhatsApp and booking automation to capture more leads and reduce missed calls.",
            llm_provider="nvidia",
            llm_model="primary-model",
            tokens_used=22,
            generated_at=datetime.now(timezone.utc),
        )

    app.dependency_overrides[get_db] = fake_get_db
    monkeypatch.setattr(leads_api, "generate_and_save_pitch", fake_generate_and_save_pitch)

    response = client.post(f"/api/v1/leads/{lead_id}/pitch")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(pitch_id)
    assert data["business_id"] == str(lead_id)
    assert data["llm_provider"] == "nvidia"
    assert "missed calls" in data["pitch_notes"]


def test_regenerate_pitch_route_returns_404(monkeypatch):
    lead_id = uuid.uuid4()

    async def fake_generate_and_save_pitch(_requested_id, _db):
        raise BusinessNotFoundError("Business not found.")

    app.dependency_overrides[get_db] = fake_get_db
    monkeypatch.setattr(leads_api, "generate_and_save_pitch", fake_generate_and_save_pitch)

    response = client.post(f"/api/v1/leads/{lead_id}/pitch")

    app.dependency_overrides.clear()

    assert response.status_code == 404
