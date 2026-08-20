"""
Mode 2 (blueprint Section 3): "how ATS-ready is this resume" with no JD.

Three checks, per blueprint:
1. Ontology-driven role benchmarking (zero-shot role classification +
   expected-skills comparison) -- stubbed here behind a small starter
   ontology; production swaps in the full RRSO/knowledge-graph lookup.
2. Structural completeness against the JSON Resume schema.
3. Action-verb and quantified-metric density in work highlights.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.json_resume import JsonResume

STRONG_ACTION_VERBS = {
    "led", "built", "launched", "scaled", "designed", "architected",
    "reduced", "increased", "shipped", "drove", "optimized", "automated",
    "negotiated", "delivered", "spearheaded", "migrated", "implemented",
}

_METRIC_PATTERN = re.compile(r"\d")

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


def _highlight_stats(resume: JsonResume) -> tuple[float, float]:
    all_highlights = [h.text for job in resume.work for h in job.highlights]
    if not all_highlights:
        return 0.0, 0.0

    verb_hits = 0
    metric_hits = 0
    for text in all_highlights:
        first_word = text.strip().split(" ", 1)[0].lower().rstrip(".,;:")
        if first_word in STRONG_ACTION_VERBS:
            verb_hits += 1
        if _METRIC_PATTERN.search(text):
            metric_hits += 1

    n = len(all_highlights)
    return verb_hits / n, metric_hits / n


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
    verb_density, metric_density = _highlight_stats(resume)
    role, missing_skills = _infer_role(resume)

    return ReadinessBreakdown(
        structural_score=structural_score,
        action_verb_density=verb_density,
        quantified_metric_density=metric_density,
        inferred_role=role,
        missing_ontology_skills=missing_skills,
        missing_sections=missing_sections,
    )
