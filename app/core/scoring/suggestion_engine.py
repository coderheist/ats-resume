"""
Top-5 Suggestions engine (Task 3): turns a score breakdown + resume into a
ranked, actionable fix list.

Ranking is analytical, not LLM-guessed: each suggestion's estimated_impact
is computed from weights that already exist in hybrid_score.py /
readiness.py, rather than asking an LLM to invent an impact number. The
LLM's job (llm/feedback_prompt.py) is narrower and lower-risk: phrase the
already-ranked list well, not decide the ranking.

Every suggestion carries a `score_context` -- "match_score" if fixing it
would actually move the number currently shown to the candidate, or
"readability" if it's a real, weight-grounded estimate against a
*different* formula that just isn't wired into the active score. This
matters concretely: in JD-match mode, content-quality issues (metrics,
verbs, passive voice) don't move final_score at all today (see
hybrid_score.py's module docstring) -- they're still worth surfacing, but
mislabeling them as moving the JD-match score would be exactly the kind
of false precision this project has tried to avoid everywhere else.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.scoring.content_quality import analyze_content_quality
from app.core.scoring.experience_match import has_unparseable_dates
from app.core.scoring.hybrid_score import ScoreBreakdown
from app.core.scoring.readiness import ReadinessBreakdown, format_issues_for
from app.schemas.json_resume import JsonResume

# readiness.py's own formula weights (ReadinessBreakdown.overall_score()),
# reused here only to *estimate* impact -- never to recompute a score.
_READINESS_METRIC_WEIGHT = 0.3
_READINESS_VERB_WEIGHT = 0.3
_READINESS_STRUCTURAL_WEIGHT = 0.4

_FORMAT_ISSUE_LABELS = {
    "summary": "Add a Summary section.",
    "work_history": "Add a Work Experience section.",
    "education": "Add an Education section.",
    "skills": "Add a Skills section.",
    "missing_email": "Add an email address to your contact info -- ATS parsers need it to build a candidate record.",
    "missing_phone": "Add a phone number to your contact info.",
}


def _truncate(text: str, n: int = 70) -> str:
    return text if len(text) <= n else text[:n] + "..."


@dataclass
class Suggestion:
    category: str  # missing_skill | unquantified_bullet | weak_verb | passive_voice | format_issue | missing_date | ontology_skill
    message: str  # deterministic, factual -- the "what", not the "how it's phrased"
    target: str | None  # job title/role this refers to, if applicable
    estimated_impact: float  # comparable within a single ranking call, not across calls
    score_context: str  # "match_score" | "readability" -- see module docstring


def _skill_suggestions(breakdown: ScoreBreakdown) -> list[Suggestion]:
    total_jd_skills = len(breakdown.matched_skills) + len(breakdown.missing_skills)
    if total_jd_skills == 0:
        return []
    w_skill = breakdown.weights_used[1]
    per_skill_impact = w_skill / total_jd_skills
    return [
        Suggestion(
            category="missing_skill",
            message=f'Add evidence of "{skill.replace("_", " ")}" -- it\'s in the job description but not found anywhere in your resume.',
            target=None,
            estimated_impact=per_skill_impact,
            score_context="match_score",
        )
        for skill in sorted(breakdown.missing_skills)
    ]


def _ontology_skill_suggestions(breakdown: ReadinessBreakdown) -> list[Suggestion]:
    if not breakdown.missing_ontology_skills:
        return []
    return [
        Suggestion(
            category="ontology_skill",
            message=f'Consider adding "{skill.replace("_", " ")}" -- it\'s a common skill for the {breakdown.inferred_role} roles your resume most resembles.',
            target=None,
            estimated_impact=0.15,  # flat: not wired into overall_score(), general-fit signal only
            score_context="readability",
        )
        for skill in sorted(breakdown.missing_ontology_skills)
    ]


def _content_quality_suggestions(resume: JsonResume, is_jd_mode: bool) -> list[Suggestion]:
    n_highlights = sum(len(job.highlights) for job in resume.work)
    if n_highlights == 0:
        return []

    # In JD-match mode these never move final_score (no weight for them
    # in that formula); in No-JD mode they directly move overall_score()
    # via readiness.py's own 0.3/0.3 weights.
    metric_verb_context = "readability" if is_jd_mode else "match_score"

    quality = analyze_content_quality(resume)
    suggestions: list[Suggestion] = []

    per_metric_impact = _READINESS_METRIC_WEIGHT / n_highlights
    for bullet in quality.unquantified_bullets:
        suggestions.append(Suggestion(
            category="unquantified_bullet",
            message=f'Add a measurable result to your {bullet.job_title} role: "{_truncate(bullet.highlight_text)}"',
            target=bullet.job_title,
            estimated_impact=per_metric_impact,
            score_context=metric_verb_context,
        ))

    per_verb_impact = _READINESS_VERB_WEIGHT / n_highlights
    for bullet in quality.weak_verb_bullets:
        suggestions.append(Suggestion(
            category="weak_verb",
            message=f'Open with a strong action verb on your {bullet.job_title} bullet: "{_truncate(bullet.highlight_text)}"',
            target=bullet.job_title,
            estimated_impact=per_verb_impact,
            score_context=metric_verb_context,
        ))

    # Passive-voice bullets overlap heavily with weak-verb bullets by
    # construction (a passive opener is rarely a strong verb) -- kept as
    # its own category anyway since "rewrite in active voice" is a more
    # specific, more actionable fix than "use a stronger verb", and
    # passive voice itself has no dedicated weight in either formula, so
    # it's always a readability estimate regardless of mode.
    for bullet in quality.passive_voice_bullets:
        suggestions.append(Suggestion(
            category="passive_voice",
            message=f'Rewrite in active voice on your {bullet.job_title} role: "{_truncate(bullet.highlight_text)}"',
            target=bullet.job_title,
            estimated_impact=per_verb_impact * 0.75,
            score_context="readability",
        ))

    return suggestions


def _format_suggestions(format_issues: list[str], is_jd_mode: bool) -> list[Suggestion]:
    if not format_issues:
        return []
    # Structural completeness is wired into overall_score() in No-JD mode
    # (0.4 weight); it isn't wired into final_score in JD-match mode.
    context = "readability" if is_jd_mode else "match_score"
    per_issue_impact = _READINESS_STRUCTURAL_WEIGHT / len(format_issues)
    return [
        Suggestion(
            category="format_issue",
            message=_FORMAT_ISSUE_LABELS.get(issue, f"Fix a formatting issue: {issue}"),
            target=None,
            estimated_impact=per_issue_impact,
            score_context=context,
        )
        for issue in format_issues
    ]


def _missing_date_suggestions(resume: JsonResume, breakdown: ScoreBreakdown | ReadinessBreakdown) -> list[Suggestion]:
    unparseable = has_unparseable_dates(resume)
    if not unparseable:
        return []
    # Only actually moves the JD-match score if the JD stated a years
    # requirement at all -- readiness mode doesn't use dates in its
    # formula in the first place.
    moves_score = isinstance(breakdown, ScoreBreakdown) and breakdown.required_years is not None
    return [
        Suggestion(
            category="missing_date",
            message=f"Add a start date to your {role} role -- without one, your experience there isn't being counted at all.",
            target=role,
            estimated_impact=0.1,  # flat: a data-integrity fix, not proportional to a specific weight
            score_context="match_score" if moves_score else "readability",
        )
        for role in unparseable
    ]


def top_suggestions(resume: JsonResume, breakdown: ScoreBreakdown | ReadinessBreakdown, limit: int = 5) -> list[Suggestion]:
    """Rank candidate fixes by estimated score impact and return the top `limit`."""
    is_jd_mode = isinstance(breakdown, ScoreBreakdown)

    suggestions: list[Suggestion] = []
    suggestions += _content_quality_suggestions(resume, is_jd_mode)
    suggestions += _missing_date_suggestions(resume, breakdown)
    suggestions += _format_suggestions(format_issues_for(resume), is_jd_mode)

    if isinstance(breakdown, ScoreBreakdown):
        suggestions += _skill_suggestions(breakdown)
    else:
        suggestions += _ontology_skill_suggestions(breakdown)

    suggestions.sort(key=lambda s: s.estimated_impact, reverse=True)
    return suggestions[:limit]
