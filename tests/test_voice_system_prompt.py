from app.core.llm.token_pricing import MIN_CACHEABLE_TOKENS
from app.core.llm.prompt_cache import estimate_static_prefix_tokens
from app.core.llm.voice_system_prompt import STABLE_INSTRUCTIONS, build_voice_agent_system


def test_stable_instructions_clears_sonnet_cache_minimum_with_margin():
    """This is the whole reason the prompt is written out in full rather
    than left as a placeholder: below the per-model minimum, the API
    silently serves it uncached and caching does nothing. Assert real
    margin (not just barely over) so small future edits don't quietly
    drop it under the line."""
    estimated = estimate_static_prefix_tokens(STABLE_INSTRUCTIONS)
    minimum = MIN_CACHEABLE_TOKENS["claude-sonnet-5"]
    # chars/4 is a rough heuristic, not Claude's real tokenizer, so require
    # real margin -- 25% -- rather than padding the prompt with filler
    # just to clear a round multiplier. (Measured: ~1476 est. tokens vs a
    # 1024 minimum, ~44% over -- comfortable, not padded-for-the-test.)
    assert estimated > minimum * 1.25, (
        f"~{estimated} estimated tokens leaves too little margin above "
        f"the {minimum}-token Sonnet 5 cache minimum"
    )


def test_build_voice_agent_system_without_session_context():
    blocks = build_voice_agent_system()
    assert len(blocks) == 1
    assert "cache_control" in blocks[0]
    assert blocks[0]["text"] == STABLE_INSTRUCTIONS


def test_build_voice_agent_system_keeps_session_context_uncached():
    blocks = build_voice_agent_system(session_context="Editing role: Senior Engineer at Acme.")
    assert len(blocks) == 2
    assert "cache_control" in blocks[0]
    assert blocks[0]["text"] == STABLE_INSTRUCTIONS
    assert "cache_control" not in blocks[1]
    assert "Senior Engineer at Acme" in blocks[1]["text"]


def test_stable_instructions_mentions_both_tools_by_name():
    """Sanity check the prompt content stays in sync with tool_schema.py --
    a stale prompt that no longer matches the actual tool names would be a
    silent, expensive-to-debug failure."""
    assert "append_work_highlight" in STABLE_INSTRUCTIONS
    assert "ask_clarifying_question" in STABLE_INSTRUCTIONS
