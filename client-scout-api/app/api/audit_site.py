"""
api/audit_site.py — POST /audit-site

Triggers an on-demand website audit for a single URL.
Currently returns a stub response; Playwright integration arrives in Phase 3.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, status

from app.schemas.audit import AuditRead, AuditRequest

router = APIRouter(prefix="/audit-site", tags=["Audit"])


@router.post(
    "",
    response_model=AuditRead,
    status_code=status.HTTP_200_OK,
    summary="Audit a single website URL",
    description=(
        "Runs a full website audit on the provided URL. "
        "Checks for: mobile-friendliness, SSL, forms, CTA buttons, "
        "WhatsApp links, booking widgets, SEO basics, and tech stack. "
        "Playwright integration wired in Phase 3."
    ),
)
async def audit_site(payload: AuditRequest) -> AuditRead:
    # TODO (Phase 3): Run Playwright audit pipeline
    stub_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    return AuditRead(
        id=stub_id,
        business_id=payload.business_id or uuid.uuid4(),
        url_checked=payload.url,
        # Stub signals — will be real Playwright results in Phase 3
        has_website=True,
        ssl_valid=payload.url.startswith("https"),
        mobile_friendly=False,
        has_forms=False,
        has_cta=False,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        load_time_ms=None,
        page_speed_score=None,
        has_title=False,
        has_meta_desc=False,
        has_h1=False,
        has_og_tags=False,
        has_facebook=False,
        has_instagram=False,
        has_linkedin=False,
        has_twitter=False,
        tech_stack=[],
        screenshot_url=None,
        status="completed",
        error_message="STUB — Playwright audit not yet wired (Phase 3)",
        audited_at=now,
    )
