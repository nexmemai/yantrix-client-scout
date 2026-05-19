import json
from uuid import uuid4

from app.models.audit import Audit
from app.models.business import Business
from app.models.score import Score
from app.services.pitch_context import build_pitch_context
from app.services.pitch_strategy import (
    build_rule_based_pitch,
    parse_structured_pitch,
    structured_pitch_from_metadata,
    structured_pitch_metadata,
)


def _context():
    business = Business(
        id=uuid4(),
        name="Example Dental",
        niche="dental",
        city="Pune",
        rating=4.4,
        review_count=80,
        source="google_maps",
    )
    audit = Audit(
        id=uuid4(),
        business_id=business.id,
        status="completed",
        has_website=True,
        ssl_valid=True,
        mobile_friendly=True,
        has_forms=False,
        has_cta=True,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        has_facebook=True,
        has_instagram=True,
        pain_flags={"pain_no_booking": True, "pain_no_whatsapp": True},
    )
    score = Score(
        id=uuid4(),
        business_id=business.id,
        overall_score=78,
        agency_fit_bucket="hot",
        opportunity_types=["booking_system"],
    )
    return build_pitch_context(business, audit, score)


def test_rule_based_pitch_is_channel_specific_and_uses_real_signals():
    pitch = build_rule_based_pitch(_context())

    assert "Example Dental" in pitch.whatsapp_message
    assert "booking" in pitch.whatsapp_message.lower()
    assert "WhatsApp" in pitch.email_body
    assert pitch.email_subject == "Quick idea for Example Dental"
    assert "Online booking funnel" in pitch.recommended_services


def test_parse_structured_pitch_json_and_metadata_roundtrip():
    payload = {
        "whatsapp_message": "Hi Example Dental, booking could be faster.",
        "whatsapp_follow_up": "Should I send details?",
        "email_subject": "Better booking flow",
        "email_body": "Hi Example Dental,\n\nA better booking flow could help.",
        "call_opener": "I noticed a booking gap.",
        "pain_points_used": ["no online booking"],
        "recommended_services": ["Online booking funnel"],
        "personalization_notes": ["80 reviews with a 4.4 rating"],
    }

    pitch = parse_structured_pitch(json.dumps(payload), _context())
    reloaded = structured_pitch_from_metadata(structured_pitch_metadata(pitch))

    assert pitch.email_subject == "Better booking flow"
    assert reloaded is not None
    assert reloaded.whatsapp_follow_up == "Should I send details?"
    assert reloaded.pain_points_used == ["no online booking"]
