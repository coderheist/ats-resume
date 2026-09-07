"""
Shared LangChain-based implementation of `create_message` for all three
closed providers (Claude/Gemini/Groq) -- see router.py's "Multi-provider
LLM switching" for the provider-selection story this plugs into.

Why this exists as ONE shared module instead of three per-provider
translation layers (which is what claude_client.py/gemini_client.py/
groq_client.py's `create_message` used to hand-roll separately): LangChain
gives the same three things across all three vendors --
  - a shared message vocabulary (SystemMessage/HumanMessage/AIMessage)
    instead of each vendor's own request shape,
  - a shared response shape (AIMessage.content, AIMessage.usage_metadata
    with input_tokens/output_tokens/total_tokens keys -- identical across
    ChatAnthropic/ChatGoogleGenerativeAI/ChatGroq, verified by inspecting
    all three installed packages, not assumed),
  - a shared tool-calling interface (.bind_tools()),
so the ~150 lines of hand-written per-provider request/response
translation this codebase carried before (Anthropic content-blocks <->
Gemini `contents`/`parts`, Anthropic content-blocks <-> OpenAI-shaped
messages, three separate finish_reason maps) collapse into the one
`invoke()` function below.

claude_client.py / gemini_client.py / groq_client.py still each own their
file -- cost tracking, the Fake* test doubles, and (for Claude only)
the real Batch API all still live there, since LangChain has no
equivalent to Anthropic's Batch API and none of that needed to change.
Only `create_message` on all three became a thin call into `invoke()`.

This still returns the SAME Anthropic-content-block-shaped dict every
caller in this codebase already expects ({"id", "stop_reason", "content":
[{"type": "text", "text": ...}], "usage": {"input_tokens", ...}}) -- so
client_factory.py, resume_extraction.py, and every existing test written
against that shape needed zero changes to pick this up.

Requires the LangChain integration package matching whichever provider
is active (`langchain-anthropic`, `langchain-google-genai`, or
`langchain-groq`) plus `langchain-core` -- see requirements.txt, same
"only install the one matching your LLM_PROVIDER" guidance as before.
Imports are deferred into `_chat_model_for()` so importing this module
(or any client module) never fails just because a package isn't
installed -- same lazy-import discipline the rest of app/core/llm follows.

Not exercised against a live endpoint in this sandbox (no network egress
to Anthropic/Google/Groq's APIs here, and no real API keys) -- written
against each package's real, current (Aug 2026) constructor signature and
message/response shape, verified by inspecting the installed packages
directly rather than assumed from training data. The plumbing itself
(message conversion, response normalization, tool translation, error
handling) is exercised end-to-end in tests/test_langchain_backend.py
against LangChain's own FakeListChatModel, so that part is genuinely
covered even without live credentials -- but the real per-vendor wire
behavior should be smoke-tested with a real key before depending on it
in production, the same caveat every provider client in this codebase
already carries.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.core.llm.router import Provider

# Anthropic/Gemini/Groq's finish-reason vocabularies differ, and none of
# this codebase's current call sites branch on stop_reason (it exists for
# future use / debugging) -- so this maps the common values through
# LangChain's passthrough response_metadata and defaults to "end_turn"
# rather than chasing three more finish-reason vocabularies for a field
# nothing reads yet.
_STOP_REASON_METADATA_KEYS = ("stop_reason", "finish_reason")
_STOP_REASON_MAP = {
    "end_turn": "end_turn", "stop": "end_turn", "STOP": "end_turn",
    "max_tokens": "max_tokens", "length": "max_tokens", "MAX_TOKENS": "max_tokens",
    "tool_use": "tool_use", "tool_calls": "tool_use", "TOOL_CALLS": "tool_use",
}


def _chat_model_for(provider: Provider, model: str, api_key: str | None, max_tokens: int):
    """Deferred imports so a missing package only breaks the provider
    that's actually being used, not import of this module (or any client
    module importing it) generally."""
    if provider is Provider.CLAUDE:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, api_key=api_key, max_tokens=max_tokens)
    if provider is Provider.GEMINI:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, max_output_tokens=max_tokens)
    if provider is Provider.GROQ:
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, api_key=api_key, max_tokens=max_tokens)
    raise ValueError(f"No LangChain chat model wired up for provider {provider!r}")


def _flatten_system(system: str | list[dict[str, Any]] | None) -> str | None:
    """Anthropic-shaped `system` (a string, or a list of content blocks
    that may carry a `cache_control` breakpoint) -> a single plain
    string. None of the three LangChain integrations expose Anthropic's
    inline cache_control breakpoint through a portable cross-vendor API,
    so -- same as this codebase's pre-LangChain Gemini/Groq clients -- any
    breakpoint is dropped here. Only claude_client.py's own Batch API path
    (prompt_cache.py, not this function) actually applies caching."""
    if system is None:
        return None
    if isinstance(system, str):
        return system
    return "\n\n".join(block.get("text", "") for block in system)


def _to_langchain_messages(
    system: str | list[dict[str, Any]] | None, messages: list[dict[str, Any]],
) -> list[Any]:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    lc_messages: list[Any] = []
    system_text = _flatten_system(system)
    if system_text:
        lc_messages.append(SystemMessage(content=system_text))
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = "\n\n".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        role = msg.get("role", "user")
        lc_messages.append(AIMessage(content=content) if role == "assistant" else HumanMessage(content=content))
    return lc_messages


def _to_langchain_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Anthropic tool defs ({"name", "description", "input_schema"}) ->
    the OpenAI-function-style shape `.bind_tools()` accepts uniformly
    across LangChain's chat models (each integration normalizes it to the
    vendor's own wire format internally). Not exercised by any current
    call site in this codebase -- see module docstring."""
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _text_from_content(content: Any) -> str:
    """AIMessage.content is normally a plain string, but some providers
    return a list of content blocks (e.g. text + tool_use mixed) --
    handled defensively even though no current call site triggers it."""
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return content or ""


def _stop_reason_from(ai_message: Any) -> str:
    metadata = getattr(ai_message, "response_metadata", None) or {}
    for key in _STOP_REASON_METADATA_KEYS:
        if key in metadata:
            return _STOP_REASON_MAP.get(metadata[key], "end_turn")
    return "end_turn"


def invoke(
    *,
    provider: Provider,
    model: str,
    system: str | list[dict[str, Any]],
    messages: list[dict[str, Any]],
    api_key: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """The one call every provider client's create_message() makes.
    Returns the same Anthropic-content-block-shaped dict this codebase
    has always passed around -- see module docstring."""
    chat_model = _chat_model_for(provider, model, api_key, max_tokens)
    lc_tools = _to_langchain_tools(tools)
    if lc_tools:
        chat_model = chat_model.bind_tools(lc_tools)

    ai_message = chat_model.invoke(_to_langchain_messages(system, messages))

    usage = getattr(ai_message, "usage_metadata", None) or {}
    return {
        "id": getattr(ai_message, "id", None) or f"{provider.value}_{uuid.uuid4().hex[:12]}",
        "stop_reason": _stop_reason_from(ai_message),
        "content": [{"type": "text", "text": _text_from_content(ai_message.content)}],
        "usage": {
            "input_tokens": usage.get("input_tokens", 0) or 0,
            "output_tokens": usage.get("output_tokens", 0) or 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }
