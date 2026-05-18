"""
api/jobs.py - Discovery job read APIs.
"""

import uuid
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.business import Business
from app.models.job import DiscoveryJob
from app.models.pitch import Pitch
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
    items = [await _job_to_read(db, job) for job in result.scalars().all()]
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
    return await _job_to_read(db, job)


async def _job_to_read(db: AsyncSession, job: DiscoveryJob) -> JobRead:
    total_pitched = await db.scalar(
        select(func.count(Pitch.id))
        .join(Business, Business.id == Pitch.business_id)
        .where(Business.discovery_job_id == job.id)
    )
    return JobRead(
        id=job.id,
        query=job.query,
        city=job.city,
        source=job.source,
        niche=job.niche,
        status=job.status,
        total_discovered=job.total_discovered,
        total_audited=job.total_audited,
        total_scored=job.total_scored,
        total_pitched=total_pitched or 0,
        error_message=job.error_message,
        started_at=job.started_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        last_updated_at=job.updated_at,
        completed_at=job.completed_at,
    )
