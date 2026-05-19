from uuid import uuid4

from app.models.business import Business
from app.models.pitch import Pitch
from app.services.outreach_helpers import build_outreach_payload
from app.services.pitch_strategy import StructuredPitch, structured_pitch_metadata


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


def test_build_outreach_payload_uses_structured_pitch_metadata():
    business = Business(
        id=uuid4(),
        name="Example Dental",
        niche="dental",
        phone="+1 555 010 9999",
        source="google_maps",
    )
    structured = StructuredPitch(
        whatsapp_message="Hi Example Dental, booking and WhatsApp can reduce missed enquiries.",
        whatsapp_follow_up="Should I send the quick booking idea?",
        email_subject="Booking idea for Example Dental",
        email_body="Hi Example Dental,\n\nHere is a specific booking idea.",
        call_opener="I noticed patients may not have a fast booking path.",
        pain_points_used=["no online booking"],
        recommended_services=["Online booking funnel"],
        personalization_notes=["12 reviews with a 4.1 rating"],
    )
    pitch = Pitch(
        id=uuid4(),
        business_id=business.id,
        pitch_notes="Generic fallback",
        objection_handlers=structured_pitch_metadata(structured),
    )

    payload = build_outreach_payload(business, pitch)

    assert payload.email_subject == "Booking idea for Example Dental"
    assert payload.email_body == "Hi Example Dental,\n\nHere is a specific booking idea."
    assert payload.whatsapp_message.startswith("Hi Example Dental")
    assert payload.whatsapp_follow_up == "Should I send the quick booking idea?"
    assert payload.call_opener == "I noticed patients may not have a fast booking path."
    assert payload.pain_points_used == ["no online booking"]
    assert payload.recommended_services == ["Online booking funnel"]
    assert payload.personalization_notes == ["12 reviews with a 4.1 rating"]
    assert "Generic" not in payload.whatsapp_link
