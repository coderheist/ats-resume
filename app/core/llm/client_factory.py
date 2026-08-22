"""
Single entry point for "give me the client and model for this task,"
provider-aware. This is the function call sites should use instead of
constructing `AnthropicClient()` (or `GeminiClient()` / `GroqClient()`)
directly, the same way everything already goes through `router.route()`
instead of hard-coding a model string.

    from app.core.llm.client_factory import get_client_for
    from app.core.llm.router import TaskType

    client, model = get_client_for(TaskType.CONVERSATIONAL_AGENT)
    result = client.create_message_with_cost(
        model=model, system=..., messages=[...],
    )

Which concrete client you get back is decided entirely by
`router.active_provider()` (the LLM_PROVIDER env var, default "claude"),
except for EXTRACTION_CROSSCHECK, which always goes through
oss_extraction_client.py regardless -- see router.py's module docstring
for the full rationale on why that task type sits outside this switch.

Live-network imports (the `anthropic`, `google-genai`, and `groq` SDKs)
are deferred to inside each client class, not here -- so importing this
module, or calling get_client_for() for a provider whose SDK isn't
installed, never fails at import time. It only fails when a real
create_message() call is actually made without the right package
installed, which is the same lazy-import discipline claude_client.py and
oss_extraction_client.py already follow.
"""
from __future__ import annotations

from app.core.llm.claude_client import AnthropicClient, LLMClient
from app.core.llm.gemini_client import GeminiClient
from app.core.llm.groq_client import GroqClient
from app.core.llm.oss_extraction_client import OSSExtractionClient
from app.core.llm.router import Provider, TaskType, active_provider, route

_CLIENT_CLASSES: dict[Provider, type] = {
    Provider.CLAUDE: AnthropicClient,
    Provider.GEMINI: GeminiClient,
    Provider.GROQ: GroqClient,
}


def get_client_for(task: TaskType, *, provider: Provider | None = None) -> tuple[LLMClient, str]:
    """
    Returns (client, model_id) for a given task type.

    `provider` defaults to `router.active_provider()` (LLM_PROVIDER env
    var, "claude" if unset). Pass it explicitly to override just this one
    call -- e.g. running the same task on two providers side by side to
    compare quality before fully switching.

    TaskType.EXTRACTION_CROSSCHECK always returns an OSSExtractionClient,
    ignoring `provider` -- that task type isn't part of the Claude/Gemini/
    Groq switch (see router.py).
    """
    if task is TaskType.EXTRACTION_CROSSCHECK:
        return OSSExtractionClient(), route(task)

    resolved_provider = provider or active_provider()
    client_cls = _CLIENT_CLASSES[resolved_provider]
    return client_cls(), route(task, provider=resolved_provider)
