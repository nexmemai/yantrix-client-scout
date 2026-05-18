from decimal import Decimal
from uuid import uuid4

from app.models.audit import Audit
from app.models.business import Business
from app.services.agency_fit import HOT_BUCKET, SKIP_BUCKET, calculate_agency_fit


def test_calculate_agency_fit_marks_hot_established_high_value_lead():
    business = Business(
        id=uuid4(),
        name="Example Dental",
        niche="dental",
        category="Dental Clinic",
        rating=Decimal("4.7"),
        review_count=180,
        source="google_maps",
    )
    audit = Audit(
        id=uuid4(),
        business_id=business.id,
        status="completed",
        has_website=True,
        ssl_valid=False,
        mobile_friendly=False,
        has_forms=False,
        has_cta=False,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        load_time_ms=4200,
        tech_stack=["WordPress"],
    )

    result = calculate_agency_fit(business, audit)

    assert result.agency_fit_score == 100
    assert result.agency_fit_bucket == HOT_BUCKET
    assert result.estimated_deal_value == 150000
    assert result.opportunity_types == [
        "booking_system",
        "whatsapp_integration",
        "chatbot",
        "lead_capture_form",
        "conversion_cta",
        "speed_optimization",
        "mobile_optimization",
        "ssl_fix",
        "website_rebuild",
    ]


def test_calculate_agency_fit_skips_low_pain_lead():
    business = Business(
        id=uuid4(),
        name="Example Cafe",
        niche="restaurant",
        category="Cafe",
        rating=Decimal("3.9"),
        review_count=12,
        source="google_maps",
    )
    audit = Audit(
        id=uuid4(),
        business_id=business.id,
        status="completed",
        has_website=True,
        ssl_valid=True,
        mobile_friendly=True,
        has_forms=True,
        has_cta=True,
        has_whatsapp=True,
        has_booking=True,
        has_chatbot=True,
        load_time_ms=900,
        tech_stack=["React"],
    )

    result = calculate_agency_fit(business, audit)

    assert result.agency_fit_score == 0
    assert result.agency_fit_bucket == SKIP_BUCKET
    assert result.estimated_deal_value == 0
    assert result.opportunity_types == []
