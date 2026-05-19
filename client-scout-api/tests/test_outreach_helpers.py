from uuid import uuid4

from app.models.business import Business
from app.models.pitch import Pitch
from app.services.outreach_helpers import build_outreach_payload


def test_build_outreach_payload_uses_pitch_and_clean_whatsapp_phone():
    business = Business(
        id=uuid4(),
        name="Example Dental",
        niche="dental",
        phone="+1 (555) 010-2222",
        source="google_maps",
    )
    pitch = Pitch(
        id=uuid4(),
        business_id=business.id,
        pitch_notes="Hi Example Dental, quick booking idea.",
    )

    payload = build_outreach_payload(business, pitch)

    assert payload.email_subject == "Quick idea for Example Dental"
    assert payload.email_body == "Hi Example Dental, quick booking idea."
    assert payload.whatsapp_link is not None
    assert payload.whatsapp_link.startswith("https://wa.me/15550102222?text=")


def test_build_outreach_payload_omits_whatsapp_for_missing_phone():
    business = Business(id=uuid4(), name="Example Dental", niche="dental", source="google_maps")

    payload = build_outreach_payload(business, None)

    assert payload.whatsapp_link is None
    assert "Example Dental" in payload.email_body
