"""
api/leads.py — GET /leads, GET /leads/{id}

Returns paginated business leads with nested audit + score data.
Currently returns realistic stub data; DB integration arrives in Phase 2.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.business import BusinessListItem, BusinessRead
from app.schemas.audit import AuditRead
from app.schemas.score import ScoreRead
from app.services.pitch_generator import (
    BusinessNotFoundError,
    PitchContextMissingError,
    PitchGenerationError,
    generate_and_save_pitch,
)

router = APIRouter(prefix="/leads", tags=["Leads"])

# ── Stub data ──────────────────────────────────────────────────────────────────

_NOW = datetime.now(timezone.utc)

_STUB_LEADS: list[dict] = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "SmileCare Dental Clinic",
        "category": "dental",
        "city": "Pune",
        "website_url": "http://smilecare-dental.in",
        "source": "google_maps",
        "overall_score": 38,
        "has_website": True,
        "created_at": _NOW,
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "GlowUp Salon & Spa",
        "category": "beauty",
        "city": "Bangalore",
        "website_url": None,
        "source": "google_maps",
        "overall_score": 12,
        "has_website": False,
        "created_at": _NOW,
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "name": "Horizon Realty",
        "category": "real_estate",
        "city": "Mumbai",
        "website_url": "https://horizonrealty.com",
        "source": "csv",
        "overall_score": 72,
        "has_website": True,
        "created_at": _NOW,
    },
]


class PaginatedLeads:
    pass


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List all leads with optional filters",
    description=(
        "Returns paginated business leads. Supports filtering by city, "
        "category, source, and minimum score. DB query wired in Phase 2."
    ),
)
async def list_leads(
    city: str | None = Query(None, description="Filter by city name"),
    category: str | None = Query(None, description="Filter by business category"),
    source: str | None = Query(None, description="Filter by discovery source"),
    min_score: int | None = Query(None, ge=0, le=100, description="Minimum overall score"),
    sort: str = Query("score_desc", description="Sort order: score_desc | score_asc | created_at_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
) -> dict:
    # TODO (Phase 2): Replace with real DB query + filters
    filtered = _STUB_LEADS

    if city:
        filtered = [l for l in filtered if l.get("city", "").lower() == city.lower()]
    if category:
        filtered = [l for l in filtered if l.get("category", "").lower() == category.lower()]
    if source:
        filtered = [l for l in filtered if l.get("source", "").lower() == source.lower()]
    if min_score is not None:
        filtered = [l for l in filtered if (l.get("overall_score") or 0) >= min_score]

    if sort == "score_desc":
        filtered = sorted(filtered, key=lambda x: x.get("overall_score") or 0, reverse=True)
    elif sort == "score_asc":
        filtered = sorted(filtered, key=lambda x: x.get("overall_score") or 0)

    total = len(filtered)
    start = (page - 1) * limit
    paginated = filtered[start : start + limit]

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, (total + limit - 1) // limit),
        "items": [BusinessListItem(**l) for l in paginated],
    }


@router.post(
    "/{lead_id}/pitch",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Regenerate pitch for a lead",
    description="Generates and saves a fresh 2-3 line AI pitch for a scored lead.",
)
async def regenerate_pitch(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        pitch = await generate_and_save_pitch(lead_id, db)
    except BusinessNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PitchContextMissingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PitchGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return {
        "id": str(pitch.id),
        "business_id": str(pitch.business_id),
        "pitch_notes": pitch.pitch_notes,
        "llm_provider": pitch.llm_provider,
        "llm_model": pitch.llm_model,
        "tokens_used": pitch.tokens_used,
        "generated_at": pitch.generated_at,
    }


@router.get(
    "/{lead_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Get full lead detail",
    description="Returns a single lead with full audit signals and LLM score/pitch notes.",
)
async def get_lead(lead_id: uuid.UUID) -> dict:
    # TODO (Phase 2): Fetch from DB with joined audit + score
    stub_audit = AuditRead(
        id=uuid.uuid4(),
        business_id=lead_id,
        url_checked="http://smilecare-dental.in",
        has_website=True,
        ssl_valid=False,
        mobile_friendly=False,
        has_forms=False,
        has_cta=True,
        has_whatsapp=False,
        has_booking=False,
        has_chatbot=False,
        load_time_ms=4200,
        page_speed_score=31,
        has_title=True,
        has_meta_desc=False,
        has_h1=True,
        has_og_tags=False,
        has_facebook=True,
        has_instagram=False,
        has_linkedin=False,
        has_twitter=False,
        tech_stack=["wordpress", "php"],
        screenshot_url=None,
        status="completed",
        error_message=None,
        audited_at=_NOW,
    )
    stub_score = ScoreRead(
        id=uuid.uuid4(),
        business_id=lead_id,
        overall_score=38,
        website_quality=30,
        online_presence=45,
        conversion_readiness=20,
        urgency=55,
        pitch_notes=(
            "- Website loads slowly (4.2s) and has no SSL — immediate red flag for patients.\n"
            "- No WhatsApp button or online booking — losing mobile leads daily.\n"
            "- No meta description means Google is ignoring them in local search."
        ),
        recommended_services=[
            "Website Speed Optimisation",
            "WhatsApp Chat Integration",
            "Online Booking Widget",
            "Local SEO Package",
        ],
        objection_handlers=(
            "1. 'We get referrals' → 72% of patients search online before choosing a clinic.\n"
            "2. 'Too expensive' → Lost bookings each month cost more than our setup fee."
        ),
        llm_provider="groq",
        llm_model="llama-3.3-70b-versatile",
        scored_at=_NOW,
    )

    return {
        "id": str(lead_id),
        "name": "SmileCare Dental Clinic",
        "category": "dental",
        "city": "Pune",
        "website_url": "http://smilecare-dental.in",
        "source": "google_maps",
        "phone": "+91-98765-43210",
        "email": None,
        "rating": 4.2,
        "review_count": 87,
        "created_at": _NOW,
        "updated_at": _NOW,
        "audit": stub_audit,
        "score": stub_score,
    }
