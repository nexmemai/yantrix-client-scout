"""
api/export.py - Phase 3-ready lead export endpoints.
"""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.lead_queries import lead_filters
from app.database import get_db
from app.models.audit import Audit
from app.models.business import Business
from app.models.pitch import Pitch
from app.models.score import Score
from app.schemas.export import ExportLeadItem, ExportRequest, ExportResponse

router = APIRouter(prefix="/export", tags=["Export"])


@router.post("", response_model=None, status_code=status.HTTP_200_OK)
async def export_leads(
    payload: ExportRequest,
    db: AsyncSession = Depends(get_db),
) -> ExportResponse | StreamingResponse:
    items = await _load_export_items(payload, db)
    if payload.resolved_destination == "json" and payload.format is not None:
        return JSONResponse(content=[item.model_dump(mode="json") for item in items])
    if payload.resolved_destination == "csv":
        return _csv_response(items)

    return ExportResponse(
        destination=payload.resolved_destination,
        status="ready" if payload.resolved_destination == "json" else "dry_run",
        lead_count=len(items),
        items=items,
    )


async def _load_export_items(payload: ExportRequest, db: AsyncSession) -> list[ExportLeadItem]:
    latest_pitch_ts = (
        select(Pitch.business_id, func.max(Pitch.generated_at).label("generated_at"))
        .group_by(Pitch.business_id)
        .subquery()
    )

    stmt = (
        select(Business, Audit.has_website, Score.overall_score, Score.score_band, Pitch)
        .outerjoin(Audit, Audit.business_id == Business.id)
        .outerjoin(Score, Score.business_id == Business.id)
        .outerjoin(latest_pitch_ts, latest_pitch_ts.c.business_id == Business.id)
        .outerjoin(
            Pitch,
            and_(
                Pitch.business_id == Business.id,
                Pitch.generated_at == latest_pitch_ts.c.generated_at,
            ),
        )
        .where(*_export_filters(payload))
        .order_by(Score.overall_score.desc().nulls_last(), Business.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        ExportLeadItem(
            business_id=business.id,
            name=business.name,
            city=business.city,
            niche=business.niche,
            category=business.category,
            stage=business.stage,
            source=business.source,
            phone=business.phone,
            email=business.email,
            website_url=business.website_url,
            google_maps_url=business.google_maps_url,
            rating=float(business.rating) if business.rating is not None else None,
            review_count=business.review_count,
            has_website=has_website,
            overall_score=overall_score,
            score_band=score_band,
            created_at=business.created_at,
            pitch_notes=pitch.pitch_notes if pitch else None,
            recommended_services=pitch.recommended_services if pitch else None,
            subject_line=pitch.subject_line if pitch else None,
        )
        for business, has_website, overall_score, score_band, pitch in rows
    ]


def _export_filters(payload: ExportRequest) -> list:
    filters = []
    if payload.lead_ids:
        filters.append(Business.id.in_(payload.lead_ids))

    if payload.filters is None:
        filters.extend(
            lead_filters(
                city=payload.city,
                niche=payload.niche,
                score_min=payload.score_min,
                bucket=payload.bucket,
            )
        )
        return filters

    export_filters = payload.filters
    filters.extend(
        lead_filters(
            city=export_filters.city,
            niche=export_filters.niche,
            score_min=export_filters.min_score,
            bucket=payload.bucket,
        )
    )
    if export_filters.stage:
        filters.append(Business.stage == export_filters.stage)
    if export_filters.unexported_only:
        if payload.resolved_destination == "hubspot":
            filters.append(or_(Pitch.id.is_(None), Pitch.exported_to_hubspot.is_(False)))
        elif payload.resolved_destination == "zoho":
            filters.append(or_(Pitch.id.is_(None), Pitch.exported_to_zoho.is_(False)))

    return filters


def _csv_response(items: list[ExportLeadItem]) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "business_id",
            "name",
            "city",
            "niche",
            "category",
            "stage",
            "source",
            "phone",
            "email",
            "website_url",
            "google_maps_url",
            "rating",
            "review_count",
            "has_website",
            "overall_score",
            "bucket",
            "pitch_notes",
            "created_at",
            "recommended_services",
            "subject_line",
        ],
    )
    writer.writeheader()
    for item in items:
        row = item.model_dump(mode="json")
        row["recommended_services"] = ", ".join(item.recommended_services or [])
        row["bucket"] = item.bucket
        row.pop("score_band", None)
        writer.writerow(row)

    buffer.seek(0)
    filename = f"client-scout-export-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
