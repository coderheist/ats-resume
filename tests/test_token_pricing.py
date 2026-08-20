from app.core.llm.token_pricing import BATCH_DISCOUNT_MULTIPLIER, calculate_cost


def test_pure_output_no_cache():
    """A response with no cached content at all -- input_cost + output_cost
    should equal a hand-computed value at Sonnet 5's listed rates."""
    usage = {"input_tokens": 1000, "output_tokens": 500}
    cost = calculate_cost("claude-sonnet-5", usage)
    assert cost.input_cost == round(1000 / 1_000_000 * 2.00, 6)
    assert cost.output_cost == round(500 / 1_000_000 * 10.00, 6)
    assert cost.cache_write_cost == 0
    assert cost.cache_read_cost == 0
    assert cost.total_cost == cost.input_cost + cost.output_cost


def test_cache_read_is_cheaper_than_uncached_equivalent():
    """The whole point of caching: reading 100k cached tokens should cost
    far less than treating them as fresh input tokens would."""
    usage = {
        "input_tokens": 50,
        "output_tokens": 200,
        "cache_read_input_tokens": 100_000,
        "cache_creation_input_tokens": 0,
    }
    cost = calculate_cost("claude-sonnet-5", usage)
    # cache_read rate (0.20/MTok) is 1/10th of base input rate (2.00/MTok)
    assert cost.cache_read_cost == round(100_000 / 1_000_000 * 0.20, 6)
    assert cost.savings_pct > 80  # reading beats paying full input price


def test_savings_reported_correctly_on_full_cache_hit():
    """If everything came from cache reads, the equivalent-uncached cost
    should be roughly 10x the actual cache-read cost (0.1x multiplier)."""
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1_000_000}
    cost = calculate_cost("claude-sonnet-5", usage)
    assert cost.total_cost == 0.20  # 1M tokens * $0.20/MTok cache-read rate
    assert cost.uncached_equivalent_cost == 2.00  # same 1M tokens at full input rate
    assert cost.savings_pct == 90.0


def test_cache_write_costs_more_than_base_input():
    """A 5-minute cache write should cost 1.25x the base input rate --
    this is the one-time cost that later reads pay off."""
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 1_000_000}
    cost = calculate_cost("claude-sonnet-5", usage)
    assert cost.cache_write_cost == 2.50  # 1.25 * $2.00 base input rate


def test_1h_ttl_breakdown_used_when_present():
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 1_000_000},
    }
    cost = calculate_cost("claude-sonnet-5", usage)
    assert cost.cache_write_cost == 4.00  # 2x base input rate for 1h TTL


def test_batch_flag_applies_50_percent_discount_to_every_component():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    normal = calculate_cost("claude-haiku-4-5-20251001", usage, batch=False)
    batched = calculate_cost("claude-haiku-4-5-20251001", usage, batch=True)
    assert batched.total_cost == round(normal.total_cost * BATCH_DISCOUNT_MULTIPLIER, 6)


def test_unknown_model_raises():
    import pytest
    with pytest.raises(ValueError):
        calculate_cost("not-a-real-model", {"input_tokens": 1})


def test_gemini_and_groq_models_have_rates_and_cost_less_than_claude():
    """Every model router.py can route a switchable task to must have a
    rate entry -- this is what would raise ValueError at call time in
    gemini_client.py / groq_client.py otherwise. Also a sanity check on
    the actual reason to switch: these should be meaningfully cheaper
    than the Claude models they stand in for."""
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}

    claude_agent = calculate_cost("claude-sonnet-5", usage)
    gemini_agent = calculate_cost("gemini-3.6-flash", usage)
    groq_agent = calculate_cost("openai/gpt-oss-120b", usage)
    assert gemini_agent.total_cost < claude_agent.total_cost
    assert groq_agent.total_cost < claude_agent.total_cost

    claude_classification = calculate_cost("claude-haiku-4-5-20251001", usage)
    gemini_classification = calculate_cost("gemini-3.5-flash-lite", usage)
    groq_classification = calculate_cost("openai/gpt-oss-20b", usage)
    assert gemini_classification.total_cost < claude_classification.total_cost
    assert groq_classification.total_cost < claude_classification.total_cost
