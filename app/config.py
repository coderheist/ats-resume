"""
Pricing/entitlement configuration. Kept as plain data (not scattered across
route handlers) so billing logic, upgrade prompts, and the pricing page can
all read from one source of truth -- and so it's obvious this needs to move
to a database-backed, dashboard-editable config once pricing needs to
change without a deploy.

Numbers match Section 7 of the blueprint.
"""
from __future__ import annotations

from dataclasses import dataclass


# Currencies checkout accepts. Razorpay requires the amount in the
# smallest unit of whichever one is used -- cents for USD, paise for INR
# -- and both happen to be 1/100, which is why one `* 100` covers both.
# Adding a zero-decimal currency (JPY, KRW) would break that assumption,
# so it is stated here rather than left implicit at the call site.
SUPPORTED_CURRENCIES: tuple[str, ...] = ("USD", "INR")
DEFAULT_CURRENCY = "USD"


@dataclass(frozen=True)
class Tier:
    """One purchasable plan.

    Plans are fixed-length PASSES, not auto-renewing subscriptions: each
    tier carries its own `duration_days` and is bought outright. That is a
    deliberate match to two facts. First, job hunting is a burst -- a
    candidate needs this intensely for six to ten weeks and then gets
    hired and stops -- so a monthly recurring charge against that
    behaviour churns hard and reads to the buyer as an open-ended
    commitment. Second, app/core/billing/razorpay_client.py implements
    one-time orders only; there is no Razorpay Subscriptions/auto-debit
    integration and no UPI AutoPay mandate handling, so a pass is what the
    billing code can actually honour today.

    There is therefore no billing_cycle anywhere: the tier IS the
    duration. "Pro" means 30 days, "Pro Season" means 90.
    """
    id: str
    name: str
    tagline: str
    # Priced per currency, never converted at run time. A live FX rate
    # would move the displayed price between page load and checkout, and a
    # hard-coded one drifts. Local pricing is also a business decision
    # rather than an arithmetic one: the INR numbers are set at round
    # local price points against the Indian market these plans target
    # (competing tools there anchor around Rs 249/month, and Rs 800-1500
    # is the band that market is documented as rejecting), while the USD
    # numbers are set for a market whose incumbents charge $25-50/month.
    # The two are intentionally NOT the same amount of money.
    price_inr: float
    price_usd: float
    duration_days: int
    # None = unlimited. Both allowances are per PASS PERIOD, not per
    # calendar month -- a 7-day Boost gets 30 scans across those 7 days.
    jd_match_scans: int | None
    ai_rewrites: int | None
    # Fair-use burst cap. Costs a real job seeker nothing (nobody applies
    # to 15 roles a day for a month) and bounds what a scripted abuser can
    # spend of an allowance in one sitting.
    scans_per_day: int | None
    # Which model class serves each operation, as a plain label rather
    # than a model id or a router enum -- keeping this module free of
    # imports from app.core.llm is what lets the pricing table stay pure
    # data (see the module docstring). app/core/llm/tier_routing.py maps
    # these to TaskTypes; nothing else should interpret them.
    #
    # "fast"    -- cheapest adequate model (Gemini flash-lite class)
    # "quality" -- the better model, reserved for the operation people pay
    #              for (Gemini 3.6-flash class)
    scan_quality: str
    rewrite_quality: str
    features: tuple[str, ...]


