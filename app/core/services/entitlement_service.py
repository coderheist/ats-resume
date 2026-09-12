"""
Usage recording (Phase 7 of the architecture plan: token/cost tracking,
usage tracking) and entitlement checking (Phase 9: free/pro usage
limits) -- one module because they share the same source of truth
(UsageLog rows), not two separate counters that could drift.

Deliberately centralized rather than scattered through route handlers:
"how many scans has this user run this period" and "does their tier
allow another one" should have exactly one implementation each, used the
same way by every route that needs it.

Two allowances are metered here, and they are counted independently:
scans (`jd_match_scan` / `standalone_scan`) and AI bullet rewrites
(`ai_rewrite`). They are separate because they are separate products to
the user -- running out of rewrites should not stop you checking a score,
and vice versa -- and because they cost materially different amounts to
serve (see app/core/llm/token_pricing.py).

THE ALLOWANCE WINDOW IS THE PASS PERIOD, NOT A CALENDAR MONTH. Plans are
fixed-length passes of 7, 30 or 90 days (see app/config.py's Tier), so a
7-day Boost bought on the 28th must not have its allowance wiped on the
1st. `period_bounds` below is the single place that decides the window,
precisely so the "you're out of scans" message, /auth/me, and the 429
body cannot disagree about when it rolls over.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Tier, entitlement_for
from app.db.models import Subscription, UsageLog, User

SCAN_ACTIONS = ("jd_match_scan", "standalone_scan")
REWRITE_ACTION = "ai_rewrite"


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month_start(now: datetime | None = None) -> datetime:
    start = _month_start(now)
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)


def _day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _is_pass_live(subscription: Subscription | None, now: datetime) -> bool:
    """True if this subscription currently grants a paid tier's benefits.

    Checking `subscription.active` alone is NOT enough, and this is the
    fix for a real bug: nothing anywhere in this codebase ever flips
    `active` back to False once a pass's `renews_at` passes -- there is no
    cron job, no lazy-expiry write-back, nothing writes to that column
    after `_activate_subscription` sets it True at purchase. A row bought
    once stays `active=True` in the database forever.

    Without this check, both the tier used for limits (`jd_match_scans`,
    `ai_rewrites`, `scans_per_day`) and the window used to count usage
    against them survive the pass's own expiry indefinitely. Concretely,
    reproduced against a real Boost pass that "ended" 70 days ago with
    `active` still True: every check kept reporting the buyer as a live
    Boost subscriber against a 7-day window frozen 70 days in the past.
    Because `_count_actions` filters `created_at < end` and `end` was that
    frozen instant, any usage recorded *after* the real expiry fell
    entirely outside the counted window -- so a buyer who hadn't spent
    their whole pass got unlimited, permanently free use of the remainder
    forever, while a buyer who HAD spent it was locked out forever,
    instead of falling back to what they actually still have: the Free
    plan's own allowance and its calendar-month window.
    """
    return (
        subscription is not None
        and subscription.active
        and subscription.renews_at is not None
        and subscription.renews_at > now
    )


def period_bounds(
    tier: Tier,
    subscription: Subscription | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """The half-open window [start, end) the current allowance is counted over.

    A paid pass is anchored to when it was bought: `renews_at` is set at
    activation to purchase time + the tier's duration (see
    app/api/routes/payments.py), so the window is simply that instant
    minus the duration. This is what makes a 7-day pass behave like seven
    days rather than "until the 1st".

    Everything else -- the free tier, a subscription with no expiry
    recorded, and (critically) a subscription whose pass has already
    expired -- falls back to the calendar month. Free has no purchase
    instant to anchor to, and a calendar month is both the least
    surprising thing to show a user ("resets on the 1st") and what this
    app did before passes existed. See `_is_pass_live`'s docstring for why
    "expired" has to be checked here explicitly rather than trusted from
    `subscription.active`.
    """
    now = now or datetime.utcnow()
    if _is_pass_live(subscription, now):
        end = subscription.renews_at
        return end - timedelta(days=tier.duration_days), end
    return _month_start(now), _next_month_start(now)


def next_reset_at(now: datetime | None = None) -> datetime:
    """Calendar-month rollover -- the free tier's reset instant.

    Retained for callers that only have a user and no tier context. Paid
    passes should use `period_bounds(...)[1]` instead, which accounts for
    the pass length; using this for a 7-day pass would report a reset date
    up to a month away.
    """
    return _next_month_start(now)


def iso_utc(value: datetime) -> str:
    """Naive-UTC datetime -> an explicitly-UTC ISO 8601 string, so the
    browser renders the reset moment in the viewer's own timezone
    instead of silently reading it as local time."""
    return value.isoformat(timespec="seconds") + "Z"


def record_scan(db: Session, user: User | None, action: str) -> None:
    """Record a scoring request. user=None for anonymous requests -- still
    logged for aggregate visibility, just never counted against any
    entitlement (see check_scan_allowance)."""
    db.add(UsageLog(user_id=user.id if user else None, action=action))
    db.commit()


def record_rewrite(db: Session, user: User | None, count: int = 1) -> None:
    """Record AI bullet rewrites.

    `count` is the number of rewrite *operations*, not bullets: one
    request that regenerates all four bullets under a role is one
    rewrite, because that is the unit the pricing page sells and the unit
    a user counts. Metering per bullet would make the allowance mean
    something different from what was advertised.
    """
    for _ in range(max(1, count)):
        db.add(UsageLog(user_id=user.id if user else None, action=REWRITE_ACTION))
    db.commit()


def record_llm_call(db: Session, user: User | None, provider: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
    db.add(UsageLog(
        user_id=user.id if user else None, action="llm_call", provider=provider,
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
    ))
    db.commit()


def _count_actions(db: Session, user: User, actions: tuple[str, ...], since: datetime, until: datetime | None = None) -> int:
    query = db.query(func.count(UsageLog.id)).filter(
        UsageLog.user_id == user.id,
        UsageLog.action.in_(actions),
        UsageLog.created_at >= since,
    )
    if until is not None:
        query = query.filter(UsageLog.created_at < until)
    return query.scalar() or 0


def scans_used_this_month(db: Session, user: User) -> int:
    """Calendar-month scan count. Kept for callers with no tier context;
    entitlement decisions go through check_scan_allowance, which counts
    over the pass period instead."""
    return _count_actions(db, user, SCAN_ACTIONS, _month_start())


def _subscription_and_tier(
    db: Session, user: User, now: datetime | None = None,
) -> tuple[Subscription | None, str, Tier]:
    """Resolves which tier's limits currently apply.

    Uses `_is_pass_live`, not just `subscription.active`, for the tier
    decision -- the same expiry check `period_bounds` uses, and for the
    same reason (see its docstring): `active` never gets flipped off on
    its own, so a subscription whose pass ended stays reported as that
    paid tier forever unless expiry is checked here explicitly. The
    caller passes the SAME `now` to this and to `period_bounds` so the
    tier-fallback decision and the window it's counted over can never
    disagree about whether a given instant still falls inside a live
    pass.
    """
    now = now or datetime.utcnow()
    subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    tier_id = subscription.tier if _is_pass_live(subscription, now) else "free"
    try:
        tier = entitlement_for(tier_id)
    except KeyError:
        # A tier id that no longer exists in the pricing table -- e.g. a
        # subscription sold under an older catalogue that has since been
        # renamed. Falling back to free is the safe direction: it
        # under-serves rather than handing out an unbounded allowance
        # nobody is paying for, and it cannot 500 a request.
        tier_id, tier = "free", entitlement_for("free")
    return subscription, tier_id, tier


@dataclass
class EntitlementCheck:
    allowed: bool
    used: int
    limit: int | None  # None = unlimited
    tier: str
    reason: str | None = None
    resets_at: datetime | None = None  # None only when the tier is unlimited


def check_scan_allowance(db: Session, user: User | None) -> EntitlementCheck:
    """
    Anonymous requests are never blocked here -- this app's free scoring
    tools have always been publicly usable without an account (see
    README's backward-compatibility notes), and that doesn't change just
    because accounts now exist. Limits apply only once a user is signed
    in, matching a normal freemium shape: try it anonymously, sign up
    once you want history/rewrites/higher limits.

    Two ceilings apply, and the daily one is reported first when both are
    hit: the per-period allowance, and a per-day fair-use cap that exists
    to bound scripted abuse rather than to constrain a real job seeker
    (nobody applies to fifteen roles a day for a month).
    """
    if user is None:
        return EntitlementCheck(allowed=True, used=0, limit=None, tier="anonymous")

    now = datetime.utcnow()
    subscription, tier_id, tier = _subscription_and_tier(db, user, now)
    start, end = period_bounds(tier, subscription, now)

    if tier.scans_per_day is not None:
        today = _count_actions(db, user, SCAN_ACTIONS, _day_start())
        if today >= tier.scans_per_day:
            tomorrow = _day_start() + timedelta(days=1)
            return EntitlementCheck(
                allowed=False, used=today, limit=tier.scans_per_day, tier=tier_id,
                reason=(
                    f"You've hit the fair-use limit of {tier.scans_per_day} scans a day on the "
                    f"{tier.name} plan. It resets at 00:00 UTC, in a few hours."
                ),
                resets_at=tomorrow,
            )

    if tier.jd_match_scans is None:
        return EntitlementCheck(allowed=True, used=0, limit=None, tier=tier_id)

    used = _count_actions(db, user, SCAN_ACTIONS, start, end)
    allowed = used < tier.jd_match_scans
    reason = None if allowed else (
        f"You've used all {tier.jd_match_scans} scans included in the {tier.name} plan. "
        f"Your allowance resets on {end.strftime('%d %B %Y')} at 00:00 UTC."
    )
    return EntitlementCheck(
        allowed=allowed, used=used, limit=tier.jd_match_scans,
        tier=tier_id, reason=reason, resets_at=end,
    )


def check_rewrite_allowance(db: Session, user: User | None) -> EntitlementCheck:
    """
    Unlike scanning, an AI rewrite ALWAYS requires an account.

    Scanning is deliberately open to anonymous visitors because it is the
    thing people arrive from a search result to try. A rewrite is the
    metered, paid feature and the one with a real per-call cost, so
    letting it run unauthenticated would mean an uncapped allowance for
    anyone who clears their cookies. Callers should turn `allowed=False`
    with tier "anonymous" into a 401, not a 429.
    """
    if user is None:
        return EntitlementCheck(
            allowed=False, used=0, limit=0, tier="anonymous",
            reason="Sign in to use AI rewrites. The free plan includes 3 a month.",
        )

    now = datetime.utcnow()
    subscription, tier_id, tier = _subscription_and_tier(db, user, now)
    start, end = period_bounds(tier, subscription, now)

    if tier.ai_rewrites is None:
        return EntitlementCheck(allowed=True, used=0, limit=None, tier=tier_id)

    used = _count_actions(db, user, (REWRITE_ACTION,), start, end)
    allowed = used < tier.ai_rewrites
    reason = None if allowed else (
        f"You've used all {tier.ai_rewrites} AI rewrites included in the {tier.name} plan. "
        f"Your allowance resets on {end.strftime('%d %B %Y')} at 00:00 UTC."
    )
    return EntitlementCheck(
        allowed=allowed, used=used, limit=tier.ai_rewrites,
        tier=tier_id, reason=reason, resets_at=end,
    )


def usage_summary(db: Session, user: User) -> dict:
    """Everything /auth/me needs to render allowance state, in one place.

    Returned as a dict rather than assembled in the route so the pricing
    page, the limit dialog, and the account screen all read the same
    numbers -- and so adding a third metered feature later is one edit
    here rather than a hunt through route handlers.
    """
    now = datetime.utcnow()
    subscription, tier_id, tier = _subscription_and_tier(db, user, now)
    start, end = period_bounds(tier, subscription, now)
    scans_used = _count_actions(db, user, SCAN_ACTIONS, start, end)
    rewrites_used = _count_actions(db, user, (REWRITE_ACTION,), start, end)
    return {
        "tier": tier_id,
        "tier_name": tier.name,
        "duration_days": tier.duration_days,
        "period_start": iso_utc(start),
        "period_end": iso_utc(end),
        "scans_limit": tier.jd_match_scans,
        "scans_used": scans_used,
        "scans_exhausted": tier.jd_match_scans is not None and scans_used >= tier.jd_match_scans,
        "scans_per_day": tier.scans_per_day,
        "rewrites_limit": tier.ai_rewrites,
        "rewrites_used": rewrites_used,
        "rewrites_exhausted": tier.ai_rewrites is not None and rewrites_used >= tier.ai_rewrites,
    }
