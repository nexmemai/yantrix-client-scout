"""
api/leads.py - DB-backed lead listing and detail endpoints.
"""

import uuid
import logging
from datetime import datetime, timezone
from math import ceil

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.api.lead_queries import lead_filters
from app.database import get_db
from app.models.audit import Audit
from app.models.business import Business
from app.models.pitch import Pitch
from app.models.score import Score
from app.schemas.audit import AuditRead
from app.schemas.business import BusinessListItem, BusinessRead
from app.schemas.score import ScoreRead
from app.services.pitch_generator import (
    BusinessNotFoundError,
    PitchContextMissingError,
    PitchGenerationError,
    generate_and_save_pitch,
)

router = APIRouter(prefix="/leads", tags=["Leads"])
logger = logging.getLogger(__name__)


@router.get(
    "",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List all leads with optional filters",
)
async def list_leads(
    city: str | None = Query(None, description="Filter by city name"),
    category: str | None = Query(None, description="Filter by business category"),
    niche: str | None = Query(None, description="Filter by niche key"),
    bucket: str | None = Query(None, description="Filter by score bucket: high | mid | low"),
    created_after: datetime | None = Query(None, description="Only leads created after this timestamp"),
    source: str | None = Query(None, description="Filter by discovery source"),
    search: str | None = Query(None, description="Case-insensitive business name search"),
    min_score: int | None = Query(None, ge=0, le=100, description="Minimum overall score"),
    sort: str = Query("score_desc", description="Sort order: score_desc | score_asc | created_at_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = lead_filters(
        city=city,
        category=category,
        niche=niche,
        bucket=bucket,
        created_after=created_after,
        source=source,
        search=search,
        min_score=min_score,
    )

    count_stmt = (
        select(func.count(Business.id))
        .select_from(Business)
        .outerjoin(Audit, Audit.business_id == Business.id)
        .outerjoin(Score, Score.business_id == Business.id)
        .where(*filters)
    )
    total = await db.scalar(count_stmt) or 0

    stmt = (
        select(
            Business,
            Audit.has_website,
            Score.overall_score,
            Score.agency_fit_score,
            Score.agency_fit_bucket,
            Score.estimated_deal_value,
        )
        .outerjoin(Audit, Audit.business_id == Business.id)
        .outerjoin(Score, Score.business_id == Business.id)
        .where(*filters)
        .order_by(*_lead_sort(sort))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    items = [
        BusinessListItem(
            id=business.id,
            name=business.name,
            category=business.category,
            city=business.city,
            website_url=business.website_url,
            source=business.source,
            overall_score=overall_score,
            agency_fit_score=agency_fit_score,
            agency_fit_bucket=agency_fit_bucket,
            estimated_deal_value=estimated_deal_value,
            has_website=has_website,
            rating=float(business.rating) if business.rating is not None else None,
            review_count=business.review_count,
            lead_status=business.lead_status,
            follow_up_at=business.follow_up_at,
            priority_rank=business.priority_rank,
            created_at=business.created_at,
        )
        for (
            business,
            has_website,
            overall_score,
            agency_fit_score,
            agency_fit_bucket,
            estimated_deal_value,
        ) in rows
    ]

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, ceil(total / limit)) if total else 1,
        "items": items,
    }


