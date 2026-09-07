from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import entitlement_for
from app.core.auth.dependencies import AuthenticatedUser, get_current_user
from app.core.services.entitlement_service import iso_utc, next_reset_at, scans_used_this_month
from app.core.services.user_service import get_or_create_user
from app.db.models import Subscription
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(auth_user: AuthenticatedUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """
    Requires a valid Firebase ID token. Returns 401 if missing/invalid,
    503 if Firebase isn't configured at all (see auth/dependencies.py).

    Creates the local User row (and a free-tier Subscription) on first
    call for a given firebase_uid -- there's no separate "register"
    endpoint, since Firebase already handled account creation client-side
    by the time this is ever called; this just materializes the local
    record the rest of the app (history, entitlements) needs.
    """
    user = get_or_create_user(db, auth_user)
    subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    tier_id = subscription.tier if subscription else "free"
    tier = entitlement_for(tier_id)
    used = scans_used_this_month(db, user)

    return {
        "uid": user.firebase_uid,
        "email": user.email,
        "name": user.name,
        "tier": tier_id,
        "tier_name": tier.name,
        "jd_match_scans_per_month": tier.jd_match_scans_per_month,
        "jd_match_scans_used_this_month": used,
        # Always sent, even on unlimited tiers: the usage window rolls
        # over on the same schedule regardless, and a client that shows
        # "resets on X" shouldn't have to special-case the tier.
        "jd_match_scans_reset_at": iso_utc(next_reset_at()),
        "jd_match_scans_exhausted": (
            tier.jd_match_scans_per_month is not None and used >= tier.jd_match_scans_per_month
        ),
    }
