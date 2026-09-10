from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth.dependencies import AuthenticatedUser, get_optional_user
from app.core.llm.client_factory import get_client_for
from app.core.llm.feedback_prompt import generate_feedback_summary, template_feedback_summary
from app.core.llm.router import TaskType
from app.core.scoring.hybrid_score import score_resume_against_jd
from app.core.scoring.readiness import AVAILABLE_ROLES, ROLE_ONTOLOGY, score_standalone_readiness
from app.core.scoring.screening_report import screen_resume_against_jd
from app.core.scoring.suggestion_engine import top_suggestions
from app.core.services.entitlement_service import check_scan_allowance, iso_utc, record_scan
from app.core.services.resume_store import save_resume, save_scan_result
from app.core.services.user_service import get_or_create_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.api_models import FullReportRequest, JdMatchRequest, StandaloneScoreRequest, SuggestionsRequest

router = APIRouter(prefix="/score", tags=["scoring"])


def _resolve_user(db: Session, auth_user: AuthenticatedUser | None) -> User | None:
    """None for anonymous requests -- every downstream call in this file
    (entitlement check, usage recording, persistence) already treats a
    None user as "anonymous, don't restrict, don't save" on its own, so
    this is the only place that needs to know how to turn a verified
    Firebase identity into a local User row."""
    return get_or_create_user(db, auth_user) if auth_user else None


def _enforce_entitlement(db: Session, user: User | None) -> None:
    """The 429 body is an object, not a bare string, because the UI has
    to do more than print it: it pops a "you're out of scans" dialog that
    names the exact reset moment in the viewer's timezone and links to
    the upgrade page. `message` stays a complete human-readable sentence
    so a plain API consumer that only reads `detail.message` still gets
    the whole story, reset date included."""
    check = check_scan_allowance(db, user)
    if check.allowed:
        return
    raise HTTPException(status_code=429, detail={
        "error": "scan_limit_reached",
        "message": check.reason,
        "used": check.used,
        "limit": check.limit,
        "tier": check.tier,
        "resets_at": iso_utc(check.resets_at) if check.resets_at else None,
    })


@router.get("/roles")
def list_roles() -> dict:
    """The roles /score/standalone accepts as `target_role`.

    Served rather than hard-coded in the frontend so a picker cannot
    drift out of sync with the ontology the backend actually scores
    against -- a stale option there would be indistinguishable from a
    working one until it returned a 400. `expected_skills` is included
    because it is the honest explanation of what choosing a role means:
    coverage is measured against exactly that set, and a candidate can
    see what is being looked for.
    """
    return {
        "roles": [
            {"id": role, "label": role.replace("_", " ").title(), "expected_skills": sorted(ROLE_ONTOLOGY[role])}
            for role in AVAILABLE_ROLES
        ]
    }


@router.post("/jd-match")
def jd_match(request: JdMatchRequest) -> dict:
    """Mode 1: score a resume against a specific job description.

    Deliberately NOT wired to auth/entitlements/persistence -- this is
    the original, simpler 3-weight endpoint kept exactly as it was for
    any existing caller depending on its shape (see full_report's
    docstring); /score/full-report is where the account-aware behavior
    below lives, since that's the endpoint the actual product UI calls.
    """
    breakdown = score_resume_against_jd(request.resume, request.jd_text)
    return breakdown.to_xai_dict()


@router.post("/standalone")
def standalone(
    request: StandaloneScoreRequest,
    auth_user: AuthenticatedUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    """Mode 2: JD-less ATS readiness score. Public and unrestricted for
    anonymous callers, unchanged; signed-in users get their scan saved
    to history and counted against their monthly entitlement.

    `target_role` (optional) scores skill coverage against a role the
    caller names instead of one inferred from the resume -- see
    GET /roles below for the accepted values, and the response's
    `role_source` for which of the two produced the role it reports.
    """
    user = _resolve_user(db, auth_user)
    _enforce_entitlement(db, user)

    try:
        breakdown = score_standalone_readiness(request.resume, target_role=request.target_role)
    except ValueError:
        # An unrecognised role is the caller's mistake, not a server
        # error. Naming the valid options matters more than usual here:
        # these are internal ids ("ai_engineer"), not free text, so a
        # rejection without the list gives no way to guess the right one.
        raise HTTPException(
            status_code=400,
            detail=f"Unknown target_role '{request.target_role}'. Valid roles: {', '.join(AVAILABLE_ROLES)}.",
        ) from None

    result = breakdown.to_xai_dict()

    if user:
        resume_row = save_resume(db, user, request.resume)
        save_scan_result(db, resume_row.id, mode="standalone", jd_text=None, final_score=result["score"], breakdown=result)
        record_scan(db, user, action="standalone_scan")

    return result


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
def full_report(
    request: FullReportRequest,
    auth_user: AuthenticatedUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
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

    Public and unrestricted for anonymous callers (identical response
    shape to before Phase 3/4/9 -- get_optional_user resolves to None,
    check_scan_allowance is a no-op for None, nothing is persisted).
    Signed-in users get this scan saved to history and counted against
    their monthly entitlement (config.py's Tier.jd_match_scans_per_month).
    """
    user = _resolve_user(db, auth_user)
    _enforce_entitlement(db, user)

    report = screen_resume_against_jd(request.resume, request.jd_text, request.format_risk_count)
    result = report.to_dict()

    if user:
        resume_row = save_resume(db, user, request.resume)
        save_scan_result(
            db, resume_row.id, mode="jd_match", jd_text=request.jd_text,
            final_score=result["overall_score"], breakdown=result,
        )
        record_scan(db, user, action="jd_match_scan")

    return result
