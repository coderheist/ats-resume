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
    id: str
    name: str
    monthly_price_usd: float
    annual_price_usd: float | None
    # INR prices are listed explicitly rather than converted from USD at
    # run time. A live FX rate would make the displayed price move on its
    # own between the page load and the checkout, and a hard-coded rate
    # silently drifts away from reality. Local pricing is also a business
    # decision, not an arithmetic one: these are set at round local price
    # points, which is how software is actually priced in India, instead
    # of the ugly literal conversion of $15.
    #
    # TREAT THESE AS PLACEHOLDERS -- they were derived at roughly Rs 83
    # to the dollar and rounded; the business should set the real ones.
    monthly_price_inr: float
    annual_price_inr: float | None
    jd_match_scans_per_month: int | None  # None = unlimited
    voice_minutes_per_month: int | None  # None = unlimited, 0 = not included
    features: tuple[str, ...]


B2C_TIERS: dict[str, Tier] = {
    "free": Tier(
        id="free", name="Free", monthly_price_usd=0, annual_price_usd=None,
        monthly_price_inr=0, annual_price_inr=None,
        jd_match_scans_per_month=10, voice_minutes_per_month=0,
        features=("basic_ats_readiness_score", "json_resume_export"),
    ),
    "starter": Tier(
        id="starter", name="Starter", monthly_price_usd=15, annual_price_usd=108,
        monthly_price_inr=1249, annual_price_inr=8999,
        jd_match_scans_per_month=None, voice_minutes_per_month=0,
        features=("full_xai_breakdown", "jd_less_scoring", "cover_letter_draft"),
    ),
    "pro": Tier(
        id="pro", name="Pro", monthly_price_usd=29, annual_price_usd=216,
        monthly_price_inr=2399, annual_price_inr=17999,
        jd_match_scans_per_month=None, voice_minutes_per_month=60,
        features=("voice_editor", "unlimited_resume_versions"),
    ),
    "pro_plus": Tier(
        id="pro_plus", name="Pro+", monthly_price_usd=45, annual_price_usd=None,
        monthly_price_inr=3749, annual_price_inr=None,
        jd_match_scans_per_month=None, voice_minutes_per_month=None,
        features=("uncapped_voice_minutes", "multilanguage_stt", "jd_bias_audit_tool"),
    ),
}

B2B_TIERS: dict[str, Tier] = {
    "team": Tier(
        id="team", name="Team", monthly_price_usd=79, annual_price_usd=None,
        monthly_price_inr=6599, annual_price_inr=None,
        jd_match_scans_per_month=None, voice_minutes_per_month=None,
        features=("jd_bias_audit", "candidate_pool_ranking", "per_candidate_xai"),
    ),
    "business": Tier(
        id="business", name="Business", monthly_price_usd=149, annual_price_usd=None,
        monthly_price_inr=12499, annual_price_inr=None,
        jd_match_scans_per_month=None, voice_minutes_per_month=None,
        features=("pipeline_skill_gap_analytics", "validity_bias_audit_reporting", "sso"),
    ),
}

API_USAGE_PRICE_PER_SCAN_USD = (0.50, 2.00)  # (floor, ceiling) — negotiate within this band


def price_for(tier: Tier, billing_cycle: str, currency: str) -> float | None:
    """The listed price, or None when this tier does not offer that
    combination (e.g. Pro+ has no annual option).

    One place that knows how a (cycle, currency) pair maps to a field, so
    the checkout route and the pricing page cannot disagree about what a
    plan costs -- which is the kind of mismatch a customer notices and
    nobody else does.
    """
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(
            "Unsupported currency '%s'. Supported: %s." % (currency, ", ".join(SUPPORTED_CURRENCIES))
        )
    if billing_cycle not in ("monthly", "annual"):
        raise ValueError("billing_cycle must be 'monthly' or 'annual'.")
    return getattr(tier, "%s_price_%s" % (billing_cycle, currency.lower()))


def entitlement_for(tier_id: str) -> Tier:
    return B2C_TIERS.get(tier_id) or B2B_TIERS[tier_id]


def voice_minutes_remaining(tier_id: str, minutes_used_this_period: int) -> int | None:
    """None = unlimited. Used by the voice session endpoint to gate access."""
    tier = entitlement_for(tier_id)
    if tier.voice_minutes_per_month is None:
        return None
    return max(0, tier.voice_minutes_per_month - minutes_used_this_period)
