from __future__ import annotations

from pydantic import BaseModel

from app.schemas.json_resume import JsonResume


class JdMatchRequest(BaseModel):
    resume: JsonResume
    jd_text: str


class StandaloneScoreRequest(BaseModel):
    resume: JsonResume


class SuggestionsRequest(BaseModel):
    """Task 3/4: Top-5 Suggestions, either mode. jd_text omitted -> No-JD
    mode (ReadinessBreakdown); jd_text provided -> With-JD mode
    (ScoreBreakdown). use_llm=False (default) returns the deterministic
    template phrasing with no API key required; True calls the real
    feedback-generation model and falls back to the template on error."""

    resume: JsonResume
    jd_text: str | None = None
    use_llm: bool = False


class FullReportRequest(BaseModel):
    """Semantic Fit screening report -- always With-JD (knockout
    detection needs a JD to classify requirements against).

    format_risk_count is optional and comes from a prior POST
    /resume/parse-file call's `format_analysis.risk_count`-equivalent
    (see format_analysis.py) -- the scoring layer only ever sees a
    JsonResume, not raw file bytes, so real layout/table/image risks
    have to be computed once at upload time and threaded through here by
    the caller. Omit it entirely (e.g. for a hand-written or pasted-text
    resume with no original file) and the ATS Readability dimension
    falls back to structural completeness only, same as before."""

    resume: JsonResume
    jd_text: str
    format_risk_count: int | None = None


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
    format_analysis: dict | None = None  # real layout/table/image checks -- file uploads only, see format_analysis.py


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


class CheckoutRequest(BaseModel):
    tier: str  # e.g. "starter", "pro", "pro_plus", "team", "business" -- see app/config.py
    billing_cycle: str = "monthly"  # "monthly" | "annual"
    currency: str = "USD"


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
