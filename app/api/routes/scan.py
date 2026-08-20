from __future__ import annotations

from fastapi import APIRouter

from app.core.scoring.hybrid_score import score_resume_against_jd
from app.core.scoring.readiness import score_standalone_readiness
from app.schemas.api_models import JdMatchRequest, StandaloneScoreRequest

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
