from app.core.llm.prompt_cache import (
    build_system_blocks,
    cache_last_tool,
    cached_text_block,
    estimate_static_prefix_tokens,
)


def test_stable_only_prompt_has_breakpoint_on_the_one_block():
    blocks = build_system_blocks(stable_instructions="You are a helpful assistant.")
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"] == "You are a helpful assistant."


def test_volatile_suffix_never_gets_a_breakpoint():
    """The core rule this module exists to enforce: content that changes
    every request must never carry cache_control, or every call becomes a
    fresh (expensive) cache write that's never read back."""
    blocks = build_system_blocks(
        stable_instructions="Static instructions here.",
        volatile_context="Today's session id is abc-123.",
    )
    assert len(blocks) == 2
    assert "cache_control" in blocks[0]
    assert "cache_control" not in blocks[1]
    assert blocks[1]["text"] == "Today's session id is abc-123."


def test_no_volatile_context_produces_single_block():
    blocks = build_system_blocks(stable_instructions="x", volatile_context=None)
    assert len(blocks) == 1


def test_1h_ttl_included_when_requested():
    block = cached_text_block("stable content", ttl="1h")
    assert block["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_5m_ttl_omits_explicit_ttl_key():
    block = cached_text_block("stable content", ttl="5m")
    assert block["cache_control"] == {"type": "ephemeral"}
    assert "ttl" not in block["cache_control"]


def test_cache_last_tool_only_marks_the_final_tool():
    tools = [
        {"name": "tool_a", "description": "first"},
        {"name": "tool_b", "description": "second"},
        {"name": "tool_c", "description": "third"},
    ]
    marked = cache_last_tool(tools)
    assert "cache_control" not in marked[0]
    assert "cache_control" not in marked[1]
    assert marked[2]["cache_control"] == {"type": "ephemeral"}
    # original list must be untouched (no accidental mutation)
    assert "cache_control" not in tools[2]


def test_cache_last_tool_handles_empty_list():
    assert cache_last_tool([]) == []


def test_estimate_static_prefix_tokens_scales_with_length():
    short = estimate_static_prefix_tokens("hello")
    long = estimate_static_prefix_tokens("hello " * 1000)
    assert long > short
    assert short >= 1  # never zero, even for tiny strings
