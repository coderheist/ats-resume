"""
Model routing layer (blueprint Section 4.3).

The single most important rule from the blueprint: never hard-code a model
string at the call site. Every LLM call in this codebase goes through
`route()` below, which maps a *task type* to a model. When a new model ships
-- and per the blueprint, that has been happening every few weeks in 2026 --
this is the only file that needs to change.

--------------------------------------------------------------------------
Multi-provider switching (added 2026-08)
--------------------------------------------------------------------------
Claude is the intended production backend (see the blueprint), but its
per-token price is real money you may not want to spend yet while a
product is pre-revenue. So the three task types that talk to a closed
frontier API (CONVERSATIONAL_AGENT, DEEP_REASONING, FAST_CLASSIFICATION)
can now each be routed to one of three providers:

  - "claude" (default, unchanged)  -- app/core/llm/claude_client.py
  - "gemini"                       -- app/core/llm/gemini_client.py
  - "groq"                         -- app/core/llm/groq_client.py

(A fourth task, RESUME_EXTRACTION -- added 2026-08 alongside the file/
paste-text upload flow, see app/core/parsing/resume_extraction.py -- is
also part of this switch. It's mapped to the same model as
CONVERSATIONAL_AGENT per provider: unlike FAST_CLASSIFICATION's
two-label output, turning a whole resume into structured JSON needs
real instruction-following reliability, not just raw speed, but it's
frequent enough -- every upload -- that DEEP_REASONING's cost tier isn't
warranted either.)

Switch by setting the LLM_PROVIDER environment variable (`claude`,
`gemini`, or `groq`) -- nothing else in the codebase changes, because
callers only ever ask `route(task)` / `get_client_for(task)` (see
client_factory.py) for "the model/client for this task," never a
provider-specific string. That's the whole point of routing through this
file in the first place: this is the ONE place the provider lives, same as
it's the one place the model lineup lives.

Per-task model choice for gemini/groq mirrors the same
frequency/stakes reasoning as the Claude column (see the table below and
client_factory.py's docstring) -- cheapest-reliable model for the
high-frequency tasks, a stronger model reserved for the low-frequency,
high-stakes one.

Gemini and Groq model ids current as of August 2026 (verify before
relying on this -- both vendors ship new model ids every few weeks, same
caveat as the Claude side):
  - Gemini: 3.6 Flash (agent) / 3.1 Pro (deep reasoning) / 3.5 Flash-Lite
    (fast classification). Google's Gemini 2.5 family still works but is
    slated to retire 2026-10-16 -- don't build new defaults on it.
  - Groq: openai/gpt-oss-120b (agent) / qwen/qwen3.6-27b (deep reasoning,
    Groq's own docs call this their highest-intelligence hosted model) /
    openai/gpt-oss-20b (fast classification). Groq deprecated
    llama-3.3-70b-versatile and llama-3.1-8b-instant in June 2026 in favor
    of exactly these gpt-oss models -- if you see the old llama ids in any
    older writeup, they're stale.

EXTRACTION_CROSSCHECK is intentionally NOT part of this switch -- it stays
on the open-weight model routed through oss_extraction_client.py
regardless of LLM_PROVIDER (see OSS_TASKS below and that module's
docstring for why: the whole point of a crosscheck pass is a genuinely
different model family from whichever closed API is primary, and Groq
itself is one of the OpenAI-compatible hosts that adapter already talks
to -- so pointing OSS_EXTRACTION_BASE_URL at Groq is a legitimate way to
run the crosscheck for free/cheap too, independent of this switch).

--------------------------------------------------------------------------
Current allocation (August 2026, provider="claude", the default)
--------------------------------------------------------------------------
  conversational_agent  -> Claude Sonnet 5    (voice-editing dialogue,
                                                tool-calling reliability)
  deep_reasoning         -> Claude Opus 4.8    (XAI narratives, bias audit
                                                reasoning -- low frequency,
                                                high stakes)
  fast_classification    -> Claude Haiku 4.5   (role/section classification,
                                                run on every document)
  extraction_crosscheck  -> Qwen 3.6 35B-A3B, open-weight, self-hosted or via
                                                a cheap inference host (secondary,
                                                independent extraction pass
                                                for high-stakes fields)

Why extraction_crosscheck is open-weight rather than another closed API
(this used to point at a placeholder OpenAI/Gemini alias -- changed
2026-08):

The whole point of a crosscheck pass is running the SAME extraction
through a genuinely DIFFERENT model family than the primary path, so the
two don't share correlated failure modes. That doesn't require a second
closed-API subscription -- an open-weight model does the job and avoids
paying a second vendor's per-token margin on top of Anthropic's, on a task
that runs on every single document, not occasionally.

Qwen 3.6 (35B total, ~3B active params/token, MoE) was picked over the
alternatives surveyed because for this specific job:
  - Structured output that respects a JSON Schema and reliable tool
    calling are called out as first-class, not bolted on.
  - The ~3B active-parameter footprint makes it one of the cheaper
    frontier-adjacent models to self-host (vLLM/SGLang, both back it),
    and the smaller a crosscheck model is, the more of the cost-avoidance
    case for running your own instead of paying a vendor holds up.
  - Commercial use is permitted under its license as of this writing --
    verify current license terms before deploying, license terms do change.

Two alternatives worth knowing about instead, depending on constraints:
  - GLM-5.2 -- reported as the strongest all-round open-weight model
    (long-context reasoning), if crosscheck accuracy on messy/ambiguous
    resumes matters more than raw cost and you can afford a larger host.
  - NuExtract 3 -- a 4B model purpose-built for exactly this shape of task
    (schema-driven document -> JSON), which makes it worth a real
    evaluation against Qwen on this codebase's own eval set. Its weights
    ship under a modified OpenRAIL-M license: free for research/personal
    use and for companies under $5M in funding or revenue, but a paid
    commercial license is required above that threshold -- get that
    checked against this product's actual revenue before shipping it,
    since "open-weight" here doesn't mean licensing is a non-issue.

None of this is exercised in the sandbox (no inference endpoint reachable
here) -- see app/core/llm/oss_extraction_client.py for the adapter, written
against the real OpenAI-compatible request shape that vLLM, SGLang, and
every major inference host (Together, Fireworks, DeepInfra, Groq, etc.)
all speak, so switching between self-hosting and a hosted provider -- or
swapping in GLM-5.2 or NuExtract 3 -- is a config change, not a rewrite.
"""
from __future__ import annotations

