from __future__ import annotations

from pydantic import BaseModel

from app.schemas.json_resume import JsonResume


class JdMatchRequest(BaseModel):
    resume: JsonResume
    jd_text: str


class StandaloneScoreRequest(BaseModel):
    resume: JsonResume


class BiasAuditRequest(BaseModel):
    jd_text: str


class ResumeParseTextRequest(BaseModel):
    text: str
    # "basic" (Groq) | "medium" (Gemini) | "advanced" (Claude) -- see
    # router.py's Tier enum. Omit to fall back to the LLM_PROVIDER env
    # var (pre-tier-selector default behavior); an invalid value here
    # becomes a 400, not a silent fallback to heuristic (see resume.py).
    tier: str | None = None


class ResumeParseResponse(BaseModel):
    resume: JsonResume
    parse_method: str  # "llm" | "heuristic" -- see resume_extraction.py
    warnings: list[str] = []
    provider_used: str | None = None  # "claude" | "gemini" | "groq" | None (heuristic-only)


class VoiceTurnRequest(BaseModel):
    session_id: str
    transcript: str
    # In production, extracted server-side by an LLM call (router.py ->
    # TaskType.CONVERSATIONAL_AGENT). Accepted directly here so the endpoint
    # contract and the decision logic are testable independent of a live
    # model call.
    extracted_slots: dict[str, str] = {}


class GapPromptRequest(BaseModel):
    """Stage 8 (interactive gap-resolution loop): resume + JD in, the
    highest-priority missing-skill question out. See
    voice_agent/gap_resolution.py."""

    resume: JsonResume
    jd_text: str


class GapAnswerRequest(BaseModel):
    """Stage 8, step 2: the candidate's free-text answer to a gap prompt.
    `job_index` defaults to the first/most recent role."""

    resume: JsonResume
    jd_text: str
    answer_text: str
    job_index: int = 0
