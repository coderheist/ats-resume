"""
Adapter for TaskType.EXTRACTION_CROSSCHECK -- an open-weight model doing an
independent second-opinion extraction pass over resume/JD fields, instead
of a second closed-API vendor (see router.py for the full rationale).

Deliberately NOT an Anthropic client. This speaks the OpenAI-compatible
`/v1/chat/completions` shape, because that's the lingua franca every
self-hosted server (vLLM, SGLang, TGI) and every major open-weight
inference host (Together AI, Fireworks, DeepInfra, Groq, etc.) already
implements. That means switching from "self-hosted on our own GPUs" to
"rented from a hosted provider" -- or swapping Qwen 3.6 for GLM-5.2 or
NuExtract 3, see router.py -- is a base_url + model string change, not a
rewrite.

Not exercised in this sandbox (no inference endpoint reachable here) --
same "adapter written against the real API shape, not invoked" pattern as
claude_client.py and parser_interface.py. FakeOSSExtractionClient below
lets everything downstream be tested without one.

On self-hosting vs. Anthropic's Batch API: these are NOT the same
cost lever, and this module deliberately doesn't claim a "50% batch
discount" the way claude_client.py legitimately does for Anthropic --
there is no vendor list price here to discount from. What self-hosting
actually saves is the per-token vendor margin itself: you pay for your
own GPU time (or a hosted provider's, priced far below closed-API rates
because open weights have no licensing markup), not a per-token fee set
by a model vendor. Throughput at volume comes from the inference server's
own request batching (vLLM's continuous batching), which is a serving-
layer optimization, not a billing discount -- real, but a different
mechanism, so don't conflate the two when writing this up for stakeholders.
"""
from __future__ import annotations

import os
from typing import Any


class OSSExtractionClient:
    """
    Production client. Requires `pip install openai` (used purely as an
    HTTP client here -- any OpenAI-compatible SDK/HTTP call works, this one
    is just the most widely supported) and an inference endpoint that
    implements /v1/chat/completions with structured-output support.

    Configured entirely by environment so swapping self-hosted vLLM for a
    hosted provider, or swapping models, never touches code:
      OSS_EXTRACTION_BASE_URL  -- e.g. http://localhost:8000/v1 (self-hosted
                                   vLLM) or a hosted provider's endpoint
      OSS_EXTRACTION_API_KEY   -- required by hosted providers; vLLM
                                   ignores it by default unless configured
                                   with --api-key
      OSS_EXTRACTION_MODEL     -- overrides router.route()'s model id if
                                   the endpoint expects a different alias
                                   (self-hosted deployments often serve the
                                   model under a local name)

    Concretely, to run the crosscheck pass on Groq for free/cheap instead
    of self-hosting (this is independent of the LLM_PROVIDER switch in
    router.py -- that switch covers the other three task types, this one
    always runs through this module regardless of LLM_PROVIDER):
      OSS_EXTRACTION_BASE_URL=https://api.groq.com/openai/v1
      OSS_EXTRACTION_API_KEY=<your GROQ_API_KEY>
      OSS_EXTRACTION_MODEL=qwen/qwen3.6-27b   # closest match to the Qwen
                                               # 3.6 family this router
                                               # already targets, see
                                               # router.py
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model_override: str | None = None,
    ) -> None:
        self._base_url = base_url or os.environ.get(
            "OSS_EXTRACTION_BASE_URL", "http://localhost:8000/v1"
        )
        self._api_key = api_key or os.environ.get("OSS_EXTRACTION_API_KEY", "not-needed")
        self._model_override = model_override or os.environ.get("OSS_EXTRACTION_MODEL")

    def _sdk_client(self):
        import openai  # deferred import: not a hard dependency of tests
        return openai.OpenAI(base_url=self._base_url, api_key=self._api_key)

    def create_message(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Same shape as AnthropicClient.create_message so this drops into the
        same call sites, translated to the OpenAI-compatible request/
        response shape.

        `json_schema`: when given, requests constrained decoding via
        `response_format={"type": "json_schema", ...}`. On vLLM/SGLang this
        is enforced by XGrammar at the token level -- the model cannot
        emit invalid JSON, not "usually doesn't." Always pass this for
        crosscheck extraction; the whole point of a second opinion is a
        clean, directly-diffable structure against the primary pass, not
        prose to re-parse.
        """
        client = self._sdk_client()
        oa_messages: list[dict[str, Any]] = []
        if isinstance(system, str):
            oa_messages.append({"role": "system", "content": system})
        elif system:
            # Content-block list (matching AnthropicClient's shape) -- an
            # OpenAI-compatible endpoint has no notion of cache_control, so
            # flatten to plain text. Caching for this task type would need
            # a KV-cache-reuse feature at the inference-server level
            # instead (e.g. vLLM's automatic prefix caching) -- a serving
            # config, not something this client controls per-request.
            oa_messages.append(
                {"role": "system", "content": "\n\n".join(b.get("text", "") for b in system)}
            )
        oa_messages.extend(messages)

        kwargs: dict[str, Any] = dict(
            model=self._model_override or model,
            messages=oa_messages,
            max_tokens=max_tokens,
        )
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction_result", "schema": json_schema, "strict": True},
            }
        if tools:
            kwargs["tools"] = tools

        response = client.chat.completions.create(**kwargs)
        return response.model_dump()


class FakeOSSExtractionClient:
    """Deterministic stand-in for tests/local dev without a live endpoint."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.next_content: str = "{}"

    def create_message(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {"model": model, "system": system, "messages": messages, "json_schema": json_schema}
        )
        return {
            "id": f"chatcmpl_fake_{len(self.calls)}",
            "choices": [
                {
                    "message": {"role": "assistant", "content": self.next_content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 400, "completion_tokens": 60, "total_tokens": 460},
        }