import os
from enum import Enum


class TaskType(str, Enum):
    CONVERSATIONAL_AGENT = "conversational_agent"
    DEEP_REASONING = "deep_reasoning"
    FAST_CLASSIFICATION = "fast_classification"
    EXTRACTION_CROSSCHECK = "extraction_crosscheck"
    RESUME_EXTRACTION = "resume_extraction"
    # Rewriting a role's bullet points into quantified, JD-aware lines.
    # Separate from FAST_CLASSIFICATION because it is the one operation
    # subscribers are actually paying for, so it is worth spending a
    # better model on even where the cheap one would technically answer
    # -- and separate from RESUME_EXTRACTION because that is a
    # structure-only job with no writing in it.
    BULLET_REWRITE = "bullet_rewrite"


class Provider(str, Enum):
    """Which closed-API backend handles the three non-OSS task types.
    EXTRACTION_CROSSCHECK ignores this entirely (see module docstring)."""
    CLAUDE = "claude"
    GEMINI = "gemini"
    GROQ = "groq"


class Tier(str, Enum):
    """A user-facing "quality/cost" label for the same three providers --
    added 2026-08 alongside the resume-upload flow so a person picks a
    tier per request (Basic/Medium/Advanced) rather than being stuck with
    whatever LLM_PROVIDER the process happens to be started with. This is
    the fix for a real bug: before this existed, setting GEMINI_API_KEY
    or GROQ_API_KEY alone did nothing, because the code only ever checked
    the key for active_provider() (LLM_PROVIDER, defaulting to "claude")
    -- someone who configured a Gemini/Groq key without *also* setting
    LLM_PROVIDER got "no provider configured" regardless. Passing an
    explicit tier (-> provider) per request sidesteps that whole class of
    confusion: the caller says which provider they mean, instead of it
    being inferred from an env var they may not have set.

    LLM_PROVIDER / active_provider() remains the *default* used when no
    tier is passed (e.g. the batch/voice-agent code paths that don't
    (yet) expose a per-request choice) -- this is additive, not a
    replacement."""
    BASIC = "basic"       # Groq    -- free/cheapest, good default to try first
    MEDIUM = "medium"     # Gemini  -- stronger, still inexpensive
    ADVANCED = "advanced" # Claude  -- best quality, real per-token cost


