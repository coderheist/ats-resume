from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from app.config import (
    B2B_TIERS,
    B2C_DISPLAY_ORDER,
    B2C_TIERS,
    DEFAULT_CURRENCY,
    RECOMMENDED_TIER_ID,
    SUPPORTED_CURRENCIES,
)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/tiers")
def list_tiers() -> dict:
    """Every tier with its prices in each supported currency.

    `currencies` is served rather than hard-coded in the frontend for the
    same reason as the tier list itself: a currency toggle offering an
    option checkout would reject is worse than not offering it, and the
    two can only stay in step if one of them is the source of truth.

    `display_order` and `recommended` are served for that same reason.
    Which plan a pricing page leads with is a commercial decision, and
    deciding it a second time in the frontend is how the highlighted card
    ends up disagreeing with the plan the business is actually pushing.

    Note there is no billing_cycle anywhere in this payload: each tier is
    a fixed-length pass carrying its own `duration_days` (see
    app/config.py's Tier docstring), so price and length are settled by
    picking a plan.
    """
    return {
        "consumer": {tid: asdict(t) for tid, t in B2C_TIERS.items()},
        "business": {tid: asdict(t) for tid, t in B2B_TIERS.items()},
        "display_order": list(B2C_DISPLAY_ORDER),
        "recommended": RECOMMENDED_TIER_ID,
        "currencies": list(SUPPORTED_CURRENCIES),
        "default_currency": DEFAULT_CURRENCY,
    }
