"""
LLM API token pricing + cost calculation -- Claude, Gemini, and Groq.

This is the *upstream* cost of calling a model API (dollars per million
tokens) -- not to be confused with app/config.py, which defines what this
product charges *its own* subscribers.

Pricing changes over time and varies by model, so -- same rule as
router.py -- nothing outside this file should hard-code a price. When a
vendor ships new rates, this is the only table that needs an edit.

Sources (snapshot: August 2026 -- verify against these before relying on
this for real billing/forecasting, all three vendors change rates):
  - Claude: https://platform.claude.com/docs/en/about-claude/pricing and
    https://platform.claude.com/docs/en/build-with-claude/prompt-caching
  - Gemini: https://ai.google.dev/gemini-api/docs/pricing
  - Groq:   https://groq.com/pricing

Cache fields (cache_write_5m/1h, cache_read) are only ever non-zero in a
`usage` dict for Claude -- claude_client.py is the only client that
populates cache_creation_input_tokens / cache_read_input_tokens, because
it's the only one that actually sends `cache_control` breakpoints
(prompt_cache.py). gemini_client.py and groq_client.py always report 0 for
those fields (see their module docstrings on why: different caching
mechanism for Gemini, no wired equivalent for Groq), so the cache rates
below for those two providers are placeholders (set equal to the input
rate) that this codebase never actually multiplies by a nonzero token
count today -- not a claim that Gemini/Groq caching is priced 1:1 with
base input.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRates:
    """All rates in USD per million tokens (MTok)."""
    input: float
    output: float
    cache_write_5m: float  # 1.25x input, per Anthropic's standard multiplier
    cache_write_1h: float  # 2x input
    cache_read: float      # 0.1x input -- a 90% discount vs. base input


# Current as of August 2026. Claude Sonnet 5 has a scheduled price change on
# 2026-09-01 (see PRICING docs) -- update SONNET_5 below after that date.
MODEL_RATES: dict[str, ModelRates] = {
    "claude-sonnet-5": ModelRates(
        input=2.00, output=10.00, cache_write_5m=2.50, cache_write_1h=4.00, cache_read=0.20,
    ),
    "claude-opus-4-8": ModelRates(
        input=5.00, output=25.00, cache_write_5m=6.25, cache_write_1h=10.00, cache_read=0.50,
    ),
    "claude-haiku-4-5-20251001": ModelRates(
        input=1.00, output=5.00, cache_write_5m=1.25, cache_write_1h=2.00, cache_read=0.10,
    ),
    # -- Gemini (ai.google.dev/gemini-api/docs/pricing, snapshot Aug 2026) --
    # Standard tier, prompts <=200K tokens (gemini-3.1-pro rises to $4/$18
    # above that threshold -- not modeled here, see the module docstring
    # on cache-field placeholders for the same "only exercised if used"
    # caveat applied to the long-context tier: this codebase's requests
    # are short enough in practice that it isn't wired either).
    "gemini-3.6-flash": ModelRates(
        input=1.50, output=7.50, cache_write_5m=1.50, cache_write_1h=1.50, cache_read=0.15,
    ),
    "gemini-3.1-pro": ModelRates(
        input=2.00, output=12.00, cache_write_5m=2.00, cache_write_1h=2.00, cache_read=0.20,
    ),
    "gemini-3.5-flash-lite": ModelRates(
        input=0.30, output=2.50, cache_write_5m=0.30, cache_write_1h=0.30, cache_read=0.03,
    ),
    # -- Groq (groq.com/pricing, snapshot Aug 2026) -- no separate
    # cache-write tier is published; cache_write set equal to input as a
    # placeholder per the module docstring, cache_read reflects Groq's
    # published ~50% automatic-prefix-caching discount on GPT-OSS models
    # where it applies (not guaranteed the way Claude's cache_read is).
    "openai/gpt-oss-120b": ModelRates(
        input=0.15, output=0.60, cache_write_5m=0.15, cache_write_1h=0.15, cache_read=0.075,
    ),
    "openai/gpt-oss-20b": ModelRates(
        input=0.075, output=0.30, cache_write_5m=0.075, cache_write_1h=0.075, cache_read=0.0375,
    ),
    "qwen/qwen3.6-27b": ModelRates(
        input=0.60, output=3.00, cache_write_5m=0.60, cache_write_1h=0.60, cache_read=0.60,
    ),
}

# Batch API: an unconditional 50% discount on both input and output tokens
# (all rate categories above), stacks with prompt caching. See
# app/core/llm/batch_narratives.py for where this applies in this codebase.
BATCH_DISCOUNT_MULTIPLIER = 0.5

# A model must have at least this many tokens in the cacheable prefix for
# caching to take effect at all -- shorter prefixes are silently processed
# uncached (no error). Sonnet/Opus: 1024. Haiku 4.5: 4096.
MIN_CACHEABLE_TOKENS: dict[str, int] = {
    "claude-sonnet-5": 1024,
    "claude-opus-4-8": 1024,
    "claude-haiku-4-5-20251001": 4096,
}


@dataclass
class CostBreakdown:
    model: str
    input_cost: float
    cache_write_cost: float
    cache_read_cost: float
    output_cost: float
    total_cost: float
    # What the same call would have cost with no caching at all -- lets
    # callers report "$X saved" / "N% off" rather than just a total.
    uncached_equivalent_cost: float

    @property
    def savings_usd(self) -> float:
        return round(self.uncached_equivalent_cost - self.total_cost, 6)

    @property
    def savings_pct(self) -> float:
        if self.uncached_equivalent_cost == 0:
            return 0.0
        return round(100 * self.savings_usd / self.uncached_equivalent_cost, 1)


def calculate_cost(
    model: str,
    usage: dict,
    *,
    batch: bool = False,
) -> CostBreakdown:
    """
    Compute actual dollar cost from an Anthropic API `usage` object.

    `usage` is expected to have the shape the Messages API returns:
      {
        "input_tokens": int,               # tokens after the last cache breakpoint
        "output_tokens": int,
        "cache_creation_input_tokens": int,  # optional, 0 if absent
        "cache_read_input_tokens": int,      # optional, 0 if absent
        "cache_creation": {                  # optional, only present when mixing TTLs
          "ephemeral_5m_input_tokens": int,
          "ephemeral_1h_input_tokens": int,
        },
      }

    Total input tokens = input_tokens + cache_creation_input_tokens +
    cache_read_input_tokens (see prompt caching docs, "Understanding the
    token breakdown").
    """
    if model not in MODEL_RATES:
        raise ValueError(f"Unknown model '{model}' -- add it to MODEL_RATES first.")
    rates = MODEL_RATES[model]

    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read_tokens = usage.get("cache_read_input_tokens", 0)

    creation_detail = usage.get("cache_creation") or {}
    write_5m_tokens = creation_detail.get("ephemeral_5m_input_tokens")
    write_1h_tokens = creation_detail.get("ephemeral_1h_input_tokens")
    if write_5m_tokens is None and write_1h_tokens is None:
        # No TTL breakdown given -- assume everything written was 5-minute
        # TTL, which is the default and the common case.
        write_5m_tokens = usage.get("cache_creation_input_tokens", 0)
        write_1h_tokens = 0

    discount = BATCH_DISCOUNT_MULTIPLIER if batch else 1.0

    input_cost = (input_tokens / 1_000_000) * rates.input * discount
    cache_write_cost = (
        (write_5m_tokens / 1_000_000) * rates.cache_write_5m
        + (write_1h_tokens / 1_000_000) * rates.cache_write_1h
    ) * discount
    cache_read_cost = (cache_read_tokens / 1_000_000) * rates.cache_read * discount
    output_cost = (output_tokens / 1_000_000) * rates.output * discount

    total_cost = input_cost + cache_write_cost + cache_read_cost + output_cost

    # Equivalent cost if none of this had been cached: every token that was
    # a cache read or cache write would instead have been a plain base-input
    # token, at the same batch/non-batch rate.
    total_prefix_tokens = input_tokens + cache_read_tokens + write_5m_tokens + write_1h_tokens
    uncached_equivalent_cost = (
        (total_prefix_tokens / 1_000_000) * rates.input * discount + output_cost
    )

    return CostBreakdown(
        model=model,
        input_cost=round(input_cost, 6),
        cache_write_cost=round(cache_write_cost, 6),
        cache_read_cost=round(cache_read_cost, 6),
        output_cost=round(output_cost, 6),
        total_cost=round(total_cost, 6),
        uncached_equivalent_cost=round(uncached_equivalent_cost, 6),
    )
