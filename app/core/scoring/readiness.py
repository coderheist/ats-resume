"""
Mode 2 (blueprint Section 3): "how ATS-ready is this resume" with no JD.

Rebuilt from an earlier version that had three real, verified problems
(not just style preferences):

1. The role ontology had exactly two entries (software_engineer,
   data_scientist) -- almost any resume outside those two literal labels
   got no role inference at all, and no skill-coverage insight.
2. Role inference compared against `resume.all_skill_keywords()` -- raw,
   lowercased strings straight from the Skills section field, never
   canonicalized. A skills list containing "React.js" or "Postgres"
   would never match the ontology's canonical "react"/"postgresql" ids,
   and anything mentioned only in a work bullet or project (not the
   Skills section) was invisible to inference entirely.
3. Skill coverage for the inferred role was computed but never actually
   scored -- `missing_ontology_skills` sat in the output purely as
   informational text, contributing nothing to `overall_score()`, even
   though "does this resume show the skills expected for its inferred
   role" is arguably the single most useful signal available with no JD
   to compare against.

Four checks now, weighted:
1. Structural completeness against the JSON Resume schema (0.30).
2. Quantified-metric density in work highlights (0.20).
3. Action-verb density in work highlights (0.15).
4. Active-voice ratio, i.e. 1 - passive-voice ratio (0.10) -- computed
   before but never scored; folded in now.
5. Ontology skill coverage for the inferred role (0.25) -- the fix for
   problem 3 above.
All five reuse scoring/content_quality.py (2-4) or this module's own
structural/ontology checks (1, 5); nothing here recomputes a signal that
already exists elsewhere.

Stated honestly: the ontology below is tech-role-scoped, because it's
built from the same CANONICAL_SKILLS vocabulary skill_extraction.py
already has (software engineering, cloud, data, DevOps) -- there's no
equivalent canonical vocabulary in this codebase for non-technical
fields (marketing, sales, finance, HR...) yet. A resume that doesn't
overlap with any of these roles gets `inferred_role=None` and a neutral
(not penalized) skill-coverage score, rather than a wrong or
misleadingly confident one -- the ontology being incomplete for a field
is not the same thing as that resume having a real skill gap, and
scoring it as if it were would be exactly the kind of false precision
this project has tried to avoid everywhere else. Production version is
the full Resume Recommender System Ontology described in the blueprint,
which would cover this properly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.scoring.content_quality import analyze_content_quality
from app.core.scoring.skill_extraction import extract_canonical_skills
from app.schemas.json_resume import JsonResume

# Tech-role ontology, deliberately built only from ids that actually exist
# in skill_extraction.py's CANONICAL_SKILLS map -- an id here that isn't a
# real canonical skill could never match anything, silently.
ROLE_ONTOLOGY: dict[str, set[str]] = {
    "software_engineer": {"software_engineering", "python", "javascript", "react", "sql", "git"},
    "backend_engineer": {"software_engineering", "python", "java", "postgresql", "rest_api", "sql"},
    "frontend_engineer": {"javascript", "typescript", "react", "vue", "angular", "git"},
    "full_stack_engineer": {"javascript", "react", "nodejs", "python", "sql", "git"},
    "data_scientist": {"machine_learning", "python", "pandas", "numpy", "sql", "tensorflow"},
    "data_engineer": {"python", "sql", "aws", "docker", "postgresql", "mongodb"},
    "data_analyst": {"sql", "excel", "tableau", "python", "pandas"},
    "devops_engineer": {"docker", "kubernetes", "terraform", "aws", "ci_cd", "git"},
    "ml_engineer": {"machine_learning", "python", "tensorflow", "pytorch", "docker", "aws"},
    # Distinct from ml_engineer: the applied/LLM side of the field, where
    # the day job is building on top of models rather than training them.
    # Its absence was a real gap -- an AI engineer resume had no correct
    # label available, and with a sparse skill parse it fell all the way
    # through to software_engineer.
    "ai_engineer": {"machine_learning", "python", "pytorch", "tensorflow", "docker", "rest_api"},
    "cloud_engineer": {"aws", "azure", "gcp", "terraform", "docker", "kubernetes"},
    "qa_engineer": {"python", "git", "ci_cd", "agile", "sql"},
}

# Sorted so the API, and any picker built from it, have a stable order.
AVAILABLE_ROLES: list[str] = sorted(ROLE_ONTOLOGY)

WEIGHTS = {
    "structural": 0.30,
    "quantified_metric": 0.20,
    "action_verb": 0.15,
    "active_voice": 0.10,
    "skill_coverage": 0.25,
}


@dataclass
class ReadinessBreakdown:
    structural_score: float
    action_verb_density: float
    quantified_metric_density: float
    inferred_role: str | None
    role_source: str = "inferred"  # "inferred" | "user_specified"
    skill_coverage_score: float = 1.0  # neutral (not penalized) when no role inferred
    highlight_count: int = 0
    passive_voice_count: int = 0
    missing_ontology_skills: set[str] = field(default_factory=set)
    missing_sections: list[str] = field(default_factory=list)
    # "Format errors" category for the Top-5 Suggestions engine (Task 3).
    # Deliberately just structural-completeness + contact-field checks
    # reused/extended, not a real column/table/glyph parseability engine
    # -- that's a separate module (parsing/format_analysis.py), which
    # operates on raw file bytes this function never sees. Informational
    # only: does not feed overall_score() below.
    format_issues: list[str] = field(default_factory=list)

    @property
    def active_voice_score(self) -> float:
        if self.highlight_count == 0:
            return 1.0
        return max(0.0, 1.0 - (self.passive_voice_count / self.highlight_count))

    def overall_score(self) -> float:
        return round(
            WEIGHTS["structural"] * self.structural_score
            + WEIGHTS["quantified_metric"] * self.quantified_metric_density
            + WEIGHTS["action_verb"] * self.action_verb_density
            + WEIGHTS["active_voice"] * self.active_voice_score
            + WEIGHTS["skill_coverage"] * self.skill_coverage_score,
            3,
        )

    def to_xai_dict(self) -> dict:
        return {
            "score": round(self.overall_score() * 100, 1),
            "inferred_role": self.inferred_role,
            # Whether the role above was stated by the caller or guessed.
            # Without this the UI cannot tell the two apart, and "we think
            # you are a software engineer" reads very differently from
            # "scored against the software engineer role you picked".
            "role_source": self.role_source,
            "structural_completeness": round(self.structural_score * 100, 1),
            "action_verb_density": round(self.action_verb_density * 100, 1),
            "quantified_metric_density": round(self.quantified_metric_density * 100, 1),
            "active_voice_score": round(self.active_voice_score * 100, 1),
            "skill_coverage_score": round(self.skill_coverage_score * 100, 1),
            "weights_used": dict(WEIGHTS),
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


def _infer_role(resume: JsonResume) -> tuple[str | None, set[str], float]:
    """
    Returns (inferred_role, missing_skills_for_that_role, skill_coverage_score).

    Uses extract_canonical_skills() over the resume's *entire* text (not
    just resume.all_skill_keywords(), which only reads the dedicated
    Skills section and returns raw, uncanonicalized strings) -- this
    catches a skill mentioned only in a work bullet or project, and
    normalizes phrasing variants ("React.js", "Postgres") to the same
    canonical id the ontology itself is built from.
    """
    resume_skills = extract_canonical_skills(resume.all_text(), known_terms=list(resume.all_skill_keywords()))

    # Rank by (overlap, coverage ratio, role name) rather than raw overlap
    # alone. Two things were wrong with the raw count:
    #
    # 1. It ignored role size, so a 3-of-5 match lost to a 3-of-6 match
    #    even though the former is the better fit.
    # 2. Ties were broken by dict insertion order, silently. Because
    #    software_engineer is declared first and its skill set is the most
    #    generic in the ontology (python, sql and git appear on nearly
    #    every technical resume), it won essentially every tie. A resume
    #    where only "python" was extracted produced an eight-way tie that
    #    always resolved to software_engineer -- which is how an AI
    #    engineer resume came back labelled a software engineer. The real
    #    trigger is upstream: a sparse parse yields few canonical skills,
    #    and few skills means ties.
    #
    # Sorting on the role name last only makes the outcome reproducible;
    # it is not a meaningful signal, which is exactly why a genuine tie is
    # better resolved by the caller stating their role -- see
    # score_standalone_readiness's target_role.
    ranked = sorted(
        (
            (len(expected & resume_skills), len(expected & resume_skills) / len(expected), role)
            for role, expected in ROLE_ONTOLOGY.items()
        ),
        reverse=True,
    )
    best_overlap, _, best_role = ranked[0]

    if best_overlap == 0:
        # No overlap with any role in this (tech-scoped) ontology -- don't
        # guess, and don't penalize; see module docstring.
        return None, set(), 1.0

    expected = ROLE_ONTOLOGY[best_role]
    missing = expected - resume_skills
    coverage = len(expected & resume_skills) / len(expected)
    return best_role, missing, coverage


def coverage_for_role(resume: JsonResume, role: str) -> tuple[set[str], float]:
    """Skill coverage against a role the CALLER named, skipping inference.

    Inference is a guess resting on two things that can each be wrong:
    how much the parser managed to extract, and how well a fixed
    tech-scoped ontology happens to describe this person. When someone
    states the role they are targeting, neither matters any more -- and
    the answer becomes more useful, since the question worth asking is
    usually "how ready am I for the job I want" rather than "what does my
    resume currently look like".
    """
    expected = ROLE_ONTOLOGY[role]
    resume_skills = extract_canonical_skills(resume.all_text(), known_terms=list(resume.all_skill_keywords()))
    return expected - resume_skills, len(expected & resume_skills) / len(expected)


def score_standalone_readiness(resume: JsonResume, target_role: str | None = None) -> ReadinessBreakdown:
    """`target_role` is the role the caller is aiming for, e.g.
    "ai_engineer" (see AVAILABLE_ROLES). Given one, skill coverage is
    measured against it and inference is skipped entirely; omitted, the
    role is inferred exactly as before, so existing callers are
    unaffected.

    An unknown role raises ValueError, which the route turns into a 400.
    Falling back to inference instead would answer a different question
    while looking like a successful request.
    """
    structural_score, missing_sections = _structural_check(resume)
    quality = analyze_content_quality(resume)

    if target_role is not None:
        if target_role not in ROLE_ONTOLOGY:
            raise ValueError("Unknown role '%s'." % target_role)
        role = target_role
        missing_skills, skill_coverage = coverage_for_role(resume, target_role)
    else:
        role, missing_skills, skill_coverage = _infer_role(resume)

    return ReadinessBreakdown(
        role_source="user_specified" if target_role is not None else "inferred",
        structural_score=structural_score,
        action_verb_density=quality.action_verb_density,
        quantified_metric_density=quality.quantified_metric_density,
        inferred_role=role,
        skill_coverage_score=skill_coverage,
        highlight_count=len(quality.bullet_issues),
        missing_ontology_skills=missing_skills,
        missing_sections=missing_sections,
        format_issues=format_issues_for(resume),
        passive_voice_count=quality.passive_voice_count,
    )
