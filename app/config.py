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


@dataclass(frozen=True)
class Tier:
    id: str
    name: str
    monthly_price_usd: float
    annual_price_usd: float | None
    jd_match_scans_per_month: int | None  # None = unlimited
    voice_minutes_per_month: int | None  # None = unlimited, 0 = not included
    features: tuple[str, ...]


B2C_TIERS: dict[str, Tier] = {
    "free": Tier(
        id="free", name="Free", monthly_price_usd=0, annual_price_usd=None,
        jd_match_scans_per_month=3, voice_minutes_per_month=0,
        features=("basic_ats_readiness_score", "json_resume_export"),
    ),
    "starter": Tier(
        id="starter", name="Starter", monthly_price_usd=15, annual_price_usd=108,
        jd_match_scans_per_month=None, voice_minutes_per_month=0,
        features=("full_xai_breakdown", "jd_less_scoring", "cover_letter_draft"),
    ),
    "pro": Tier(
        id="pro", name="Pro", monthly_price_usd=29, annual_price_usd=216,
        jd_match_scans_per_month=None, voice_minutes_per_month=60,
        features=("voice_editor", "unlimited_resume_versions"),
    ),
    "pro_plus": Tier(
        id="pro_plus", name="Pro+", monthly_price_usd=45, annual_price_usd=None,
        jd_match_scans_per_month=None, voice_minutes_per_month=None,
        features=("uncapped_voice_minutes", "multilanguage_stt", "jd_bias_audit_tool"),
    ),
}

B2B_TIERS: dict[str, Tier] = {
    "team": Tier(
        id="team", name="Team", monthly_price_usd=79, annual_price_usd=None,
        jd_match_scans_per_month=None, voice_minutes_per_month=None,
        features=("jd_bias_audit", "candidate_pool_ranking", "per_candidate_xai"),
    ),
    "business": Tier(
        id="business", name="Business", monthly_price_usd=149, annual_price_usd=None,
        jd_match_scans_per_month=None, voice_minutes_per_month=None,
        features=("pipeline_skill_gap_analytics", "validity_bias_audit_reporting", "sso"),
    ),
}

API_USAGE_PRICE_PER_SCAN_USD = (0.50, 2.00)  # (floor, ceiling) — negotiate within this band


def entitlement_for(tier_id: str) -> Tier:
    return B2C_TIERS.get(tier_id) or B2B_TIERS[tier_id]


def voice_minutes_remaining(tier_id: str, minutes_used_this_period: int) -> int | None:
    """None = unlimited. Used by the voice session endpoint to gate access."""
    tier = entitlement_for(tier_id)
    if tier.voice_minutes_per_month is None:
        return None
    return max(0, tier.voice_minutes_per_month - minutes_used_this_period)
