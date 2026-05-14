"""
api/jobs.py - Discovery job read APIs.
"""

import uuid
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import DiscoveryJob
from app.schemas.job import JobRead

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("", response_model=dict, status_code=status.HTTP_200_OK)
async def list_jobs(
    status_filter: str | None = Query(None, alias="status"),
    city: str | None = Query(None),
    niche: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    filters = []
    if status_filter:
        filters.append(DiscoveryJob.status == status_filter)
    if city:
        filters.append(func.lower(DiscoveryJob.city) == city.lower())
    if niche:
        filters.append(func.lower(DiscoveryJob.niche) == niche.lower())

    total = await db.scalar(select(func.count(DiscoveryJob.id)).where(*filters)) or 0
    result = await db.execute(
        select(DiscoveryJob)
        .where(*filters)
        .order_by(desc(DiscoveryJob.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = [JobRead.model_validate(job) for job in result.scalars().all()]
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, ceil(total / limit)) if total else 1,
        "items": items,
    }


@router.get("/{job_id}", response_model=JobRead, status_code=status.HTTP_200_OK)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> JobRead:
    result = await db.execute(select(DiscoveryJob).where(DiscoveryJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return JobRead.model_validate(job)
