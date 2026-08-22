"""
Bulk resume-backlog processing: a user uploads a pile of old resumes just
to have them parsed and sitting in their profile for later use -- nobody
is watching a progress bar for resume #7 of 10. Blueprint Sections 4.1/4.3.

Per document, two LLM calls happen in this pipeline (after Docling/Marker
parsing, which isn't an LLM call and doesn't factor in here):
  1. FAST_CLASSIFICATION (Claude Haiku 4.5) -- role/section classification,
     used to route/tag the resume in the profile.
  2. EXTRACTION_CROSSCHECK (open-weight, see router.py) -- independent
     structured-field extraction for validation against the primary parse.

These two steps use two DIFFERENT cost levers, deliberately not the same
one, because they're genuinely different kinds of infrastructure:

  - Step 1 goes through Anthropic's real Batch API
    (claude_client.AnthropicClient.create_message_batch): an unconditional
    50% off list price, submitted as one job, results collected later.
    build_classification_batch_requests() below builds that job.

  - Step 2 goes through the open-weight crosscheck model
    (oss_extraction_client.py). There is no per-vendor "batch job" concept
    there the way Anthropic/OpenAI define it -- self-hosted or hosted-
    open-weight inference doesn't have a list price to discount from in
    the first place. What actually helps at N=10 (or N=1000) is firing
    the N requests concurrently against an inference server that does its
    own request batching (vLLM's continuous batching): real throughput
    and cost efficiency, just via a different mechanism than a billing
    discount. run_crosscheck_concurrently() below is that path -- see its
    docstring before assuming it behaves like create_message_batch().

Not exercised in this sandbox (no live endpoints) -- see
tests/test_batch_resume_extraction.py, which covers both paths with fakes.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.llm.claude_client import BatchRequestSpec, LLMClient
from app.core.llm.oss_extraction_client import FakeOSSExtractionClient
from app.core.llm.router import TaskType, route

CLASSIFICATION_INSTRUCTIONS = """\
Classify this resume's most recent role into a single canonical job
family (e.g. "backend_engineer", "data_scientist", "product_manager",
"sales_account_executive") and seniority band ("junior", "mid",
"senior", "staff_plus"). Respond with only the two labels, nothing else.
Base the classification on the actual work described, not job titles
alone -- titles are inconsistent across companies.
"""


@dataclass
class BacklogResume:
    """One parsed (Docling/Marker output already run) resume waiting on
    the classification + crosscheck pass."""
    resume_id: str
    parsed_markdown: str


def build_classification_batch_requests(
    resumes: list[BacklogResume], *, model: str | None = None,
) -> list[BatchRequestSpec]:
    """
    One Anthropic Batch API request per resume. CLASSIFICATION_INSTRUCTIONS
    is identical across every request in the batch -- explicit cache
    breakpoint isn't even necessary to get automatic caching to help here
    (the API auto-caches the last block, which for a single-turn request
    with no volatile suffix is the whole system prompt), but marking it
    explicitly documents the intent and survives someone later adding a
    volatile suffix without silently breaking caching -- see
    prompt_cache.py's module docstring for why that matters.
    """
    from app.core.llm.prompt_cache import build_system_blocks

    model = model or route(TaskType.FAST_CLASSIFICATION)
    system_blocks = build_system_blocks(stable_instructions=CLASSIFICATION_INSTRUCTIONS, ttl="5m")

    return [
        BatchRequestSpec(
            custom_id=resume.resume_id,
            model=model,
            system=system_blocks,
            messages=[{"role": "user", "content": resume.parsed_markdown}],
            max_tokens=20,
        )
        for resume in resumes
    ]


def submit_classification_batch(client: LLMClient, resumes: list[BacklogResume]) -> str:
    """Submits the batch, returns the batch id to poll later. See
    claude_client.AnthropicClient.get_batch_status /
    retrieve_batch_results for the rest of the lifecycle."""
    requests = build_classification_batch_requests(resumes)
    batch = client.create_message_batch(requests)
    return batch["id"]


# -- Step 2: open-weight crosscheck, concurrent (not Anthropic-batched) ---

CROSSCHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_years_experience": {"type": "number"},
        "most_recent_title": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["candidate_years_experience", "most_recent_title", "skills"],
}


@dataclass
class CrosscheckResult:
    resume_id: str
    extracted: dict | None
    succeeded: bool
    error: str | None = None


async def run_crosscheck_concurrently(
    client, resumes: list[BacklogResume], *, max_in_flight: int = 10,
) -> list[CrosscheckResult]:
    """
    Fires the open-weight crosscheck extraction for every resume in the
    backlog concurrently (bounded by `max_in_flight`), relying on the
    inference server's own request batching for throughput -- this is NOT
    Anthropic's Message Batches API and does not carry an equivalent
    guaranteed price discount (see module docstring). `client` must expose
    a sync `create_message(...)`; this wraps it in a thread so N calls
    genuinely overlap instead of running one at a time.
    """
    model = route(TaskType.EXTRACTION_CROSSCHECK)
    semaphore = asyncio.Semaphore(max_in_flight)

    async def _one(resume: BacklogResume) -> CrosscheckResult:
        async with semaphore:
            try:
                raw = await asyncio.to_thread(
                    client.create_message,
                    model=model,
                    system=CLASSIFICATION_INSTRUCTIONS,
                    messages=[{"role": "user", "content": resume.parsed_markdown}],
                    json_schema=CROSSCHECK_SCHEMA,
                )
            except Exception as exc:  # noqa: BLE001 -- surfaced per-resume, not raised
                return CrosscheckResult(resume.resume_id, None, succeeded=False, error=str(exc))

            content = raw["choices"][0]["message"]["content"]
            import json
            try:
                extracted = json.loads(content)
            except (json.JSONDecodeError, KeyError, IndexError) as exc:
                return CrosscheckResult(resume.resume_id, None, succeeded=False, error=str(exc))
            return CrosscheckResult(resume.resume_id, extracted, succeeded=True)

    return list(await asyncio.gather(*(_one(r) for r in resumes)))


def _fake_client_for_dev() -> FakeOSSExtractionClient:
    """Convenience for local smoke-testing this module without a live
    inference endpoint -- not used by the app itself."""
    return FakeOSSExtractionClient()