# The consumer ladder. Sized from measured token costs (see
# app/core/llm/token_pricing.py) so that even a subscriber who burns 100%
# of their allowance leaves a 73-81% gross margin after payment-gateway
# fees, on Gemini models.
#
# Scans are cheap because most of the work is not an LLM call at all:
# scoring runs locally (app/core/scoring), and resume_extraction.py runs a
# heuristic parser first, escalating to a model only when confidence falls
# below threshold. The metered thing that actually costs money, and the
# thing people pay for, is the AI rewrite -- which is why scans and
# rewrites are sold at matched counts rather than a lopsided split.
B2C_TIERS: dict[str, Tier] = {
    "free": Tier(
        id="free", name="Free",
        tagline="Try it on one application.",
        price_inr=0, price_usd=0, duration_days=30,
        jd_match_scans=5, ai_rewrites=3,
        scans_per_day=None,  # 5 in a month is its own cap
        scan_quality="fast", rewrite_quality="fast",
        features=(
            "ats_readiness_score",
            "jd_match_report",
            "top_5_suggestions",
            "json_resume_export",
        ),
    ),
    "boost": Tier(
        id="boost", name="Boost",
        tagline="One week, one big push.",
        price_inr=149, price_usd=4.99, duration_days=7,
        jd_match_scans=30, ai_rewrites=30,
        scans_per_day=15,
        scan_quality="fast", rewrite_quality="quality",
        features=(
            "ats_readiness_score",
            "jd_match_report",
            "top_5_suggestions",
            "json_resume_export",
            "ai_bullet_rewrite",
            "full_xai_breakdown",
            "scan_history",
        ),
    ),
    "pro": Tier(
        id="pro", name="Pro",
        tagline="100 scans and 100 rewrites a month.",
        price_inr=399, price_usd=12.99, duration_days=30,
        jd_match_scans=100, ai_rewrites=100,
        scans_per_day=15,
        scan_quality="fast", rewrite_quality="quality",
        features=(
            "ats_readiness_score",
            "jd_match_report",
            "top_5_suggestions",
            "json_resume_export",
            "ai_bullet_rewrite",
            "full_xai_breakdown",
            "scan_history",
            "unlimited_resume_versions",
        ),
    ),
    "pro_season": Tier(
        id="pro_season", name="Pro Season",
        tagline="A whole job hunt. Best value.",
        price_inr=999, price_usd=29.99, duration_days=90,
        jd_match_scans=300, ai_rewrites=300,
        scans_per_day=15,
        scan_quality="fast", rewrite_quality="quality",
        features=(
            "ats_readiness_score",
            "jd_match_report",
            "top_5_suggestions",
            "json_resume_export",
            "ai_bullet_rewrite",
            "full_xai_breakdown",
            "scan_history",
            "unlimited_resume_versions",
            "priority_support",
        ),
    ),
}

# Not part of the launch ladder. Kept so /billing/tiers keeps its existing
# shape, but these are speculative: they were written around a bias-audit
# product that is not shipping, and their prices have never been tested on
# a real buyer. Do not put them on the pricing page without repricing.
B2B_TIERS: dict[str, Tier] = {
    "team": Tier(
        id="team", name="Team",
        tagline="Speculative -- not launched.",
        price_inr=6599, price_usd=79, duration_days=30,
        jd_match_scans=None, ai_rewrites=None, scans_per_day=None,
        scan_quality="fast", rewrite_quality="quality",
        features=("candidate_pool_ranking", "per_candidate_xai"),
    ),
    "business": Tier(
        id="business", name="Business",
        tagline="Speculative -- not launched.",
        price_inr=12499, price_usd=149, duration_days=30,
        jd_match_scans=None, ai_rewrites=None, scans_per_day=None,
        scan_quality="fast", rewrite_quality="quality",
        features=("pipeline_skill_gap_analytics", "sso"),
    ),
}

# The order the pricing page renders the consumer ladder in, and which
# card it marks. Explicit rather than relying on dict order, because
# which plan leads is a commercial decision, not an artefact of how the
# literal above happens to be written.
B2C_DISPLAY_ORDER: tuple[str, ...] = ("free", "boost", "pro", "pro_season")
RECOMMENDED_TIER_ID = "pro"


API_USAGE_PRICE_PER_SCAN_USD = (0.50, 2.00)  # (floor, ceiling) — negotiate within this band


def price_for(tier: Tier, currency: str) -> float:
    """The listed price of a pass in the given currency.

    No billing_cycle argument: a tier is a single fixed-length pass with
    exactly one price (see Tier's docstring), so there is no combination
    that can be unavailable and no None for callers to handle. One place
    knows how a currency maps to a field, so checkout and the pricing page
    cannot disagree about what a plan costs -- the kind of mismatch a
    customer notices and nobody else does.
    """
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(
            "Unsupported currency '%s'. Supported: %s." % (currency, ", ".join(SUPPORTED_CURRENCIES))
        )
    return getattr(tier, "price_%s" % currency.lower())


def entitlement_for(tier_id: str) -> Tier:
    return B2C_TIERS.get(tier_id) or B2B_TIERS[tier_id]
