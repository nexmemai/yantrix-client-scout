"""
api/leads.py - DB-backed lead listing and detail endpoints.
"""

import uuid
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


@router.get(
    "",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List all leads with optional filters",
)
async def list_leads(
    city: str | None = Query(None, description="Filter by city name"),
    category: str | None = Query(None, description="Filter by business category"),
    source: str | None = Query(None, description="Filter by discovery source"),
    min_score: int | None = Query(None, ge=0, le=100, description="Minimum overall score"),
    sort: str = Query("score_desc", description="Sort order: score_desc | score_asc | created_at_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = _lead_filters(city=city, category=category, source=source, min_score=min_score)

    count_stmt = (
        select(func.count(Business.id))
        .select_from(Business)
        .outerjoin(Audit, Audit.business_id == Business.id)
        .outerjoin(Score, Score.business_id == Business.id)
        .where(*filters)
    )
    total = await db.scalar(count_stmt) or 0

    stmt = (
        select(Business, Audit.has_website, Score.overall_score)
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
            has_website=has_website,
            created_at=business.created_at,
        )
        for business, has_website, overall_score in rows
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
        source=business.source,
        discovery_job_id=business.discovery_job_id,
        created_at=business.created_at,
        updated_at=business.updated_at,
        audit=AuditRead.model_validate(business.audit) if business.audit else None,
        score=_score_read(business.score, pitch) if business.score else None,
    )
    return data.model_dump(mode="json")


def _lead_filters(
    *,
    city: str | None,
    category: str | None,
    source: str | None,
    min_score: int | None,
) -> list:
    filters = []
    if city:
        filters.append(func.lower(Business.city) == city.lower())
    if category:
        filters.append(func.lower(Business.category) == category.lower())
    if source:
        filters.append(func.lower(Business.source) == source.lower())
    if min_score is not None:
        filters.append(Score.overall_score >= min_score)
    return filters


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
        pitch_notes=pitch.pitch_notes if pitch else None,
        recommended_services=pitch.recommended_services if pitch else None,
        objection_handlers=pitch.objection_handlers if pitch else None,
        llm_provider=score.llm_provider,
        llm_model=score.llm_model,
        scored_at=score.scored_at,
    )
