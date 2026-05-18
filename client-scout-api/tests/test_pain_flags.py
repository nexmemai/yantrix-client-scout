from types import SimpleNamespace

from app.services.pain_flags import build_pain_flags, detect_cms


def test_build_pain_flags_marks_missing_conversion_signals():
    audit = SimpleNamespace(
        has_website=True,
        has_booking=False,
        has_whatsapp=False,
        has_forms=True,
        ssl_valid=True,
        mobile_friendly=False,
        load_time_ms=4200,
        has_cta=False,
        has_chatbot=False,
        has_facebook=True,
        has_instagram=False,
    )

    flags = build_pain_flags(audit)

    assert flags["pain_no_website"] is False
    assert flags["pain_no_booking"] is True
    assert flags["pain_no_whatsapp"] is True
    assert flags["pain_no_form"] is False
    assert flags["pain_no_ssl"] is False
    assert flags["pain_not_mobile"] is True
    assert flags["pain_slow_load"] is True
    assert flags["pain_no_cta"] is True
    assert flags["pain_no_chatbot"] is True
    assert flags["pain_no_instagram"] is True


def test_detect_cms_prefers_known_cms_from_tech_stack():
    assert detect_cms(["Bootstrap", "WordPress", "React"]) == "WordPress"
    assert detect_cms(["React", "Bootstrap"]) is None
