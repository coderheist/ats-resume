from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth.dependencies import AuthenticatedUser, get_current_user
from app.core.services.entitlement_service import usage_summary
from app.core.services.user_service import get_or_create_user
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

    # Allowance state comes from entitlement_service rather than being
    # recomputed here: the same numbers drive the 429 bodies and the
    # upgrade prompts, and a second implementation is how a UI that says
    # "3 of 5 used" ends up next to a request that gets refused.
    return {
        "uid": user.firebase_uid,
        "email": user.email,
        "name": user.name,
        **usage_summary(db, user),
    }
