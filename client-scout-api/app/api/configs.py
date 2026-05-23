"""
api/configs.py - DB-backed niche scoring config endpoints.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.config import NicheConfig
from app.schemas.config import DEFAULT_WEIGHTS, ScoringConfigRead, ScoringConfigUpdate

router = APIRouter(prefix="/configs", tags=["Configs"])


@router.get(
    "",
    response_model=list[ScoringConfigRead],
    status_code=status.HTTP_200_OK,
    summary="List all scoring configurations",
)
async def list_configs(db: AsyncSession = Depends(get_db)) -> list[ScoringConfigRead]:
    result = await db.execute(select(NicheConfig).order_by(NicheConfig.is_default.desc(), NicheConfig.niche))
    configs = result.scalars().all()
    return [_to_read(config) for config in configs]


@router.get(
    "/{niche}",
    response_model=ScoringConfigRead,
    status_code=status.HTTP_200_OK,
    summary="Get scoring config for a specific niche",
)
async def get_config(niche: str, db: AsyncSession = Depends(get_db)) -> ScoringConfigRead:
    config = await _get_config(niche, db)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scoring config found for niche '{niche}'.",
        )
    return _to_read(config)


@router.put(
    "/{niche}",
    response_model=ScoringConfigRead,
    status_code=status.HTTP_200_OK,
    summary="Update or create scoring config for a niche",
)
async def upsert_config(
    niche: str,
    payload: ScoringConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> ScoringConfigRead:
    clean_niche = niche.strip().lower()
    if not clean_niche:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Niche cannot be empty.")

    config = await _get_config(clean_niche, db)
    now = datetime.now(timezone.utc)
    if config is None:
        config = NicheConfig(
            id=uuid.uuid4(),
            niche=clean_niche,
            display_name=clean_niche.replace("_", " ").title(),
            is_default=False,
            created_at=now,
            updated_at=now,
        )
        db.add(config)

    config.weights = payload.weights.model_dump()
    config.prompt_template = payload.prompt_template
    config.pitch_tone = payload.pitch_tone
    config.updated_at = now
    await db.commit()
    await db.refresh(config)
    return _to_read(config)


@router.delete(
    "/{niche}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scoring config for a niche",
)
async def delete_config(niche: str, db: AsyncSession = Depends(get_db)) -> None:
    config = await _get_config(niche, db)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scoring config found for niche '{niche}'.",
        )
    if config.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The default scoring config cannot be deleted.",
        )

    await db.delete(config)
    await db.commit()


async def _get_config(niche: str, db: AsyncSession) -> NicheConfig | None:
    result = await db.execute(select(NicheConfig).where(NicheConfig.niche == niche.strip().lower()))
    return result.scalar_one_or_none()


def _to_read(config: NicheConfig) -> ScoringConfigRead:
    return ScoringConfigRead(
        id=config.id,
        niche=config.niche,
        weights={**DEFAULT_WEIGHTS, **(config.weights or {})},
        prompt_template=config.prompt_template,
        pitch_tone=config.pitch_tone,
        is_default=config.is_default,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )
