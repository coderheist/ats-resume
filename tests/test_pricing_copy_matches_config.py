"""
Guards the one duplicated fact in this codebase: the plan prices.

app/config.py is the source of truth -- it is what checkout actually
charges. But three marketing surfaces have to state prices in static HTML
that exists *before* any API call: the SoftwareApplication structured
data, llms.txt, and the prerendered pricing summary. A crawler or an AI
assistant reads the served markup, so "fetch it at runtime" is not
available to them, and a build-time mirror in frontend-react/src/lib/seo.js
is unavoidable.

A mirror can drift, and a pricing page that contradicts checkout is worse
than one that says nothing: Google treats structured data that disagrees
with the visible page as a violation, an assistant quoting a stale price
costs a sale, and a customer who sees one number and is charged another
files a chargeback. So the duplication is allowed but not left to
discipline -- this test parses the JavaScript and fails if any figure
disagrees.

Parsing JS from Python is admittedly crude. The alternatives were worse:
generating seo.js from config.py at build time adds a codegen step to a
frontend that otherwise has none, and serving prices from an endpoint
does not solve the problem, because the whole point is the numbers must
be in the HTML before JavaScript runs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.config import B2C_TIERS

SEO_JS = Path(__file__).resolve().parents[1] / "frontend-react" / "src" / "lib" / "seo.js"

# { id: "pro", name: "Pro", inr: 399, usd: 12.99, days: 30, scans: 100, rewrites: 100 },
_ENTRY = re.compile(
    r"\{\s*id:\s*\"(?P<id>[a-z_]+)\","
    r"\s*name:\s*\"(?P<name>[^\"]+)\","
    r"\s*inr:\s*(?P<inr>[\d.]+),"
    r"\s*usd:\s*(?P<usd>[\d.]+),"
    r"\s*days:\s*(?P<days>\d+),"
    r"\s*scans:\s*(?P<scans>\d+),"
    r"\s*rewrites:\s*(?P<rewrites>\d+)\s*\}"
)


def _parse_plans() -> dict[str, dict]:
    source = SEO_JS.read_text(encoding="utf-8")
    block = re.search(r"export const PLANS = \[(.*?)\];", source, re.DOTALL)
    assert block, "PLANS array not found in seo.js -- has it been renamed?"
    plans = {
        m.group("id"): {
            "name": m.group("name"),
            "inr": float(m.group("inr")),
            "usd": float(m.group("usd")),
            "days": int(m.group("days")),
            "scans": int(m.group("scans")),
            "rewrites": int(m.group("rewrites")),
        }
        for m in _ENTRY.finditer(block.group(1))
    }
    assert plans, "PLANS matched no entries -- the shape in seo.js has changed"
    return plans


@pytest.mark.skipif(not SEO_JS.exists(), reason="frontend not present in this checkout")
class TestPricingCopyMatchesConfig:
    def test_the_same_plans_exist_on_both_sides(self):
        assert set(_parse_plans()) == set(B2C_TIERS)

    @pytest.mark.parametrize("tier_id", sorted(B2C_TIERS))
    def test_every_number_agrees(self, tier_id):
        plan = _parse_plans().get(tier_id)
        assert plan is not None, f"{tier_id} is priced in config.py but missing from seo.js PLANS"
        tier = B2C_TIERS[tier_id]

        assert plan["name"] == tier.name, f"{tier_id}: display name"
        assert plan["inr"] == tier.price_inr, f"{tier_id}: INR price"
        assert plan["usd"] == tier.price_usd, f"{tier_id}: USD price"
        assert plan["days"] == tier.duration_days, f"{tier_id}: pass length"
        assert plan["scans"] == tier.jd_match_scans, f"{tier_id}: scan allowance"
        assert plan["rewrites"] == tier.ai_rewrites, f"{tier_id}: rewrite allowance"

    def test_the_free_plan_is_actually_free_on_both_sides(self):
        """Cheap to state, expensive to get wrong: a Free card that
        advertises a price is the one pricing bug users screenshot."""
        assert _parse_plans()["free"]["inr"] == 0
        assert B2C_TIERS["free"].price_inr == 0
        assert B2C_TIERS["free"].price_usd == 0
