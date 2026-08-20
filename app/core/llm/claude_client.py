"""
Thin wrapper around the Anthropic API for the conversational voice-editing
agent (blueprint Section 4.3), plus the Message Batches API for
non-real-time bulk work (blueprint Sections 4.1 and 6 -- bulk resume
ingestion, candidate-pool ranking).

`create_message` is implemented via app/core/llm/langchain_backend.py
(LangChain's `ChatAnthropic`) -- see that module's docstring for why one
shared LangChain-based implementation replaced this file's own
Anthropic-SDK call (and the equivalent hand-rolled translation code that
used to live in gemini_client.py/groq_client.py). The Batch API below is
NOT part of that -- LangChain has no equivalent to Anthropic's actual
async Batch endpoint (50% off, stacks with caching), so this still talks
to the raw `anthropic` SDK directly for create_message_batch/
get_batch_status/retrieve_batch_results, same as before.

Not exercised against a live endpoint in this sandbox (no ANTHROPIC_API_KEY
or network egress to Anthropic's API here) -- this is the real call shape
to wire up in deployment. Everything downstream (agent_loop.py,
batch_resume_extraction.py, batch_candidate_narratives.py) is written
against the `LLMClient` interface so it's testable with a fake client,
same pattern as before.

Cost-optimization techniques wired in here:
  - Prompt caching (prompt_cache.py): explicit cache_control breakpoints
    on stable system instructions and tool definitions (Batch API path
    only -- see langchain_backend.py's docstring on why the synchronous
    create_message path doesn't carry this through LangChain).
  - Cost tracking (token_pricing.py): every response's `usage` field is
    turned into an actual dollar breakdown, so cache effectiveness is
    visible, not just assumed.
  - Batch API: create_message_batch()/retrieve_batch_results() for
    workloads that don't need a synchronous response -- 50% off, stacks
    with caching.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.llm.router import Provider, TaskType, route
from app.core.llm.token_pricing import CostBreakdown, calculate_cost


class LLMClient(Protocol):
    def create_message(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        ...


@dataclass
class MessageResult:
    """A Messages API response plus its computed cost, so callers never
    have to re-derive pricing logic at the call site."""
    raw: dict[str, Any]
    cost: CostBreakdown

    @property
    def stop_reason(self) -> str | None:
        return self.raw.get("stop_reason")

    @property
    def content(self) -> list[dict[str, Any]]:
        return self.raw.get("content", [])


@dataclass
class BatchRequestSpec:
    """One request within a Message Batch. `custom_id` is how you match
    this request back to its result -- use something you can join back to
    your own record (a resume id, a candidate id), not a random uuid, so
    retrieve_batch_results() output is directly usable."""
    custom_id: str
    model: str
    system: str | list[dict[str, Any]]
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    max_tokens: int = 1024


class AnthropicClient:
    """Production client. Requires `pip install langchain-anthropic` (for
    create_message) and `pip install anthropic` (for the Batch API methods
    below, which don't go through LangChain -- see module docstring) with
    ANTHROPIC_API_KEY set in the environment."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def _sdk_client(self):
        import anthropic  # deferred import: not a hard dependency of tests
        return anthropic.Anthropic(api_key=self._api_key)

    def create_message(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        from app.core.llm.langchain_backend import invoke

        return invoke(
            provider=Provider.CLAUDE, model=model, system=system, messages=messages,
            api_key=self._api_key, tools=tools, max_tokens=max_tokens,
        )

    def create_message_with_cost(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> MessageResult:
        """Same call as create_message, but also computes real dollar cost
        (including cache savings) from the response's usage field. Prefer
        this over the bare create_message when you want to log/monitor
        spend, which is the common case."""
        raw = self.create_message(
            model=model, system=system, messages=messages, tools=tools, max_tokens=max_tokens,
        )
        cost = calculate_cost(model, raw.get("usage", {}))
        return MessageResult(raw=raw, cost=cost)

    # -- Batch API -----------------------------------------------------
    #
    # For non-real-time workloads: a backlog of resumes uploaded to be
    # parsed and stored (not read while the user waits), or scoring a
    # whole candidate pool against one JD for a recruiter dashboard. Both
    # are unconditional 50%-off vs. a synchronous call, and that discount
    # stacks with prompt caching (see BATCH_DISCOUNT_MULTIPLIER in
    # token_pricing.py). Turnaround is asynchronous, typically well under
    # 24 hours -- never use this for anything a user is actively waiting
    # on mid-conversation.

    def create_message_batch(self, requests: list[BatchRequestSpec]) -> dict[str, Any]:
        """Submits a batch job. Returns the batch object (id, status,
        etc.) -- results aren't ready synchronously; poll or retrieve
        later with retrieve_batch_results()."""
        client = self._sdk_client()
        batch = client.messages.batches.create(
            requests=[
                {
                    "custom_id": r.custom_id,
                    "params": {
                        "model": r.model,
                        "max_tokens": r.max_tokens,
                        "system": r.system,
                        "messages": r.messages,
                        "tools": r.tools or [],
                    },
                }
                for r in requests
            ]
        )
        return batch.model_dump()

    def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        client = self._sdk_client()
        return client.messages.batches.retrieve(batch_id).model_dump()

    def retrieve_batch_results(self, batch_id: str) -> list[dict[str, Any]]:
        """Streams and collects per-request results once
        get_batch_status(batch_id)["processing_status"] == "ended". Each
        result includes `custom_id` so callers can join it back to
        whatever the request represented (a resume, a candidate)."""
        client = self._sdk_client()
        results = []
        for entry in client.messages.batches.results(batch_id):
            results.append(entry.model_dump())
        return results


class FakeAnthropicClient:
    """
    Deterministic stand-in for AnthropicClient, used by tests and local
    dev without an API key. Mirrors the real usage-field shape (including
    cache_creation_input_tokens / cache_read_input_tokens) so cost
    calculation logic can be exercised end-to-end without network access.

    Set `next_usage` between calls to simulate a cache miss on the first
    call and a cache hit on the second, etc.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.next_usage: dict[str, Any] = {
            "input_tokens": 50,
            "output_tokens": 120,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        self._batches: dict[str, dict[str, Any]] = {}

    def create_message(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        self.calls.append({"model": model, "system": system, "messages": messages, "tools": tools})
        return {
            "id": f"msg_fake_{len(self.calls)}",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "[fake response]"}],
            "usage": dict(self.next_usage),
        }

    def create_message_with_cost(self, **kwargs) -> MessageResult:
        raw = self.create_message(**kwargs)
        return MessageResult(raw=raw, cost=calculate_cost(kwargs["model"], raw["usage"]))

    def create_message_batch(self, requests: list[BatchRequestSpec]) -> dict[str, Any]:
        batch_id = f"batch_fake_{uuid.uuid4().hex[:8]}"
        self._batches[batch_id] = {
            "id": batch_id,
            "processing_status": "ended",
            "requests": requests,
        }
        return {"id": batch_id, "processing_status": "ended", "request_counts": {"succeeded": len(requests)}}

    def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        return {"id": batch_id, "processing_status": self._batches[batch_id]["processing_status"]}

    def retrieve_batch_results(self, batch_id: str) -> list[dict[str, Any]]:
        results = []
        for r in self._batches[batch_id]["requests"]:
            results.append({
                "custom_id": r.custom_id,
                "result": {
                    "type": "succeeded",
                    "message": {
                        "content": [{"type": "text", "text": "[fake batch response]"}],
                        "usage": dict(self.next_usage),
                    },
                },
            })
        return results


def get_client_for(task: TaskType) -> tuple[LLMClient, str]:
    """Returns (client, model_id) for a given task type, always on Claude.

    This is kept for direct/explicit Anthropic access, but most call sites
    should prefer app/core/llm/client_factory.py's get_client_for(), which
    is provider-aware (respects LLM_PROVIDER -- claude/gemini/groq) and
    falls back to Claude by default, same as this one does unconditionally.
    """
    return AnthropicClient(), route(task)
