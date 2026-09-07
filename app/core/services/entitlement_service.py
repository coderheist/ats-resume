"""
Usage recording (Phase 7 of the architecture plan: token/cost tracking,
usage tracking) and entitlement checking (Phase 9: free/pro usage
limits) -- one module because they share the same source of truth
(UsageLog rows), not two separate counters that could drift.

Deliberately centralized rather than scattered through route handlers:
"how many scans has this user run this month" and "does their tier
allow another one" should have exactly one implementation each, used the
same way by every route that needs it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import entitlement_for
from app.db.models import Subscription, UsageLog, User


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def record_scan(db: Session, user: User | None, action: str) -> None:
    """Record a scoring request. user=None for anonymous requests -- still
    logged for aggregate visibility, just never counted against any
    entitlement (see check_scan_allowance)."""
    db.add(UsageLog(user_id=user.id if user else None, action=action))
    db.commit()


def record_llm_call(db: Session, user: User | None, provider: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
    db.add(UsageLog(
        user_id=user.id if user else None, action="llm_call", provider=provider,
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
    ))
    db.commit()


def scans_used_this_month(db: Session, user: User) -> int:
    return (
        db.query(func.count(UsageLog.id))
        .filter(
            UsageLog.user_id == user.id,
            UsageLog.action.in_(["jd_match_scan", "standalone_scan"]),
            UsageLog.created_at >= _month_start(),
        )
        .scalar()
        or 0
    )


@dataclass
class EntitlementCheck:
    allowed: bool
    used: int
    limit: int | None  # None = unlimited
    tier: str
    reason: str | None = None


def check_scan_allowance(db: Session, user: User | None) -> EntitlementCheck:
    """
    Anonymous requests are never blocked here -- this app's free scoring
    tools have always been publicly usable without an account (see
    README's backward-compatibility notes), and that doesn't change just
    because accounts now exist. Limits apply only once a user is signed
    in, matching a normal freemium shape: try it anonymously, sign up
    once you want history/higher limits.
    """
    if user is None:
        return EntitlementCheck(allowed=True, used=0, limit=None, tier="anonymous")

    subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    tier_id = subscription.tier if subscription and subscription.active else "free"
    tier = entitlement_for(tier_id)

    if tier.jd_match_scans_per_month is None:
        return EntitlementCheck(allowed=True, used=0, limit=None, tier=tier_id)

    used = scans_used_this_month(db, user)
    allowed = used < tier.jd_match_scans_per_month
    reason = None if allowed else (
        f"You've used all {tier.jd_match_scans_per_month} scans included in the {tier.name} plan this month."
    )
    return EntitlementCheck(allowed=allowed, used=used, limit=tier.jd_match_scans_per_month, tier=tier_id, reason=reason)