TIER_TO_PROVIDER: dict[Tier, Provider] = {
    Tier.BASIC: Provider.GROQ,
    Tier.MEDIUM: Provider.GEMINI,
    Tier.ADVANCED: Provider.CLAUDE,
}
PROVIDER_TO_TIER: dict[Provider, Tier] = {v: k for k, v in TIER_TO_PROVIDER.items()}


def provider_for_tier(tier: Tier | str) -> Provider:
    """Raises ValueError for a string that isn't a valid Tier -- callers
    at an API boundary (see app/api/routes/resume.py) should catch that
    and turn it into a 400, not let it become a 500."""
    return TIER_TO_PROVIDER[Tier(tier)]


# NOTE: keep this map, and only this map, in sync as the model landscape
# moves. Nothing else in the codebase should reference a model string.
# One row per provider for the four switchable task types;
# EXTRACTION_CROSSCHECK is deliberately absent here (see below).
_MODEL_MAP: dict[Provider, dict[TaskType, str]] = {
    Provider.CLAUDE: {
        TaskType.CONVERSATIONAL_AGENT: "claude-sonnet-5",
        TaskType.DEEP_REASONING: "claude-opus-4-8",
        TaskType.FAST_CLASSIFICATION: "claude-haiku-4-5-20251001",
        TaskType.RESUME_EXTRACTION: "claude-sonnet-5",
        TaskType.BULLET_REWRITE: "claude-sonnet-5",
    },
    Provider.GEMINI: {
        TaskType.CONVERSATIONAL_AGENT: "gemini-3.6-flash",
        TaskType.DEEP_REASONING: "gemini-3.1-pro",
        TaskType.FAST_CLASSIFICATION: "gemini-3.5-flash-lite",
        TaskType.RESUME_EXTRACTION: "gemini-3.6-flash",
        TaskType.BULLET_REWRITE: "gemini-3.6-flash",
    },
    Provider.GROQ: {
        TaskType.CONVERSATIONAL_AGENT: "openai/gpt-oss-120b",
        TaskType.DEEP_REASONING: "qwen/qwen3.6-27b",
        TaskType.FAST_CLASSIFICATION: "openai/gpt-oss-20b",
        TaskType.RESUME_EXTRACTION: "openai/gpt-oss-120b",
        TaskType.BULLET_REWRITE: "openai/gpt-oss-120b",
    },
}

# extraction_crosscheck always resolves here, regardless of provider/env --
# it is not part of the Claude/Gemini/Groq switch at all.
_OSS_MODEL = "qwen3.6-35b-a3b-instruct"

# Tasks routed to Claude (all of them except the crosscheck) go through
# app/core/llm/claude_client.py -- or, when LLM_PROVIDER is set, the
# equivalent gemini_client.py / groq_client.py. EXTRACTION_CROSSCHECK
# always goes through app/core/llm/oss_extraction_client.py instead --
# same LLMClient protocol, different backend, see that module for why.
OSS_TASKS: frozenset[TaskType] = frozenset({TaskType.EXTRACTION_CROSSCHECK})


def active_provider() -> Provider:
    """
    Reads LLM_PROVIDER from the environment (default: "claude"). This is
    the single switch: set it once (env var, .env file, deploy config) and
    every conversational_agent / deep_reasoning / fast_classification call
    in the app follows it, with no code changes anywhere else.

        export LLM_PROVIDER=gemini   # or groq, or claude (default)

    Invalid values fall back to "claude" rather than raising, so a typo'd
    env var degrades to the production default instead of crashing the app.
    """
    raw = os.environ.get("LLM_PROVIDER", Provider.CLAUDE.value).strip().lower()
    try:
        return Provider(raw)
    except ValueError:
        return Provider.CLAUDE


def route(task: TaskType, provider: Provider | None = None) -> str:
    """
    Return the model identifier for a given task type.

    `provider` defaults to `active_provider()` (i.e. the LLM_PROVIDER env
    var, or Claude if unset) -- pass it explicitly only when you deliberately
    want one call routed differently than the process-wide default (e.g. a
    one-off eval comparing providers on the same task).

    EXTRACTION_CROSSCHECK ignores `provider` entirely and always returns
    the open-weight crosscheck model -- see the module docstring for why
    that task type sits outside the Claude/Gemini/Groq switch.
    """
    if task is TaskType.EXTRACTION_CROSSCHECK:
        return _OSS_MODEL
    resolved_provider = provider or active_provider()
    return _MODEL_MAP[resolved_provider][task]
