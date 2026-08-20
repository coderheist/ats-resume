"""
Prompt-cache breakpoint construction (blueprint Section 4.3 cost controls).

The single most common way to implement Claude prompt caching *wrong* is to
put the `cache_control` breakpoint on the last block in the request --
which, in a typical agent call, is the part that changes every time (the
user's latest message, a timestamp, per-request context). That writes a
fresh cache entry on every single call and never reads one back. See
"Common mistake: Breakpoint on content that changes every request" in
https://platform.claude.com/docs/en/build-with-claude/prompt-caching

The rule this module encodes: the breakpoint goes on the last block whose
content is byte-identical across the calls you want to share a cache --
i.e. the end of the STABLE prefix, never on the VARYING suffix.

Everything here is pure data transformation (no network calls), so it's
fully unit-testable without an API key -- see tests/test_prompt_cache.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TTL = Literal["5m", "1h"]

# Max explicit cache_control breakpoints per request (a hard API limit --
# a 5th breakpoint is a 400 error, not a soft cap).
MAX_EXPLICIT_BREAKPOINTS = 4


def _cache_control(ttl: TTL) -> dict:
    block = {"type": "ephemeral"}
    if ttl == "1h":
        block["ttl"] = "1h"
    return block


def cached_text_block(text: str, ttl: TTL = "5m") -> dict:
    """A single system/message content block with a cache breakpoint on it."""
    return {"type": "text", "text": text, "cache_control": _cache_control(ttl)}


def plain_text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def build_system_blocks(
    *,
    stable_instructions: str,
    volatile_context: str | None = None,
    ttl: TTL = "5m",
) -> list[dict]:
    """
    Build a `system` content-block list with the cache breakpoint placed
    correctly: on the end of `stable_instructions` (identical across every
    call this session/deployment makes), never on `volatile_context`
    (per-request data -- e.g. "today's date is..." or a session id).

    If there's no volatile context, the stable block is simply the last
    block and gets the breakpoint -- automatic caching would do the same
    thing here, but being explicit means adding a volatile suffix later
    can't silently move the breakpoint onto the wrong block.
    """
    blocks = [cached_text_block(stable_instructions, ttl=ttl)]
    if volatile_context:
        blocks.append(plain_text_block(volatile_context))
    return blocks


def cache_last_tool(tools: list[dict], ttl: TTL = "5m") -> list[dict]:
    """
    Tool definitions are typically the most stable thing in a request --
    they change only on deploys, not per-conversation -- so they're prime
    caching material. Per the docs, cache prefixes are built in the order
    tools -> system -> messages, so marking the *last* tool definition
    caches the entire tool array as one prefix.
    """
    if not tools:
        return tools
    *rest, last = tools
    return [*rest, {**last, "cache_control": _cache_control(ttl)}]


@dataclass
class TurnCacheState:
    """
    Tracks the cache breakpoint for automatic caching across a growing
    multi-turn conversation (the voice-editing session). Per the docs, a
    top-level `cache_control` on the request auto-advances the breakpoint
    to the last cacheable block each turn -- this class just documents/
    enforces that contract at the call site so agent_loop.py doesn't need
    to reason about it.
    """
    ttl: TTL = "5m"

    def top_level_cache_control(self) -> dict:
        return _cache_control(self.ttl)


def estimate_static_prefix_tokens(text: str) -> int:
    """
    Rough token estimate (chars / 4, the standard rule-of-thumb for English
    prose) used only to warn when a "cacheable" prompt is actually too
    short to ever be cached -- see MIN_CACHEABLE_TOKENS in token_pricing.py.
    Not a substitute for a real tokenizer; use the API's `usage` fields
    (cache_creation_input_tokens / cache_read_input_tokens) for ground
    truth after a live call.
    """
    return max(1, len(text) // 4)
