from __future__ import annotations

from fastapi import APIRouter

from app.core.llm.client_factory import get_client_for
from app.core.llm.feedback_prompt import generate_feedback_summary, template_feedback_summary
from app.core.llm.router import TaskType
from app.core.scoring.hybrid_score import score_resume_against_jd
from app.core.scoring.readiness import score_standalone_readiness
from app.core.scoring.screening_report import screen_resume_against_jd
from app.core.scoring.suggestion_engine import top_suggestions
from app.schemas.api_models import FullReportRequest, JdMatchRequest, StandaloneScoreRequest, SuggestionsRequest

router = APIRouter(prefix="/score", tags=["scoring"])


@router.post("/jd-match")
def jd_match(request: JdMatchRequest) -> dict:
    """Mode 1: score a resume against a specific job description."""
    breakdown = score_resume_against_jd(request.resume, request.jd_text)
    return breakdown.to_xai_dict()


@router.post("/standalone")
def standalone(request: StandaloneScoreRequest) -> dict:
    """Mode 2: JD-less ATS readiness score."""
    breakdown = score_standalone_readiness(request.resume)
    return breakdown.to_xai_dict()


@router.post("/suggestions")
def suggestions(request: SuggestionsRequest) -> dict:
    """
    Task 3/4: ranked Top-5 Suggestions. Mode is inferred from whether
    jd_text was given -- same resume, different breakdown, different
    feedback tone (llm/feedback_prompt.py's WITH_JD_INSTRUCTIONS vs.
    NO_JD_INSTRUCTIONS).

    use_llm=False (default) returns deterministic template phrasing --
    no API key required. use_llm=True calls the real feedback model and
    falls back to the template on any failure (missing key, network,
    provider error) rather than surfacing a raw exception.
    """
    mode = "with_jd" if request.jd_text else "no_jd"
    if request.jd_text:
        breakdown = score_resume_against_jd(request.resume, request.jd_text)
    else:
        breakdown = score_standalone_readiness(request.resume)

    ranked = top_suggestions(request.resume, breakdown)
    ranked_payload = [
        {
            "category": s.category,
            "message": s.message,
            "target": s.target,
            "estimated_impact": round(s.estimated_impact, 4),
            "score_context": s.score_context,
        }
        for s in ranked
    ]

    summary_source = "template"
    summary = "\n".join(f"{i}. {line}" for i, line in enumerate(template_feedback_summary(ranked), start=1))
    if request.use_llm:
        try:
            client, model = get_client_for(TaskType.CONVERSATIONAL_AGENT)
            summary = generate_feedback_summary(
                client, ranked, mode=mode, jd_text=request.jd_text, model=model
            )
            summary_source = "llm"
        except Exception:
            # Deliberately broad: any failure in the live-model path
            # (missing key, network, provider error) should degrade to
            # the always-available template, not break the response.
            summary = "\n".join(f"{i}. {line}" for i, line in enumerate(template_feedback_summary(ranked), start=1))
            summary_source = "template"

    return {
        "mode": mode,
        "score": breakdown.to_xai_dict(),
        "suggestions": ranked_payload,
        "summary": summary,
        "summary_source": summary_source,
    }


@router.post("/full-report")
def full_report(request: FullReportRequest) -> dict:
    """
    Semantic Fit screening report: JD requirement extraction + tiering
    (knockout/critical/important/preferred/optional), evidence-aware
    matching per requirement, and the 7-dimension weighted score
    (screening_report.py). Answers the three questions the spec asks for:
    how well does this resume match, where is it losing points, and what
    should the candidate do about it.

    Deliberately a separate endpoint from /score/jd-match rather than a
    replacement -- that route's simpler 3-weight formula stays exactly as
    it is for any existing caller depending on its shape.
    """
    report = screen_resume_against_jd(request.resume, request.jd_text)
    return report.to_dict()
