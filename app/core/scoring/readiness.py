"""
Mode 2 (blueprint Section 3): "how ATS-ready is this resume" with no JD.

Three checks, per blueprint:
1. Ontology-driven role benchmarking (zero-shot role classification +
   expected-skills comparison) -- stubbed here behind a small starter
   ontology; production swaps in the full RRSO/knowledge-graph lookup.
2. Structural completeness against the JSON Resume schema.
3. Action-verb, quantified-metric, and passive-voice signal in work
   highlights -- delegated to scoring/content_quality.py (shared with
   Mode 1's JD-match path; see that module's docstring).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.scoring.content_quality import analyze_content_quality
from app.schemas.json_resume import JsonResume

# Starter ontology: role -> expected canonical skills. Production version is
# the full Resume Recommender System Ontology described in the blueprint.
ROLE_ONTOLOGY: dict[str, set[str]] = {
    "software_engineer": {"software_engineering", "cpp", "react", "postgresql", "machine_learning"},
    "data_scientist": {"machine_learning", "nlp", "neural_networks", "postgresql"},
}


@dataclass
class ReadinessBreakdown:
    structural_score: float
    action_verb_density: float
    quantified_metric_density: float
    inferred_role: str | None
    missing_ontology_skills: set[str] = field(default_factory=set)
    missing_sections: list[str] = field(default_factory=list)
    # "Format errors" category for the Top-5 Suggestions engine (Task 3).
    # Deliberately just structural-completeness + contact-field checks
    # reused/extended, not a real column/table/glyph parseability engine
    # -- that's a separate, larger future module. Informational only:
    # does not feed overall_score() below.
    format_issues: list[str] = field(default_factory=list)
    passive_voice_count: int = 0

    def overall_score(self) -> float:
        return round(
            0.4 * self.structural_score
            + 0.3 * self.quantified_metric_density
            + 0.3 * self.action_verb_density,
            3,
        )

    def to_xai_dict(self) -> dict:
        return {
            "score": round(self.overall_score() * 100, 1),
            "inferred_role": self.inferred_role,
            "structural_completeness": round(self.structural_score * 100, 1),
            "action_verb_density": round(self.action_verb_density * 100, 1),
            "quantified_metric_density": round(self.quantified_metric_density * 100, 1),
            "missing_sections": self.missing_sections,
            "missing_ontology_skills": sorted(self.missing_ontology_skills),
            "format_issues": self.format_issues,
            "passive_voice_count": self.passive_voice_count,
        }


def _structural_check(resume: JsonResume) -> tuple[float, list[str]]:
    checks = {
        "summary": bool(resume.basics.summary),
        "work_history": bool(resume.work),
        "education": bool(resume.education),
        "skills": bool(resume.skills),
    }
    missing = [name for name, present in checks.items() if not present]
    score = sum(checks.values()) / len(checks)
    return score, missing


def _contact_format_issues(resume: JsonResume) -> list[str]:
    """The two contact fields an ATS parser needs to extract a candidate
    record at all -- see ReadinessBreakdown.format_issues docstring."""
    issues = []
    if not resume.basics.email:
        issues.append("missing_email")
    if not resume.basics.phone:
        issues.append("missing_phone")
    return issues


def structural_completeness_score(resume: JsonResume) -> float:
    """Public entry point for screening_report.py's ATS Readability
    dimension -- same structural check score_standalone_readiness() uses
    internally, without re-deriving the missing-sections list too."""
    score, _ = _structural_check(resume)
    return score


def format_issues_for(resume: JsonResume) -> list[str]:
    """Public entry point for suggestion_engine.py -- the same checks
    score_standalone_readiness() below uses internally, exposed so
    JD-mode suggestions (Task 3) can draw on format/structural issues too
    without duplicating the check logic."""
    _, missing_sections = _structural_check(resume)
    return [*missing_sections, *_contact_format_issues(resume)]


def _infer_role(resume: JsonResume) -> tuple[str | None, set[str]]:
    resume_skills = resume.all_skill_keywords()
    best_role, best_overlap = None, 0
    for role, expected in ROLE_ONTOLOGY.items():
        overlap = len(expected & resume_skills)
        if overlap > best_overlap:
            best_role, best_overlap = role, overlap

    if best_role is None:
        return None, set()

    missing = ROLE_ONTOLOGY[best_role] - resume_skills
    return best_role, missing


def score_standalone_readiness(resume: JsonResume) -> ReadinessBreakdown:
    structural_score, missing_sections = _structural_check(resume)
    quality = analyze_content_quality(resume)
    role, missing_skills = _infer_role(resume)

    return ReadinessBreakdown(
        structural_score=structural_score,
        action_verb_density=quality.action_verb_density,
        quantified_metric_density=quality.quantified_metric_density,
        inferred_role=role,
        missing_ontology_skills=missing_skills,
        missing_sections=missing_sections,
        format_issues=format_issues_for(resume),
        passive_voice_count=quality.passive_voice_count,
    )
