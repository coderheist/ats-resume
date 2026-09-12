"""
AI bullet rewriting -- the metered feature the paid plans sell.

Sits in its own module rather than in resume.py or scan.py because it is
the only endpoint in the app with a per-call allowance that is not the
scan allowance, and mixing the two meters in one file is how they end up
sharing a counter by accident.

Unlike scoring, this endpoint ALWAYS requires an account. The scoring
routes are deliberately open to anonymous visitors -- they are what
someone arrives from a search result to try -- but a rewrite has a real
per-call cost and is the thing being sold, so serving it unauthenticated
would hand an uncapped allowance to anyone who clears their cookies.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth.dependencies import AuthenticatedUser, get_current_user
from app.core.llm.bullet_rewrite import MAX_BULLETS_PER_REQUEST, rewrite_bullets
from app.core.llm.client_factory import get_client_for
from app.core.llm.tier_routing import rewrite_task_for_tier
from app.core.services.entitlement_service import (
    check_rewrite_allowance,
    iso_utc,
    record_rewrite,
)
from app.core.services.user_service import get_or_create_user
from app.config import entitlement_for
from app.db.models import Subscription
from app.db.session import get_db
from app.schemas.api_models import RewriteBulletsRequest

router = APIRouter(prefix="/resume", tags=["resume-rewrite"])

_log = logging.getLogger(__name__)


@router.post("/rewrite-bullets")
def rewrite_bullets_route(
    request: RewriteBulletsRequest,
    auth_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Rewrite one role's bullet points, optionally tailored to a job
    description.

    Allowance is checked BEFORE the model call and recorded AFTER it
    succeeds. That ordering is deliberate in both directions: checking
    first means an out-of-allowance user never costs us a paid API call,
    and recording last means a user is never charged an allowance unit
    for a request that failed upstream -- which is the version of this
    bug people actually complain about.
    """
    if not request.bullets or not any(b and b.strip() for b in request.bullets):
        raise HTTPException(status_code=400, detail="Send at least one non-empty bullet to rewrite.")
    if len(request.bullets) > MAX_BULLETS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Send at most {MAX_BULLETS_PER_REQUEST} bullets in one request -- "
                "that is one role's worth, which is the unit a rewrite is metered in."
            ),
        )

    user = get_or_create_user(db, auth_user)

    check = check_rewrite_allowance(db, user)
    if not check.allowed:
        # The body mirrors the scan limiter's shape (see scan.py) so the
        # frontend's limit dialog can render either without branching:
        # a complete human-readable `message`, plus the fields it needs to
        # show a reset time and an upgrade link.
        raise HTTPException(status_code=429, detail={
            "error": "rewrite_limit_reached",
            "message": check.reason,
            "used": check.used,
            "limit": check.limit,
            "tier": check.tier,
            "resets_at": iso_utc(check.resets_at) if check.resets_at else None,
        })

    subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    tier_id = subscription.tier if subscription and subscription.active else "free"
    try:
        tier = entitlement_for(tier_id)
    except KeyError:
        tier = entitlement_for("free")

    # Which model answers depends on what they paid: the rewrite is the
    # one place in the request path where model quality is plainly
    # visible in the output, so it is where the tiers actually differ.
    # See app/core/llm/tier_routing.py.
    task = rewrite_task_for_tier(tier)
    try:
        client, model = get_client_for(task)
    except Exception as exc:  # noqa: BLE001 -- no provider configured, missing key, etc.
        _log.warning("Rewrite unavailable -- no usable LLM client: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="AI rewrite is temporarily unavailable. Your allowance has not been used.",
        ) from None

    try:
        results = rewrite_bullets(
            client,
            request.bullets,
            role_title=request.role_title,
            company=request.company,
            jd_text=request.jd_text,
            model=model,
            task=task,
        )
    except Exception as exc:  # noqa: BLE001 -- provider error, malformed JSON, timeout
        _log.warning("Bullet rewrite failed on model %s: %s", model, exc)
        raise HTTPException(
            status_code=502,
            detail="The rewrite model didn't return a usable answer. Your allowance has not been used.",
        ) from None

    record_rewrite(db, user)
    after = check_rewrite_allowance(db, user)

    return {
        "bullets": [r.as_dict() for r in results],
        # Echoed so the UI can show "7 of 100 rewrites used" without a
        # second round trip to /auth/me right after every rewrite.
        "rewrites_used": after.used,
        "rewrites_limit": after.limit,
        "tier": tier_id,
        "model_quality": tier.rewrite_quality,
    }
