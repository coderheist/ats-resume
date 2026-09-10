from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from app.config import B2B_TIERS, B2C_TIERS, DEFAULT_CURRENCY, SUPPORTED_CURRENCIES

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/tiers")
def list_tiers() -> dict:
    """Every tier with its prices in each supported currency.

    `currencies` is served rather than hard-coded in the frontend for the
    same reason as the tier list itself: a currency toggle offering an
    option checkout would reject is worse than not offering it, and the
    two can only stay in step if one of them is the source of truth.
    """
    return {
        "consumer": {tid: asdict(t) for tid, t in B2C_TIERS.items()},
        "business": {tid: asdict(t) for tid, t in B2B_TIERS.items()},
        "currencies": list(SUPPORTED_CURRENCIES),
        "default_currency": DEFAULT_CURRENCY,
    }
