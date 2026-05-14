"""
api/configs.py — GET /configs, PUT /configs/{niche}

Manages per-niche scoring weight configurations.
Currently backed by in-memory stubs; DB integration in Phase 2.
"""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, HTTPException, status

from app.schemas.config import ScoringConfigRead, ScoringConfigUpdate

router = APIRouter(prefix="/configs", tags=["Configs"])

_NOW = datetime.now(timezone.utc)

# In-memory config store (replaced by DB in Phase 2)
_CONFIGS: dict[str, dict] = {
    "default": {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "niche": "default",
        "weights": {
            "has_website": 5,
            "mobile_friendly": 15,
            "has_forms": 15,
            "has_cta": 10,
            "has_whatsapp": 10,
            "has_booking": 15,
            "ssl_valid": 5,
            "page_speed": 10,
            "seo_basics": 10,
            "social_presence": 5,
        },
        "prompt_template": None,
        "is_default": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    },
    "healthcare": {
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "niche": "healthcare",
        "weights": {
            "has_website": 5,
            "mobile_friendly": 20,
            "has_forms": 10,
            "has_cta": 5,
            "has_whatsapp": 15,
            "has_booking": 25,
            "ssl_valid": 5,
            "page_speed": 5,
            "seo_basics": 5,
            "social_presence": 5,
        },
        "prompt_template": None,
        "is_default": False,
        "created_at": _NOW,
        "updated_at": _NOW,
    },
    "beauty": {
        "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "niche": "beauty",
        "weights": {
            "has_website": 5,
            "mobile_friendly": 15,
            "has_forms": 5,
            "has_cta": 10,
            "has_whatsapp": 20,
            "has_booking": 20,
            "ssl_valid": 5,
            "page_speed": 5,
            "seo_basics": 10,
            "social_presence": 5,
        },
        "prompt_template": None,
        "is_default": False,
        "created_at": _NOW,
        "updated_at": _NOW,
    },
}


@router.get(
    "",
    response_model=list[ScoringConfigRead],
    status_code=status.HTTP_200_OK,
    summary="List all scoring configurations",
    description="Returns per-niche scoring weight configurations. DB-backed in Phase 2.",
)
async def list_configs() -> list[ScoringConfigRead]:
    return [ScoringConfigRead(**cfg) for cfg in _CONFIGS.values()]


@router.get(
    "/{niche}",
    response_model=ScoringConfigRead,
    status_code=status.HTTP_200_OK,
    summary="Get scoring config for a specific niche",
)
async def get_config(niche: str) -> ScoringConfigRead:
    if niche not in _CONFIGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scoring config found for niche '{niche}'. "
                   f"Available: {list(_CONFIGS.keys())}",
        )
    return ScoringConfigRead(**_CONFIGS[niche])


@router.put(
    "/{niche}",
    response_model=ScoringConfigRead,
    status_code=status.HTTP_200_OK,
    summary="Update or create scoring config for a niche",
    description=(
        "Updates the weight distribution for a niche. "
        "Weights do not need to sum to 100 — they are normalised during scoring. "
        "DB upsert wired in Phase 2."
    ),
)
async def upsert_config(niche: str, payload: ScoringConfigUpdate) -> ScoringConfigRead:
    # TODO (Phase 2): DB upsert
    existing = _CONFIGS.get(niche)
    now = datetime.now(timezone.utc)

    if existing:
        existing["weights"] = payload.weights.model_dump()
        if payload.prompt_template is not None:
            existing["prompt_template"] = payload.prompt_template
        existing["updated_at"] = now
        return ScoringConfigRead(**existing)
    else:
        new_cfg = {
            "id": str(uuid.uuid4()),
            "niche": niche,
            "weights": payload.weights.model_dump(),
            "prompt_template": payload.prompt_template,
            "is_default": False,
            "created_at": now,
            "updated_at": now,
        }
        _CONFIGS[niche] = new_cfg
        return ScoringConfigRead(**new_cfg)


@router.delete(
    "/{niche}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scoring config for a niche",
)
async def delete_config(niche: str) -> None:
    existing = _CONFIGS.get(niche)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scoring config found for niche '{niche}'.",
        )
    if existing.get("is_default"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The default scoring config cannot be deleted.",
        )
    del _CONFIGS[niche]
