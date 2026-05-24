"""
api/leads.py - DB-backed lead listing and detail endpoints.
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone
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
from app.models.outreach import OutreachAttempt
from app.models.pitch import Pitch
from app.models.score import Score
from app.schemas.audit import AuditRead
from app.schemas.business import BusinessListItem, BusinessRead, LeadSalesUpdate
from app.schemas.outreach import (
    OutreachAttemptOut,
    OutreachLeadSummary,
    OutreachTimelineOut,
)
from app.schemas.score import ScoreRead
from app.services.outreach_helpers import build_outreach_payload
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
    agency_fit_bucket: str | None = None,
    lead_status: str | None = None,
    priority_rank: int | None = None,
    created_after: datetime | None = Query(None, description="Only leads created after this timestamp"),
    source: str | None = Query(None, description="Filter by discovery source"),
    search: str | None = Query(None, description="Case-insensitive business name search"),
    min_score: int | None = Query(None, ge=0, le=100, description="Minimum overall score"),
    sort: str = Query("score_desc", description="Sort order: score_desc | score_asc | created_at_desc"),
    page: int = Query(1, ge=1, description="(legacy) page number; ignored when `cursor` is provided"),
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(
        None,
        description=(
            "Opaque pagination cursor returned by a prior response as "
            "`next_cursor`. When provided, page is ignored and results "
            "stream forward keyset-style for stable scrolling under writes."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Paginated lead listing with both legacy offset and forward-only cursor.

    The dashboard's virtualised pipeline view uses cursor pagination because
    it streams thousands of rows; everything else (CSV export, manual
    debugging, niche-config admin) keeps using the page/limit shape so the
    contract stays backwards compatible.
    """
    filters = lead_filters(
        city=city,
        category=category,
        niche=niche,
        bucket=bucket,
        agency_fit_bucket=agency_fit_bucket,
        lead_status=lead_status,
        priority_rank=priority_rank,
        created_after=created_after,
        source=source,
        search=search,
        min_score=min_score,
    )

    use_cursor = cursor is not None
    cursor_filter = _decode_cursor(cursor) if use_cursor else None

    # Total count is omitted in cursor mode: the whole point of keyset
    # pagination is to avoid the OFFSET-style full count on every page,
    # which gets expensive past ~50k leads. Clients use `next_cursor`
    # instead of `total/pages`.
    total: int | None = None
    if not use_cursor:
        count_stmt = (
            select(func.count(Business.id))
            .select_from(Business)
            .outerjoin(Audit, Audit.business_id == Business.id)
            .outerjoin(Score, Score.business_id == Business.id)
            .where(*filters)
        )
        total = await db.scalar(count_stmt) or 0

    select_clause = (
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
    )
    if cursor_filter is not None:
        select_clause = select_clause.where(cursor_filter)

    # Cursor mode: always sort by (created_at desc, id desc) so the keyset
    # comparison is unambiguous. Offset mode keeps the legacy sort options.
    order_by = (
        (desc(Business.created_at), desc(Business.id))
        if use_cursor
        else _lead_sort(sort)
    )
    stmt = select_clause.order_by(*order_by)
    if use_cursor:
        # Fetch limit+1 so we can tell if a next page exists without a count.
        stmt = stmt.limit(limit + 1)
    else:
        stmt = stmt.offset((page - 1) * limit).limit(limit)

    rows = (await db.execute(stmt)).all()
    has_more = use_cursor and len(rows) > limit
    if has_more:
        rows = rows[:limit]

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
            lead_status=business.lead_status or "new",
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

    response: dict = {
        "page": 1 if use_cursor else page,
        "limit": limit,
        "items": items,
    }
    if use_cursor:
        # next_cursor is opaque to the client - we encode the last row's
        # composite key so the next page picks up exactly where this one
        # ended even if rows are inserted in between.
        last_row = rows[-1] if rows else None
        next_cursor = _encode_cursor(last_row[0]) if has_more and last_row else None
        response.update(
            {
                "total": None,
                "pages": None,
                "next_cursor": next_cursor,
                "has_more": bool(next_cursor),
            }
        )
    else:
        response.update(
            {
                "total": total or 0,
                "pages": max(1, ceil((total or 0) / limit)) if total else 1,
            }
        )
    return response


@router.get(
    "/board",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Pipeline board: hot, follow-up, stale, and won columns",
)
async def lead_board(
    column_limit: int = Query(50, ge=5, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return four columns of leads for the dashboard's Kanban board.

    Each column ships the same lightweight `BusinessListItem` shape as the
    table view PLUS the pain-flag dict from the joined audit row, so the
    frontend can render the density grid without an extra round-trip.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stale_cutoff = now - timedelta(days=7)
    won_cutoff = now - timedelta(days=14)

    columns = {
        "hot": (
            (Score.agency_fit_bucket == "hot") & (Business.lead_status == "new"),
            desc(Score.agency_fit_score).nulls_last(),
        ),
        "follow_ups": (
            (
                (Business.follow_up_at.is_not(None) & (Business.follow_up_at <= now))
                & Business.lead_status.in_(["contacted", "replied", "meeting_set"])
            ),
            asc(Business.follow_up_at),
        ),
        "stale": (
            (Business.lead_status == "contacted")
            & Business.last_contacted_at.is_not(None)
            & (Business.last_contacted_at < stale_cutoff),
            asc(Business.last_contacted_at),
        ),
        "won": (
            (Business.lead_status == "won")
            & (Business.updated_at >= won_cutoff),
            desc(Business.updated_at),
        ),
    }

    payload: dict[str, list[dict]] = {}
    for column_name, (where, order) in columns.items():
        stmt = (
            select(
                Business,
                Audit.has_website,
                Audit.pain_flags,
                Score.overall_score,
                Score.agency_fit_score,
                Score.agency_fit_bucket,
                Score.estimated_deal_value,
            )
            .outerjoin(Audit, Audit.business_id == Business.id)
            .outerjoin(Score, Score.business_id == Business.id)
            .where(where)
            .order_by(order, desc(Business.created_at))
            .limit(column_limit)
        )
        rows = (await db.execute(stmt)).all()
        payload[column_name] = [_board_card(row) for row in rows]

    payload["generated_at"] = now.isoformat()
    payload["window"] = {
        "today_start": today_start.isoformat(),
        "stale_cutoff": stale_cutoff.isoformat(),
        "won_cutoff": won_cutoff.isoformat(),
    }
    return payload


def _board_card(row) -> dict:
    business, has_website, pain_flags, overall_score, agency_fit_score, agency_fit_bucket, estimated_deal_value = row
    item = BusinessListItem(
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
        lead_status=business.lead_status or "new",
        follow_up_at=business.follow_up_at,
        priority_rank=business.priority_rank,
        created_at=business.created_at,
    )
    card = item.model_dump(mode="json")
    # Surface pain_flags directly so the frontend density grid can render
    # without another HTTP roundtrip per card.
    card["pain_flags"] = pain_flags or {}
    card["pain_count"] = sum(1 for v in (pain_flags or {}).values() if v)
    card["last_contacted_at"] = business.last_contacted_at.isoformat() if business.last_contacted_at else None
    return card


def _encode_cursor(business: Business) -> str:
    """Pack `(created_at_iso, id)` into a URL-safe opaque cursor."""
    import base64

    payload = f"{business.created_at.isoformat()}|{business.id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None):
    """Decode an opaque cursor into a SQLAlchemy keyset filter expression.

    Returns None when the cursor is missing or unparseable; the caller treats
    that as "first page" so a stale or hand-edited cursor doesn't blow up.
    """
    if not cursor:
        return None
    import base64
    from datetime import datetime as _dt

    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        created_str, id_str = decoded.split("|", 1)
        created_at = _dt.fromisoformat(created_str)
        last_id = uuid.UUID(id_str)
    except Exception:  # noqa: BLE001 - bad cursor: fall back to first page
        logger.warning("[LEADS] discarding malformed cursor=%r", cursor)
        return None

    # Standard keyset condition for `(created_at desc, id desc)`:
    #   row.created_at < last.created_at
    #   OR (row.created_at = last.created_at AND row.id < last.id)
    return (Business.created_at < created_at) | (
        (Business.created_at == created_at) & (Business.id < last_id)
    )


@router.get(
    "/summary",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Daily lead action summary",
)
async def lead_summary(db: AsyncSession = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    stale_cutoff = now - timedelta(days=7)

    followups_today = await db.scalar(
        select(func.count(Business.id)).where(
            Business.follow_up_at >= today_start,
            Business.follow_up_at < tomorrow_start,
        )
    ) or 0
    new_hot_leads = await db.scalar(
        select(func.count(Business.id))
        .join(Score, Score.business_id == Business.id)
        .where(Business.lead_status == "new", Score.agency_fit_bucket == "hot")
    ) or 0
    stale_contacted = await db.scalar(
        select(func.count(Business.id)).where(
            Business.lead_status == "contacted",
            Business.last_contacted_at.is_not(None),
            Business.last_contacted_at < stale_cutoff,
        )
    ) or 0

    return {
        "followups_today": followups_today,
        "new_hot_leads": new_hot_leads,
        "stale_contacted": stale_contacted,
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
        "subject_line": pitch.subject_line,
        "recommended_services": pitch.recommended_services or [],
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


@router.patch(
    "/{lead_id}/sales",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Update lightweight sales workflow fields for a lead",
)
async def update_lead_sales(
    lead_id: uuid.UUID,
    payload: LeadSalesUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    business = await _get_business_or_404(lead_id, db)
    now = datetime.now(timezone.utc)

    if payload.lead_status is not None:
        business.lead_status = payload.lead_status
        if payload.lead_status == "contacted" and payload.last_contacted_at is None:
            business.last_contacted_at = business.last_contacted_at or now

    if payload.follow_up_at is not None:
        business.follow_up_at = payload.follow_up_at
    if payload.last_contacted_at is not None:
        business.last_contacted_at = payload.last_contacted_at
    if payload.sales_notes is not None:
        business.sales_notes = payload.sales_notes
    if payload.priority_rank is not None:
        business.priority_rank = payload.priority_rank
    if payload.assigned_to is not None:
        business.assigned_to = payload.assigned_to
    if payload.increment_contact_attempts:
        business.contact_attempts = (business.contact_attempts or 0) + 1
        business.last_contacted_at = payload.last_contacted_at or now

    await db.commit()
    await db.refresh(business)
    return _sales_payload(business)


@router.post(
    "/{lead_id}/contact-attempt",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Record a manual outreach attempt for a lead",
)
async def record_contact_attempt(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    business = await _get_business_or_404(lead_id, db)
    business.contact_attempts = (business.contact_attempts or 0) + 1
    business.last_contacted_at = datetime.now(timezone.utc)
    if business.lead_status == "new":
        business.lead_status = "contacted"
    await db.commit()
    await db.refresh(business)
    return _sales_payload(business)


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
    outreach = build_outreach_payload(business, pitch)
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
            lead_status=business.lead_status or "new",
        follow_up_at=business.follow_up_at,
        last_contacted_at=business.last_contacted_at,
            contact_attempts=business.contact_attempts or 0,
        sales_notes=business.sales_notes,
        priority_rank=business.priority_rank,
        assigned_to=business.assigned_to,
        whatsapp_link=outreach.whatsapp_link,
        whatsapp_message=outreach.whatsapp_message,
        whatsapp_follow_up=outreach.whatsapp_follow_up,
        email_subject=outreach.email_subject,
        email_body=outreach.email_body,
        call_opener=outreach.call_opener,
        pain_points_used=outreach.pain_points_used,
        pitch_recommended_services=outreach.recommended_services,
        personalization_notes=outreach.personalization_notes,
        discovery_job_id=business.discovery_job_id,
        created_at=business.created_at,
        updated_at=business.updated_at,
        audit=AuditRead.model_validate(business.audit) if business.audit else None,
        score=_score_read(business.score, pitch) if business.score else None,
    )
    return data.model_dump(mode="json")


@router.get(
    "/{lead_id}/outreach",
    response_model=OutreachTimelineOut,
    status_code=status.HTTP_200_OK,
    summary="Get the autonomous outreach timeline for a lead",
)
async def get_lead_outreach(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> OutreachTimelineOut:
    """Return the per-lead outreach summary plus full attempt history.

    Envelope shape (summary + attempts) is intentional: the dashboard's
    Communication Log renders a status header above the timeline list,
    and rolling both into one response avoids a second round-trip from
    the LeadDetailPage. The summary is taken from the lead row's
    denormalised columns (cheap), the timeline from the append-only
    outreach_attempts table (ordered newest-first, capped at 50 - the
    UI never needs more than the recent run plus history).
    """
    business = await _get_business_or_404(lead_id, db)

    attempts_result = await db.execute(
        select(OutreachAttempt)
        .where(OutreachAttempt.business_id == lead_id)
        .order_by(OutreachAttempt.attempted_at.desc())
        .limit(50)
    )
    attempts = list(attempts_result.scalars().all())

    summary = OutreachLeadSummary(
        business_id=business.id,
        outreach_status=business.outreach_status or "idle",
        email_sent_at=business.email_sent_at,
        whatsapp_sent_at=business.whatsapp_sent_at,
        last_outreach_at=business.last_outreach_at,
        last_outreach_error=business.last_outreach_error,
        has_email_channel=bool(business.contact_email or business.email),
        has_whatsapp_channel=bool(business.contact_phone or business.phone),
    )
    return OutreachTimelineOut(
        summary=summary,
        attempts=[OutreachAttemptOut.model_validate(a) for a in attempts],
    )


async def _get_business_or_404(lead_id: uuid.UUID, db: AsyncSession) -> Business:
    result = await db.execute(select(Business).where(Business.id == lead_id))
    business = result.scalar_one_or_none()
    if business is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
    return business


def _sales_payload(business: Business) -> dict:
    return {
        "business_id": str(business.id),
        "lead_status": business.lead_status,
        "follow_up_at": business.follow_up_at,
        "last_contacted_at": business.last_contacted_at,
        "contact_attempts": business.contact_attempts,
        "sales_notes": business.sales_notes,
        "priority_rank": business.priority_rank,
        "assigned_to": business.assigned_to,
    }


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
