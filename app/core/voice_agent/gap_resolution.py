"""
Interactive gap-resolution loop -- turns a Mode 1 scoring gap (a missing
skill from `ScoreBreakdown.missing_skills`) into a targeted follow-up
question, and, once the candidate answers, patches the resume and
recomputes the score so the before/after delta is visible immediately.

This closes the loop that `hybrid_score.py` alone leaves open: without
this module, a candidate gets a one-shot report and has to go edit their
resume elsewhere and re-upload to see whether a fix helped.

Deliberately channel-agnostic: `next_gap_prompt` returns plain text in
`GapResolutionPrompt.prompt`. It's driven by the existing voice agent
today (`voice_agent/agent_loop.py`, `api/routes/voice.py`), but nothing
here assumes a voice channel specifically -- the same object would serve
a chat-based follow-up equally well. `agent_loop.py`'s SCOPE/SCALE/
OUTCOME_METRIC slot loop still governs *how* a good bullet gets built once
the candidate starts answering; this module is what decides *which*
resume gap to ask about next and closes the loop back into the score.

Fabrication guardrail (same principle as the rest of the feedback engine,
see blueprint Section 6): `apply_gap_answer` appends the candidate's
answer as given. Production should route `answer_text` through an LLM
rewrite pass first, constrained to reframing what the candidate actually
said -- never inventing scope, scale, or numbers they didn't provide. That
rewrite step is intentionally out of scope here, the same way
`agent_loop.py`'s decision core is kept separate from the live slot-
extraction call.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.scoring.hybrid_score import ScoreBreakdown, score_resume_against_jd
from app.schemas.json_resume import JsonResume, Work, WorkHighlight


@dataclass
class GapResolutionPrompt:
    target_skill: str
    prompt: str


@dataclass
class GapResolutionResult:
    updated_resume: JsonResume
    before: ScoreBreakdown
    after: ScoreBreakdown
    score_delta: float


def next_gap_prompt(breakdown: ScoreBreakdown) -> GapResolutionPrompt | None:
    """
    Pick the highest-priority unresolved gap and phrase a targeted
    follow-up question for it. Returns None once there are no gaps left
    (the caller's signal to stop looping and show the final score).

    Priority is "first missing skill" for now -- `missing_skills` is
    already a deterministic sorted set at this point (mirrors how
    `to_xai_dict()` exposes `skill_gaps`). A future version can rank by
    estimated score impact per the blueprint's feedback-engine design
    (each fix's `estimated_score_impact`), the same way Stage 6's
    prioritized fix list is meant to work -- that ranking needs a
    what-if rerun per candidate gap, which is a straightforward extension
    of `apply_gap_answer` below but deliberately left out of this first
    pass to keep the loop cheap (one comparison, not N reruns, per turn).
    """
    if not breakdown.missing_skills:
        return None

    target = sorted(breakdown.missing_skills)[0]
    return GapResolutionPrompt(
        target_skill=target,
        prompt=(
            f'I don\'t see "{target}" backed by a project or role in your resume. '
            f"Have you used it hands-on anywhere? If so, tell me what you built or "
            f"did, and what happened."
        ),
    )


def apply_gap_answer(
    resume: JsonResume,
    jd_text: str,
    answer_text: str,
    job_index: int = 0,
) -> GapResolutionResult:
    """
    Patch the candidate's answer into the resume as a new highlight on the
    given job (defaults to the most recent/first role), then recompute the
    score against the same JD so the caller can show a before/after delta.

    Does not mutate the input `resume` -- returns a new JsonResume, same
    immutable-update pattern the rest of the schema layer uses.
    """
    before = score_resume_against_jd(resume, jd_text)

    work_list = list(resume.work) if resume.work else [Work(name="", position="")]
    if not (0 <= job_index < len(work_list)):
        job_index = 0

    target_job = work_list[job_index]
    new_highlights = list(target_job.highlights) + [WorkHighlight(text=answer_text)]
    work_list[job_index] = target_job.model_copy(update={"highlights": new_highlights})

    updated_resume = resume.model_copy(update={"work": work_list})
    after = score_resume_against_jd(updated_resume, jd_text)

    return GapResolutionResult(
        updated_resume=updated_resume,
        before=before,
        after=after,
        score_delta=round(after.final_score - before.final_score, 4),
    )