@router.post(
    "/{lead_id}/pitch",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Regenerate pitch for a lead",
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


@router.post(
    "/{lead_id}/webhook",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Send the latest lead payload to a CRM webhook",
)
async def send_lead_webhook(
    lead_id: uuid.UUID,
    webhook_url: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    result = await db.execute(select(Business).where(Business.id == lead_id))
    business = result.scalar_one_or_none()
    if business is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")

    target_url = webhook_url or business.webhook_url or settings.LEAD_WEBHOOK_DEFAULT_URL
    if not target_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook URL is not configured.")

    pitch = await _latest_pitch(lead_id, db)
    payload = {
        "business_id": str(business.id),
        "name": business.name,
        "niche": business.niche,
        "category": business.category,
        "city": business.city,
        "phone": business.phone,
        "email": business.email,
        "website_url": business.website_url,
        "source": business.source,
        "pitch": pitch.pitch_notes if pitch else None,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(target_url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        business.last_sync_at = datetime.now(timezone.utc)
        business.last_sync_status = f"failed: {exc!s}"[:255]
        await db.commit()
        logger.warning("Lead webhook failed lead_id=%s url=%s error=%s", lead_id, target_url, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Webhook delivery failed.") from exc

    business.webhook_url = target_url
    business.last_sync_at = datetime.now(timezone.utc)
    business.last_sync_status = f"success:{response.status_code}"
    await db.commit()
    return {"status": "sent", "business_id": str(lead_id), "status_code": response.status_code}


@router.get(
    "/{lead_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Get full lead detail",
)
async def get_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Business)
        .options(selectinload(Business.audit), selectinload(Business.score))
        .where(Business.id == lead_id)
    )
    business = result.scalar_one_or_none()
    if business is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")

    pitch = await _latest_pitch(lead_id, db)
    data = BusinessRead(
        id=business.id,
        name=business.name,
        category=business.category,
        niche=business.niche,
        address=business.address,
        city=business.city,
        state=business.state,
        country=business.country,
        phone=business.phone,
        email=business.email,
        website_url=business.website_url,
        google_maps_url=business.google_maps_url,
        rating=float(business.rating) if business.rating is not None else None,
        review_count=business.review_count,
        contact_name=business.contact_name,
        contact_title=business.contact_title,
        contact_email=business.contact_email,
        contact_phone=business.contact_phone,
        contact_linkedin_url=business.contact_linkedin_url,
        contact_confidence=business.contact_confidence,
        primary_language=business.primary_language,
        domain_age_years=float(business.domain_age_years) if business.domain_age_years is not None else None,
        has_recent_updates=business.has_recent_updates,
        budget_tier=business.budget_tier,
        reliability=business.reliability,
        source=business.source,
        lead_status=business.lead_status,
        follow_up_at=business.follow_up_at,
        last_contacted_at=business.last_contacted_at,
        contact_attempts=business.contact_attempts,
        sales_notes=business.sales_notes,
        priority_rank=business.priority_rank,
        assigned_to=business.assigned_to,
        discovery_job_id=business.discovery_job_id,
        created_at=business.created_at,
        updated_at=business.updated_at,
        audit=AuditRead.model_validate(business.audit) if business.audit else None,
        score=_score_read(business.score, pitch) if business.score else None,
    )
    return data.model_dump(mode="json")


def _lead_sort(sort: str) -> tuple:
    if sort == "score_asc":
        return (asc(Score.overall_score).nulls_last(), desc(Business.created_at))
    if sort == "created_at_desc":
        return (desc(Business.created_at),)
    return (desc(Score.overall_score).nulls_last(), desc(Business.created_at))


async def _latest_pitch(lead_id: uuid.UUID, db: AsyncSession) -> Pitch | None:
    result = await db.execute(
        select(Pitch)
        .where(Pitch.business_id == lead_id)
        .order_by(Pitch.generated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _score_read(score: Score, pitch: Pitch | None) -> ScoreRead:
    return ScoreRead(
        id=score.id,
        business_id=score.business_id,
        overall_score=score.overall_score,
        website_quality=score.website_quality,
        online_presence=score.online_presence,
        conversion_readiness=score.conversion_readiness,
        urgency=score.urgency,
        agency_fit_score=score.agency_fit_score,
        agency_fit_bucket=score.agency_fit_bucket,
        opportunity_types=score.opportunity_types,
        estimated_deal_value=score.estimated_deal_value,
        pitch_notes=pitch.pitch_notes if pitch else None,
        recommended_services=pitch.recommended_services if pitch else None,
        objection_handlers=pitch.objection_handlers if pitch else None,
        llm_provider=score.llm_provider,
        llm_model=score.llm_model,
        scored_at=score.scored_at,
    )
