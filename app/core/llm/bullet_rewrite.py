"""
AI bullet rewriting -- the metered feature the paid plans actually sell.

The quality bar and the worked examples here are lifted from
voice_system_prompt.py, which had already worked out what separates a
weak resume bullet from a strong one. That work is reused rather than
reinvented: the standard does not change because the input arrived as
typed text instead of speech.

ONE THING IS DELIBERATELY DIFFERENT FROM THE VOICE AGENT, AND IT IS THE
MOST IMPORTANT RULE IN THIS MODULE. The voice agent, faced with a bullet
that has no measurable outcome, asks the candidate for the number. This
path has no conversation to ask into -- it is a single request/response
against text that is already written. So it must NEVER invent the number.

A resume tool that fabricates "reduced costs by 30%" is not a helpful
tool; it writes a claim the candidate has to defend in an interview and
cannot. It is worse than useless, because the output looks better while
being a liability. When a bullet has no metric, the rewrite improves what
can honestly be improved -- verb strength, specificity, scope, removing
passive voice and filler -- and returns `needs_metric: true` with a
prompt naming what to measure, so the UI can ask the person who actually
knows the answer.

Output is JSON so each bullet keeps its `needs_metric` flag alongside its
text. Prose would force the caller to parse a flag back out of English,
and the flag is the part that keeps the feature honest.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict

from app.core.llm.client_factory import LLMClient
from app.core.llm.router import TaskType, route

# One rewrite call handles a whole role's bullets rather than one line at
# a time. That is both what the pricing meters (one role = one rewrite,
# see entitlement_service.record_rewrite) and what produces better
# output: the model can see the other bullets and avoid opening four in a
# row with the same verb, which per-bullet calls reliably do.
MAX_BULLETS_PER_REQUEST = 12
MAX_BULLET_CHARS = 1200
MAX_JD_CHARS = 6000

REWRITE_SYSTEM = """You rewrite resume bullet points. You are given the bullets under one role, and sometimes a job description to tailor them toward.

## What a strong bullet looks like

Every bullet is: a strong action verb, the specific thing done (with scope -- scale, tooling, team size, timeframe), and the outcome it produced. Implied subject, never first person: "Led the migration...", not "I led the migration...".

Weak: "Wrote documentation for the API."
Strong: "Authored the public API reference docs, reducing integration support requests by roughly a third within two months of publishing."

Weak: "Fixed a bunch of bugs in the mobile app."
Strong: "Resolved 30+ crash-causing defects in the iOS app over one quarter, lifting the crash-free session rate from 96% to 99.4%."

Weak: "Set up monitoring for the infrastructure."
Strong: "Instrumented Prometheus/Grafana monitoring across 40+ services, cutting mean time to detect production incidents from 45 minutes to 6."

## The rule you must never break

NEVER invent, estimate, or imply a number, percentage, duration, team size, or outcome that is not present in the original bullet or clearly implied by it.

You have no way to ask the candidate what the real figure was. A fabricated metric is a claim they will be asked to defend in an interview and cannot. This rule outranks every other instruction here, including making the bullet sound impressive.

When the original bullet has no measurable outcome:
  - Rewrite what you honestly can: a stronger verb, the specific scope that IS stated, active voice, removing filler like "responsible for" and "helped with".
  - Set "needs_metric": true.
  - In "metric_hint", name the specific measurement that would make this bullet land -- e.g. "How many services? What did latency go from and to?" Ask for the number; do not guess it.

When the original bullet already carries a real metric, keep that exact figure. Do not round it, scale it, or make it sound larger.

## Tailoring to a job description

When a job description is given, prefer the vocabulary it uses where the candidate's work genuinely matches -- if they wrote "containers" and the posting says "Kubernetes", use "Kubernetes" ONLY if the original mentions Kubernetes or something unambiguously equivalent. Matching a keyword the candidate has not actually earned is the same fabrication problem in a different costume.

## Output

Return ONLY a JSON object, no prose around it:

{"bullets": [{"original": "<the input bullet, unchanged>", "rewritten": "<your rewrite>", "needs_metric": true|false, "metric_hint": "<question naming the missing measurement, or empty string>"}]}

