from __future__ import annotations

import time

from fastapi import APIRouter

from app.core.scoring.hybrid_score import score_resume_against_jd
from app.core.voice_agent.agent_loop import (
    CLARIFYING_QUESTIONS, NextAction, Slot, run_turn,
)
from app.core.voice_agent.gap_resolution import apply_gap_answer, next_gap_prompt
from app.schemas.api_models import GapAnswerRequest, GapPromptRequest, VoiceTurnRequest

router = APIRouter(prefix="/voice", tags=["voice-agent"])

# In-memory session store for this scaffold. Production: Redis, keyed by
# session_id, with a TTL matching the voice session length.
#
# Two bounds until then, because `session_id` is caller-supplied and this
# endpoint is unauthenticated -- an append-only dict keyed on arbitrary
# client input grows for the lifetime of the process, and nothing here
# ever removed an entry. A conversation that is simply abandoned (the
# normal way a voice session ends) leaks too, so this does not need an
# attacker to matter.
SESSION_TTL_SECONDS = 60 * 30
MAX_SESSIONS = 10_000

_SESSIONS: dict[str, tuple[float, dict[Slot, str]]] = {}


def _prune_sessions(now: float) -> None:
    """Drop expired sessions, then oldest-first if still over the cap.

    The TTL is the real mechanism; the cap is a backstop for a burst that
    arrives faster than entries expire, so memory stays bounded by
    MAX_SESSIONS regardless of traffic shape rather than by how well
    behaved callers are.
    """
    for key in [k for k, (touched, _) in _SESSIONS.items() if now - touched > SESSION_TTL_SECONDS]:
        del _SESSIONS[key]

    if len(_SESSIONS) > MAX_SESSIONS:
        for key, _ in sorted(_SESSIONS.items(), key=lambda kv: kv[1][0])[: len(_SESSIONS) - MAX_SESSIONS]:
            del _SESSIONS[key]


@router.post("/turn")
def voice_turn(request: VoiceTurnRequest) -> dict:
    """
    One turn of the voice-editing conversation.

    NOTE: `extracted_slots` is accepted directly in this scaffold. In
    production, the transcript is first passed to the conversational agent
    (router.TaskType.CONVERSATIONAL_AGENT -- Claude Sonnet 5 by default, or
    Gemini/Groq if LLM_PROVIDER is set, see client_factory.get_client_for)
    which extracts slot values via tool calling (tool_schema.py) before this
    decision logic runs -- see blueprint Section 4.3, "Handling ambiguous
    speech".
    """
    slots = {Slot(k): v for k, v in request.extracted_slots.items()}

    now = time.monotonic()
    touched, accumulated = _SESSIONS.get(request.session_id, (now, {}))
    if now - touched > SESSION_TTL_SECONDS:
        # Expired but not yet pruned: start fresh rather than silently
        # resuming a conversation the caller abandoned half an hour ago.
        accumulated = {}

    decision = run_turn(slots, accumulated)
    # The timestamp is refreshed on every turn, so the TTL measures
    # silence rather than total conversation length -- an active session
    # is never evicted mid-conversation.
    _SESSIONS[request.session_id] = (now, decision.filled_slots)

    # Pruned AFTER storing, so MAX_SESSIONS is a real ceiling. Pruning
    # first left the store at MAX_SESSIONS and then added this turn's
    # entry on top, so the bound was quietly off by one on every request.
    _prune_sessions(now)

    if decision.action == NextAction.ASK_CLARIFYING_QUESTION:
        return {
            "action": decision.action.value,
            "question": CLARIFYING_QUESTIONS[decision.missing_slot],
            "missing_slot": decision.missing_slot.value,
        }

    return {
        "action": decision.action.value,
        "ready_to_generate": True,
        "filled_slots": {k.value: v for k, v in decision.filled_slots.items()},
    }


@router.post("/gap-prompt")
def gap_prompt(request: GapPromptRequest) -> dict:
    """
    Stage 8, step 1: score the resume against the JD, and hand back a
    targeted follow-up question for the highest-priority missing skill --
    or `done: true` once there's nothing left to ask about. Intended to be
    called in a loop with /voice/gap-answer: prompt -> candidate answers ->
    answer -> updated score -> prompt again.
    """
    breakdown = score_resume_against_jd(request.resume, request.jd_text)
    prompt = next_gap_prompt(breakdown)

    if prompt is None:
        return {"done": True, "score": breakdown.to_xai_dict()}

    return {
        "done": False,
        "target_skill": prompt.target_skill,
        "prompt": prompt.prompt,
        "current_score": breakdown.to_xai_dict(),
    }


@router.post("/gap-answer")
def gap_answer(request: GapAnswerRequest) -> dict:
    """
    Stage 8, step 2: patch the candidate's answer into the resume and
    recompute the score, returning the before/after delta and the updated
    resume so the frontend can persist it and loop back to /gap-prompt.
    """
    result = apply_gap_answer(
        request.resume, request.jd_text, request.answer_text, request.job_index
    )
    return {
        "updated_resume": result.updated_resume.model_dump(),
        "before": result.before.to_xai_dict(),
        "after": result.after.to_xai_dict(),
        "score_delta": result.score_delta,
    }
