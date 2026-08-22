"""
Task 4: turns suggestion_engine.py's ranked, deterministic Suggestion list
into candidate-facing prose -- distinct tone for With-JD vs. No-JD mode,
per the approved design.

Follows the same shape as batch_candidate_narratives.py: a rubric-style
system prompt, cache-aware system-block construction (prompt_cache.py),
and an explicit "these facts are already computed, do not invent
anything beyond them" guardrail -- the LLM's job here is phrasing, not
deciding what's wrong with the resume. Routed through
TaskType.CONVERSATIONAL_AGENT (Sonnet-tier): this runs once per candidate
scan, not a recruiter-dashboard batch job across many candidates, so it
doesn't need DEEP_REASONING's heavier tier.

Two entry points:
- generate_feedback_summary(): the real, LLM-backed path. Needs a live
  LLMClient (e.g. AnthropicClient with ANTHROPIC_API_KEY set); unit-tested
  here against FakeAnthropicClient, same as batch_candidate_narratives.py.
- template_feedback_summary(): a deterministic, non-AI fallback that
  needs no API key at all, so the API route always has something to
  return. Mirrors the frontend's "template preview, not AI-generated"
  bullet-draft pattern in voice_agent -- same philosophy, applied here.
"""
from __future__ import annotations

from app.core.llm.claude_client import LLMClient
from app.core.llm.prompt_cache import build_system_blocks
from app.core.llm.router import TaskType, route
from app.core.scoring.suggestion_engine import Suggestion

WITH_JD_INSTRUCTIONS = """You are a resume coach writing feedback for a candidate who is applying to
a *specific* job. You are given an already-ranked list of fixes and the
job description they're applying to. Do not re-rank them, do not invent
new fixes, and do not reference any skill, requirement, or fact that
isn't explicitly present in the fixes list or the job description below.

Ground every sentence in the specific job: reference what the job
actually asks for, not generic advice that could apply to any posting.
Write exactly one sentence per fix, in the same order given. Each
sentence must:
- name the specific gap in second person ("you"), not third person
- reference the specific role/bullet if one was given
- avoid boilerplate openers ("It's important to...", "Consider...",
  "One suggestion is...") -- start directly with the action
- use varied sentence structure across the five -- no two sentences
  should start with the same word or follow the same template

Output the five sentences as a numbered list, nothing else -- no preamble,
no closing summary."""

NO_JD_INSTRUCTIONS = """You are a resume coach writing general ATS-readiness feedback for a
candidate who has not targeted a specific job yet. You are given an
already-ranked list of fixes. Do not re-rank them, do not invent new
fixes, and do not reference any skill or requirement not explicitly
present in the fixes list below.

Since there's no specific job to ground this in, focus each sentence on
general ATS readability, metric density, and industry-standard skill
expectations for the candidate's inferred field -- not job-specific
language. Write exactly one sentence per fix, in the same order given.
Each sentence must:
- name the specific gap in second person ("you"), not third person
- reference the specific role/bullet if one was given
- avoid boilerplate openers ("It's important to...", "Consider...",
  "One suggestion is...") -- start directly with the action
- use varied sentence structure across the five -- no two sentences
  should start with the same word or follow the same template

Output the five sentences as a numbered list, nothing else -- no preamble,
no closing summary."""


def _format_suggestions_block(suggestions: list[Suggestion]) -> str:
    lines = []
    for i, s in enumerate(suggestions, start=1):
        target = f" (role: {s.target})" if s.target else ""
        lines.append(f"{i}. [{s.category}]{target} {s.message}")
    return "\n".join(lines)


def build_feedback_system(mode: str) -> list[dict]:
    """mode is 'with_jd' or 'no_jd'."""
    instructions = WITH_JD_INSTRUCTIONS if mode == "with_jd" else NO_JD_INSTRUCTIONS
    return build_system_blocks(stable_instructions=instructions, volatile_context=None)


def build_feedback_messages(suggestions: list[Suggestion], jd_text: str | None = None) -> list[dict]:
    suggestions_block = _format_suggestions_block(suggestions)
    if jd_text:
        content = f"Job description:\n{jd_text}\n\nRanked fixes (already computed, do not re-rank):\n{suggestions_block}"
    else:
        content = f"Ranked fixes (already computed, do not re-rank):\n{suggestions_block}"
    return [{"role": "user", "content": content}]


def generate_feedback_summary(
    client: LLMClient,
    suggestions: list[Suggestion],
    *,
    mode: str,
    jd_text: str | None = None,
    model: str | None = None,
) -> str:
    """Real, LLM-backed path. Raises whatever the client raises on failure
    -- callers (API routes) should fall back to template_feedback_summary()
    on error rather than surface a raw exception to the candidate."""
    if not suggestions:
        return "No major issues found -- this resume is in good shape."

    response = client.create_message(
        model=model or route(TaskType.CONVERSATIONAL_AGENT),
        system=build_feedback_system(mode),
        messages=build_feedback_messages(suggestions, jd_text),
        max_tokens=600,
    )
    for block in response.get("content", []):
        if block.get("type") == "text":
            return block["text"].strip()
    return ""


def template_feedback_summary(suggestions: list[Suggestion]) -> list[str]:
    """Deterministic, non-AI fallback -- needs no API key. Same role as
    the frontend's template bullet preview: clearly not AI-generated,
    but always available."""
    if not suggestions:
        return ["No major issues found -- this resume is in good shape."]
    return [s.message for s in suggestions]