One entry per input bullet, in the same order. If a bullet is already strong and you cannot improve it honestly, return it unchanged with "needs_metric": false."""


@dataclass
class RewrittenBullet:
    original: str
    rewritten: str
    needs_metric: bool
    metric_hint: str

    def as_dict(self) -> dict:
        return asdict(self)


def build_rewrite_messages(
    bullets: list[str],
    *,
    role_title: str | None = None,
    company: str | None = None,
    jd_text: str | None = None,
) -> list[dict]:
    parts: list[str] = []
    where = " at ".join(x for x in (role_title, company) if x)
    if where:
        parts.append(f"Role: {where}")
    if jd_text:
        parts.append(
            "Job description to tailor toward (use its vocabulary only where the "
            "candidate's work genuinely matches):\n" + jd_text[:MAX_JD_CHARS]
        )
    numbered = "\n".join(f"{i + 1}. {b}" for i, b in enumerate(bullets))
    parts.append("Bullets to rewrite:\n" + numbered)
    return [{"role": "user", "content": "\n\n".join(parts)}]


class UnparsableRewriteError(ValueError):
    """Raised by _extract_json when the model's reply has no recoverable
    JSON object in it.

    A distinct type (rather than a bare ValueError) so rewrite_bullets can
    catch specifically this -- a real JSON-parsing failure worth one
    corrective retry -- without also swallowing a json.JSONDecodeError
    thrown mid-retry for an unrelated reason, or masking a bug in the
    calling code that happens to raise ValueError for some other cause.
    json.JSONDecodeError already subclasses ValueError, so both failure
    shapes this module can produce are caught by one except clause.
    """


def _extract_json(text: str) -> dict:
    """Models occasionally wrap JSON in a ```json fence or a sentence of
    preamble despite being told not to. Strip the common cases rather
    than failing the whole request over formatting -- but do not attempt
    to repair genuinely malformed JSON, which risks silently changing
    what the model said about a candidate's work."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise UnparsableRewriteError("The rewrite model returned no JSON object.")
    return json.loads(text[start : end + 1])


def _coerce(payload: dict, originals: list[str]) -> list[RewrittenBullet]:
    """Align the model's output back onto the input list.

    Positional, and defensive about length: a model that returns fewer
    entries than it was given must not silently drop a candidate's bullet
    from their resume. Anything missing falls back to the original text,
    flagged as needing a metric only if it visibly lacks a digit.
    """
    rows = payload.get("bullets") or []
    out: list[RewrittenBullet] = []
    for i, original in enumerate(originals):
        row = rows[i] if i < len(rows) and isinstance(rows[i], dict) else {}
        rewritten = (row.get("rewritten") or "").strip() or original
        needs = row.get("needs_metric")
        if not isinstance(needs, bool):
            needs = not re.search(r"\d", rewritten)
        out.append(RewrittenBullet(
            original=original,
            rewritten=rewritten,
            needs_metric=needs,
            metric_hint=(row.get("metric_hint") or "").strip(),
        ))
    return out


_RETRY_NUDGE = (
    "That response was not a single valid JSON object, so it could not be used. "
    "Reply again with ONLY the JSON object described above -- no markdown fence, "
    "no prose before or after it, no explanation."
)


def _call_and_extract_text(client: LLMClient, *, model: str, system: str, messages: list[dict]) -> str:
    """One model call: send it, log its cost, and pull the text block back
    out. Raised errors from the client itself (auth, network, rate limit)
    propagate unchanged -- those are not what the retry in rewrite_bullets
    is for; see its docstring."""
    response = client.create_message(model=model, system=system, messages=messages, max_tokens=1600)

    if "usage" in response:
        from app.core.llm.token_pricing import _infer_provider_from_model, record_llm_usage
        record_llm_usage(model, response["usage"], provider=_infer_provider_from_model(model))

    for block in response.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    return ""


def rewrite_bullets(
    client: LLMClient,
    bullets: list[str],
    *,
    role_title: str | None = None,
    company: str | None = None,
    jd_text: str | None = None,
    model: str | None = None,
    task: TaskType = TaskType.BULLET_REWRITE,
) -> list[RewrittenBullet]:
    """Rewrite one role's bullets.

    `task` defaults to BULLET_REWRITE but is passed in by the route so a
    Free-tier request can be served by the cheaper model
    (app/core/llm/tier_routing.py decides which).

    Retries exactly once, and only for one specific failure: the model
    answered, but what it said isn't a JSON object that parses -- a
    smaller/cheaper model occasionally wraps its answer in a stray
    sentence or a markdown fence despite the system prompt's "no prose"
    instruction. The retry hands that exact bad reply back to the model as
    an assistant turn, with a short correction, rather than repeating the
    original request and hoping for different luck -- concrete feedback on
    what was wrong gets a valid reply far more reliably than a blind
    resend, and it costs one extra call only on the failure path, not on
    every request.

    Deliberately NOT retried: an exception raised by the client itself
    (network error, rate limit, invalid API key, upstream 5xx). Those are
    provider/infrastructure failures, not "the model said something odd"
    -- retrying them risks hammering an already-failing or already
    rate-limited API, and the caller (the /resume/rewrite-bullets route)
    is what decides how to surface that to the user (a 502, allowance
    left untouched). They propagate unchanged, exactly as before.
    """
    cleaned = [b.strip()[:MAX_BULLET_CHARS] for b in bullets if b and b.strip()]
    if not cleaned:
        return []
    cleaned = cleaned[:MAX_BULLETS_PER_REQUEST]

    resolved_model = model or route(task)
    first_messages = build_rewrite_messages(cleaned, role_title=role_title, company=company, jd_text=jd_text)

    text = _call_and_extract_text(client, model=resolved_model, system=REWRITE_SYSTEM, messages=first_messages)
    try:
        payload = _extract_json(text)
    except ValueError:
        retry_messages = [
            *first_messages,
            {"role": "assistant", "content": text},
            {"role": "user", "content": _RETRY_NUDGE},
        ]
        # No inner try/except here: if the retry also fails to parse, that
        # ValueError is the one that should reach the route -- one
        # corrective attempt is the policy, not a loop, so a model that
        # cannot produce valid JSON twice in a row is a real failure to
        # report, not something to keep hammering.
        text = _call_and_extract_text(client, model=resolved_model, system=REWRITE_SYSTEM, messages=retry_messages)
        payload = _extract_json(text)

    return _coerce(payload, cleaned)
