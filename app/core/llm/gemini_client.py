"""
Gemini backend for the three switchable task types (CONVERSATIONAL_AGENT,
DEEP_REASONING, FAST_CLASSIFICATION) -- see router.py's "Multi-provider
switching" section for how LLM_PROVIDER=gemini gets you here instead of
claude_client.py. EXTRACTION_CROSSCHECK never comes through this module
(it's OSS-only, see oss_extraction_client.py).

Why this exists: Gemini has a genuinely usable free tier (rate-limited,
not a trial credit that expires), which makes it a reasonable way to build
and demo this product end-to-end before paying for Claude. The intent per
the blueprint is still to run this on Claude in production -- this client
just makes that an env-var flip later instead of a rewrite.

Response shape is deliberately normalized to match AnthropicClient's, i.e.
this returns the same {"id", "stop_reason", "content": [...], "usage": {
"input_tokens", "output_tokens", ...}} shape claude_client.py does, NOT
Gemini's native response shape. That's what lets MessageResult, and every
downstream parser written against the Anthropic content-block shape
(parse_narrative_batch_results, etc.), work unmodified regardless of which
provider actually answered the call.

Two real, non-cosmetic differences from Claude worth knowing before you
rely on this in production:

1. Prompt caching: Gemini has its own context-caching feature, but it's a
   different mechanism (an explicit cached-content resource you create and
   reference by name) from Anthropic's inline `cache_control` breakpoints
   -- prompt_cache.py's `cache_control` blocks have no meaning here and
   are flattened away below. Cost tracking in token_pricing.py therefore
   only computes plain input/output cost for Gemini calls, never a cache
   discount -- don't read a $0 cache_write_cost as "caching isn't
   helping," it means caching isn't wired for this provider yet.

2. Batch API: `create_message_batch` below is NOT Gemini's real batch
   endpoint (Gemini's is a separate async job you submit as a file, similar
   in spirit to OpenAI's Batch API, not the same call shape as Anthropic's
   Message Batches). It's a compatibility shim -- bounded-concurrency
   synchronous fan-out, same pattern as
   batch_resume_extraction.run_crosscheck_concurrently -- that exists so
   submit_classification_batch() / run_candidate_pool_narratives() keep
   working unmodified when LLM_PROVIDER=gemini. It does NOT carry
   Anthropic's unconditional 50% batch discount (there is no such thing to
   discount from here). If Gemini volume ever gets large enough that its
   real batch endpoint's discount matters, wire that for real instead of
   leaning on this shim indefinitely.

`create_message` below is implemented via app/core/llm/langchain_backend.py
(LangChain's `ChatGoogleGenerativeAI`) -- see that module's docstring for
why one shared LangChain-based implementation replaced the per-provider
request/response translation code (Anthropic content-blocks <-> Gemini's
`contents`/`parts` shape, a Gemini-specific finish_reason map) this file
used to carry directly. Everything else below -- the two real differences
from Claude, the batch shim, FakeGeminiClient -- is unchanged.

Requires `pip install langchain-google-genai` and GEMINI_API_KEY set in
the environment. Not exercised in this sandbox (no API key at build time,
no network egress to Google's API here) -- same "adapter written against
the real API shape, not invoked" pattern as claude_client.py.
FakeGeminiClient below lets everything downstream be tested without one.
"""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.llm.claude_client import BatchRequestSpec, MessageResult
from app.core.llm.router import Provider
from app.core.llm.token_pricing import calculate_cost


class GeminiClient:
    """Production client. Requires `pip install langchain-google-genai`
    and GEMINI_API_KEY set in the environment (or passed explicitly)."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
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
        from app.core.llm.langchain_backend import invoke

        return invoke(
            provider=Provider.GEMINI, model=model, system=system, messages=messages,
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
        raw = self.create_message(
            model=model, system=system, messages=messages, tools=tools, max_tokens=max_tokens,
        )
        cost = calculate_cost(model, raw.get("usage", {}))
        return MessageResult(raw=raw, cost=cost)

    # -- Batch compatibility shim -- see module docstring point 2 before
    # assuming this behaves like AnthropicClient.create_message_batch. --

    def create_message_batch(
        self, requests: list[BatchRequestSpec], *, max_in_flight: int = 10,
    ) -> dict[str, Any]:
        batch_id = f"gemini_batch_{uuid.uuid4().hex[:8]}"
        results: list[dict[str, Any]] = []

        def _one(req: BatchRequestSpec) -> dict[str, Any]:
            try:
                raw = self.create_message(
                    model=req.model, system=req.system, messages=req.messages,
                    tools=req.tools, max_tokens=req.max_tokens,
                )
                return {
                    "custom_id": req.custom_id,
                    "result": {"type": "succeeded", "message": raw},
                }
            except Exception as exc:  # noqa: BLE001 -- surfaced per-request, not raised
                return {
                    "custom_id": req.custom_id,
                    "result": {"type": "errored", "error": {"message": str(exc)}},
                }

        with ThreadPoolExecutor(max_workers=max_in_flight) as pool:
            results = list(pool.map(_one, requests))

        self._batches[batch_id] = {"results": results}
        succeeded = sum(1 for r in results if r["result"]["type"] == "succeeded")
        return {
            "id": batch_id,
            "processing_status": "ended",
            "request_counts": {"succeeded": succeeded, "errored": len(results) - succeeded},
        }

    def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        return {"id": batch_id, "processing_status": "ended"}

    def retrieve_batch_results(self, batch_id: str) -> list[dict[str, Any]]:
        return self._batches[batch_id]["results"]


class FakeGeminiClient:
    """Deterministic stand-in for GeminiClient, used by tests and local
    dev without an API key. Mirrors FakeAnthropicClient's contract so
    tests can parametrize over both."""

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
            "id": f"gemini_fake_{len(self.calls)}",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "[fake gemini response]"}],
            "usage": dict(self.next_usage),
        }

    def create_message_with_cost(self, **kwargs) -> MessageResult:
        raw = self.create_message(**kwargs)
        return MessageResult(raw=raw, cost=calculate_cost(kwargs["model"], raw["usage"]))

    def create_message_batch(self, requests: list[BatchRequestSpec]) -> dict[str, Any]:
        batch_id = f"gemini_batch_fake_{uuid.uuid4().hex[:8]}"
        self._batches[batch_id] = {"requests": requests}
        return {"id": batch_id, "processing_status": "ended", "request_counts": {"succeeded": len(requests)}}

    def get_batch_status(self, batch_id: str) -> dict[str, Any]:
        return {"id": batch_id, "processing_status": "ended"}

    def retrieve_batch_results(self, batch_id: str) -> list[dict[str, Any]]:
        return [
            {
                "custom_id": r.custom_id,
                "result": {
                    "type": "succeeded",
                    "message": {
                        "content": [{"type": "text", "text": "[fake gemini batch response]"}],
                        "usage": dict(self.next_usage),
                    },
                },
            }
            for r in self._batches[batch_id]["requests"]
        ]
