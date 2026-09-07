"""
Groq backend for the three switchable task types (CONVERSATIONAL_AGENT,
DEEP_REASONING, FAST_CLASSIFICATION) -- see router.py's "Multi-provider
switching" section for how LLM_PROVIDER=groq gets you here instead of
claude_client.py. EXTRACTION_CROSSCHECK never comes through this module
either -- it's OSS-only (oss_extraction_client.py), though notably that
adapter can *also* point at Groq (it's one of the OpenAI-compatible hosts
listed in its own docstring) if you want the crosscheck pass on Groq too;
that's a separate, independent switch from this one.

Why this exists: Groq's free tier plus very low paid per-token rates on
open-weight models make it the cheapest way to get this whole pipeline
running end-to-end before Claude is affordable, and Groq's inference is
fast enough that the synchronous voice-agent path stays responsive even
without production infra. The intent per the blueprint is still Claude in
production -- this client is what makes that an env-var flip later.

Groq's API is OpenAI-compatible (`/openai/v1/chat/completions`), so this
is structurally the same adapter shape as oss_extraction_client.py, just
translating request/response into the Anthropic-shaped dict this
codebase's other callers already expect (MessageResult, the batch-result
parsers) -- see gemini_client.py's docstring for the same design choice
and its rationale.

Two real, non-cosmetic differences from Claude worth knowing before you
rely on this in production:

1. Prompt caching: Groq does automatic prefix caching server-side on
   some models, but there's no Anthropic-style explicit `cache_control`
   breakpoint or a documented, guaranteed discount tier for it the way
   Claude has -- `cache_control` blocks are flattened away below (same as
   the OSS crosscheck client already does), and token_pricing.py's cost
   calculation for Groq calls only ever reflects plain input/output cost.
2. Batch API: Groq does have a real async Batch endpoint (JSONL-file-based,
   closer to OpenAI's Batches API shape than Anthropic's Message Batches),
   but `create_message_batch` below is NOT that -- it's a bounded-
   concurrency synchronous fan-out shim, same pattern and same caveat as
   gemini_client.py's. It exists so submit_classification_batch() /
   run_candidate_pool_narratives() keep working unmodified when
   LLM_PROVIDER=groq. Worth wiring the real batch endpoint later if volume
   on Groq gets large enough that its discount matters; out of scope here.

Model ids (openai/gpt-oss-120b, qwen/qwen3.6-27b, openai/gpt-oss-20b) --
see router.py -- reflect Groq's June-2026 deprecation of the older Llama
3.x models; verify against https://console.groq.com/docs/models before
relying on this, Groq's lineup moves fast.

`create_message` below is implemented via app/core/llm/langchain_backend.py
(LangChain's `ChatGroq`) -- see that module's docstring for why one
shared LangChain-based implementation replaced the per-provider
request/response translation code (Anthropic content-blocks <-> the
OpenAI-shaped messages Groq's endpoint expects, a Groq-specific
finish_reason map) this file used to carry directly. Everything else
below -- the two real differences from Claude, the batch shim,
FakeGroqClient -- is unchanged.

Model ids (openai/gpt-oss-120b, qwen/qwen3.6-27b, openai/gpt-oss-20b) --
see router.py -- reflect Groq's June-2026 deprecation of the older Llama
3.x models; verify against https://console.groq.com/docs/models before
relying on this, Groq's lineup moves fast.

Requires `pip install langchain-groq` and GROQ_API_KEY set in the
environment. Not exercised in this sandbox (no API key at build time, no
network egress to Groq's API here). FakeGroqClient below lets everything
downstream be tested without one.
"""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.llm.claude_client import BatchRequestSpec, MessageResult
from app.core.llm.router import Provider
from app.core.llm.token_pricing import calculate_cost


class GroqClient:
    """Production client. Requires `pip install langchain-groq` and
    GROQ_API_KEY set in the environment (or passed explicitly)."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("GROQ_API_KEY")
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
            provider=Provider.GROQ, model=model, system=system, messages=messages,
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
        batch_id = f"groq_batch_{uuid.uuid4().hex[:8]}"

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


class FakeGroqClient:
    """Deterministic stand-in for GroqClient, used by tests and local dev
    without an API key. Mirrors FakeAnthropicClient's contract so tests
    can parametrize over both."""

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
            "id": f"groq_fake_{len(self.calls)}",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "[fake groq response]"}],
            "usage": dict(self.next_usage),
        }

    def create_message_with_cost(self, **kwargs) -> MessageResult:
        raw = self.create_message(**kwargs)
        return MessageResult(raw=raw, cost=calculate_cost(kwargs["model"], raw["usage"]))

    def create_message_batch(self, requests: list[BatchRequestSpec]) -> dict[str, Any]:
        batch_id = f"groq_batch_fake_{uuid.uuid4().hex[:8]}"
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
                        "content": [{"type": "text", "text": "[fake groq batch response]"}],
                        "usage": dict(self.next_usage),
                    },
                },
            }
            for r in self._batches[batch_id]["requests"]
        ]
