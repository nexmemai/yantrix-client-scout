from uuid import uuid4

from app.models.audit import Audit
from app.models.business import Business
from app.models.score import Score
from app.services.pitch_context import build_pitch_context


def test_build_pitch_context_uses_audit_pain_flags_and_opportunities():
    business = Business(
        id=uuid4(),
        name="Example Dental",
        niche="dental",
        city="Sioux Falls",
        rating=4.6,
        review_count=132,
        source="google_maps",
    )
    audit = Audit(
        id=uuid4(),
        business_id=business.id,
        status="completed",
        has_website=True,
        ssl_valid=True,
        mobile_friendly=False,
        has_forms=False,
        has_cta=False,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        has_facebook=True,
        has_instagram=False,
        pain_flags={
            "pain_no_booking": True,
            "pain_no_whatsapp": True,
            "pain_no_cta": True,
        },
        tech_stack=["WordPress"],
        cms_detected="WordPress",
    )
    score = Score(
        id=uuid4(),
        business_id=business.id,
        overall_score=84,
        agency_fit_score=91,
        agency_fit_bucket="hot",
        opportunity_types=["booking_system", "whatsapp_integration"],
        estimated_deal_value=90000,
    )

    context = build_pitch_context(business, audit, score)

    assert context.business_name == "Example Dental"
    assert context.agency_fit_bucket == "hot"
    assert [point.flag for point in context.pain_points] == [
        "pain_no_booking",
        "pain_no_whatsapp",
        "pain_no_cta",
    ]
    assert "Online booking funnel" in context.recommended_services
    assert "WhatsApp lead follow-up automation" in context.recommended_services
    assert any("132 reviews" in note for note in context.personalization_notes)
