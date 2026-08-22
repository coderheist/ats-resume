from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from app.config import B2B_TIERS, B2C_TIERS

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/tiers")
def list_tiers() -> dict:
    return {
        "consumer": {tid: asdict(t) for tid, t in B2C_TIERS.items()},
        "business": {tid: asdict(t) for tid, t in B2B_TIERS.items()},
    }
