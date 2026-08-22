"""
Batch generation of per-candidate XAI narratives for the recruiter-facing
"candidate_pool_ranking" / "per_candidate_xai" features (Team/Business
tiers, see app/config.py). Blueprint Section 4.3 (DEEP_REASONING) + 6.

The use case this exists for: a recruiter uploads a JD and N candidates
(tens to hundreds), and later opens a dashboard to see each candidate
ranked with a written explanation of their fit. Nobody is staring at a
spinner waiting for candidate #47's narrative -- this is the textbook case
for the Batch API instead of N synchronous calls (see
app/core/llm/claude_client.py's create_message_batch).

This is also the best caching opportunity in the whole codebase: every
candidate in one ranking job shares the exact same JD text and scoring
rubric instructions -- only the per-candidate score breakdown differs. So
the batch's shared prefix is cached ONCE and read N-1 more times, instead
of being paid for in full N times. Batch discount (50%) and cache reads
(90% off the base rate) stack -- see token_pricing.py -- so at N=50 the
JD+rubric portion of the bill drops to roughly 1/20th of what N separate
uncached calls would cost.

Model: DEEP_REASONING (Claude Opus 4.8) -- this is exactly the "low
frequency, high stakes" case that tier exists for. A ranking job runs
once per JD, not once per page view, and a wrong or misleading narrative
in front of a recruiter making real hiring decisions is the expensive
failure mode here, not the token bill.

Not exercised in this sandbox (no ANTHROPIC_API_KEY) -- see
tests/test_batch_candidate_narratives.py for coverage using
FakeAnthropicClient, which exercises the actual request-building and
result-parsing logic end-to-end.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.llm.claude_client import BatchRequestSpec, LLMClient
from app.core.llm.prompt_cache import build_system_blocks
from app.core.llm.router import TaskType, route

RUBRIC_INSTRUCTIONS = """\
You are writing a short, candid explanation of one candidate's fit for a
job description, for a recruiter who will read many of these back to back
while ranking a candidate pool.

You will be given the job description once, then for each candidate: their
hybrid match score breakdown (semantic fit, skill match, experience match),
their matched skills, and their skill gaps.

Write exactly 2-3 sentences. Lead with the single strongest reason this
candidate is or isn't a fit -- not a summary of every number. Name specific
matched or missing skills rather than restating the scores as percentages;
a recruiter can already see the percentages on screen. Never soften a real
gap into vague language ("could be a good fit with some ramp-up") -- if the
skill match or experience match is weak, say so plainly and say why.

Do not repeat the candidate's name back if given; the dashboard already
shows it. Do not invent skills or experience not present in the score
breakdown you were given.
"""


@dataclass
class CandidateScoreInput:
    """One candidate's already-computed score, ready to narrate. Produced
    by app/core/scoring/hybrid_score.py -- this module only handles turning
    that structured breakdown into a batch of narrative-generation
    requests, not scoring itself."""
    candidate_id: str
    xai_breakdown: dict  # ScoreBreakdown.to_xai_dict() output


def build_narrative_batch_requests(
    *,
    jd_text: str,
    candidates: list[CandidateScoreInput],
    model: str | None = None,
) -> list[BatchRequestSpec]:
    """
    Builds one BatchRequestSpec per candidate, all sharing an identical
    cached system prefix (RUBRIC_INSTRUCTIONS + the JD text) so the batch
    reads that shared context from cache after the first entry writes it.

    Per the docs, cache hit rates within a batch are best-effort (batches
    run concurrently, and a cache entry only exists after the first
    response to write it begins) -- typically 30-98% depending on how the
    batch is scheduled, not a guarantee. Still strictly better than paying
    for N full copies of the JD + rubric with no caching at all.
    """
    model = model or route(TaskType.DEEP_REASONING)

    # The JD is identical for every candidate in one ranking job, so it
    # belongs in the STABLE cached prefix alongside the rubric -- not
    # repeated per-candidate in the message. Only the per-candidate score
    # breakdown varies, so that's what goes in `messages`.
    stable_prefix = f"{RUBRIC_INSTRUCTIONS}\n\n## Job description\n\n{jd_text}"
    system_blocks = build_system_blocks(stable_instructions=stable_prefix, ttl="5m")

    requests = []
    for candidate in candidates:
        requests.append(
            BatchRequestSpec(
                custom_id=candidate.candidate_id,
                model=model,
                system=system_blocks,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Candidate score breakdown:\n"
                            f"{candidate.xai_breakdown}"
                        ),
                    }
                ],
                max_tokens=200,
            )
        )
    return requests


@dataclass
class CandidateNarrativeResult:
    candidate_id: str
    narrative: str | None
    succeeded: bool
    error: str | None = None


def parse_narrative_batch_results(raw_results: list[dict]) -> list[CandidateNarrativeResult]:
    """
    Turns AnthropicClient.retrieve_batch_results() output back into
    per-candidate narratives, joined by custom_id (== candidate_id).
    """
    parsed = []
    for entry in raw_results:
        candidate_id = entry.get("custom_id", "")
        result = entry.get("result", {})
        if result.get("type") == "succeeded":
            content_blocks = result.get("message", {}).get("content", [])
            text = next((b["text"] for b in content_blocks if b.get("type") == "text"), None)
            parsed.append(CandidateNarrativeResult(candidate_id, text, succeeded=True))
        else:
            parsed.append(
                CandidateNarrativeResult(
                    candidate_id, None, succeeded=False,
                    error=result.get("error", {}).get("message", result.get("type", "unknown error")),
                )
            )
    return parsed


def run_candidate_pool_narratives(
    client: LLMClient, *, jd_text: str, candidates: list[CandidateScoreInput],
) -> str:
    """
    Convenience entry point: submits the batch and returns the batch id.
    Results aren't ready synchronously -- poll client.get_batch_status(id)
    until processing_status == "ended", then call
    client.retrieve_batch_results(id) and pass that to
    parse_narrative_batch_results().
    """
    requests = build_narrative_batch_requests(jd_text=jd_text, candidates=candidates)
    batch = client.create_message_batch(requests)
    return batch["id"]
