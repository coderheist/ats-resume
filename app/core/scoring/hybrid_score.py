"""
Mode 1 (blueprint Section 3): score a resume against a specific JD.

    FinalScore = W_semantic * Semantic similarity
               + W_skill    * Explicit skill match
               + W_experience * Experience/tenure match

The three weights are no longer a fixed constant -- they shift with the
JD's detected seniority level (see SENIORITY_WEIGHT_PROFILES below). A
"5+ years required" line matters a lot less for an entry-level posting's
overall fit than it does for a staff-level one, and penalizing a fresher
against a senior-calibrated experience weight was scoring junior
candidates unfairly. The un-weighted defaults (0.5/0.3/0.2) are kept as
the MID profile, so any JD with no detectable seniority signal scores
exactly as it always did.

Semantic similarity goes through scaled_similarity() (embeddings.py),
which clamps into [0,1] before it's weighted in -- defensive against a
future SBERT swap producing a negative cosine similarity; see that
module's docstring for the reasoning. final_score itself is clamped into
[0,1] for the same reason, one layer up.

Content-quality signals (unquantified bullets, weak verbs, passive voice)
are computed here too and exposed on the breakdown, but deliberately do
NOT feed final_score -- there's no weight for them in the formula above,
and quietly baking them in would misrepresent what the JD-match score
means. They're informational, same as readiness.py's format_issues, and
exist so the Top-5 Suggestions engine (suggestion_engine.py) has bullet-
level detail available even during a JD-match scan, not just in the
JD-less readiness mode.

Every call also returns an XAI breakdown object -- per blueprint Section 5,
the score is never shown to a candidate as a single opaque number.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.scoring.content_quality import analyze_content_quality
from app.core.scoring.embeddings import get_embedding_provider, scaled_similarity
from app.core.scoring.experience_match import (
    RequiredExperience, experience_match_score, has_unparseable_dates,
)
from app.core.scoring.seniority import SeniorityLevel, detect_seniority
from app.core.scoring.skill_extraction import skill_match_score
from app.schemas.json_resume import JsonResume

# Baseline (MID) weights -- unchanged from the original static formula, and
# kept as module-level constants since test_hybrid_score.py and other
# callers reference them directly as "the default weights".
SEMANTIC_WEIGHT = 0.5
SKILL_WEIGHT = 0.3
EXPERIENCE_WEIGHT = 0.2

# Dynamic weight profile per detected seniority level. As seniority rises,
# demonstrated experience becomes a larger share of what differentiates
# candidates; for entry-level postings, requirement/skill coverage should
# dominate since most junior candidates won't have deep experience
# evidence to weigh in the first place.
SENIORITY_WEIGHT_PROFILES: dict[SeniorityLevel, tuple[float, float, float]] = {
    # (semantic, skill, experience) -- each tuple sums to 1.0
    SeniorityLevel.ENTRY: (0.55, 0.35, 0.10),
    SeniorityLevel.MID: (SEMANTIC_WEIGHT, SKILL_WEIGHT, EXPERIENCE_WEIGHT),
    SeniorityLevel.SENIOR: (0.45, 0.25, 0.30),
    SeniorityLevel.STAFF: (0.40, 0.20, 0.40),
}


@dataclass
class ScoreBreakdown:
    final_score: float
    semantic_similarity: float
    skill_match_score: float
    experience_match_score: float
    matched_skills: set[str] = field(default_factory=set)
    missing_skills: set[str] = field(default_factory=set)
    required_years: float | None = None
    required_years_max: float | None = None  # set only for an explicit JD range
    candidate_years: float = 0.0
    seniority_level: SeniorityLevel = SeniorityLevel.MID
    weights_used: tuple[float, float, float] = (SEMANTIC_WEIGHT, SKILL_WEIGHT, EXPERIENCE_WEIGHT)
    # Informational only -- see module docstring for why these don't feed final_score.
    unquantified_bullet_count: int = 0
    weak_verb_bullet_count: int = 0
    passive_voice_count: int = 0
    unparseable_experience_roles: list[str] = field(default_factory=list)

    def to_xai_dict(self) -> dict:
        """Shape consumed by the candidate-facing XAI panel."""
        w_semantic, w_skill, w_experience = self.weights_used
        return {
            "score": round(self.final_score * 100, 1),
            "breakdown": {
                "semantic_fit": round(self.semantic_similarity * 100, 1),
                "skill_match": round(self.skill_match_score * 100, 1),
                "experience_match": round(self.experience_match_score * 100, 1),
            },
            "matched_skills": sorted(self.matched_skills),
            "skill_gaps": sorted(self.missing_skills),
            "experience": {
                "required_years": self.required_years,
                "required_years_max": self.required_years_max,
                "candidate_years": self.candidate_years,
                "unparseable_roles": self.unparseable_experience_roles,
            },
            "seniority_detected": self.seniority_level.value,
            "weights_used": {
                "semantic": w_semantic,
                "skill": w_skill,
                "experience": w_experience,
            },
            "content_quality": {
                "unquantified_bullets": self.unquantified_bullet_count,
                "weak_verb_bullets": self.weak_verb_bullet_count,
                "passive_voice_bullets": self.passive_voice_count,
                "note": "Informational -- not part of the JD match score above.",
            },
        }


def score_resume_against_jd(resume: JsonResume, jd_text: str) -> ScoreBreakdown:
    provider = get_embedding_provider()
    resume_text = resume.all_text()

    vectors = provider.embed([resume_text, jd_text])
    semantic = scaled_similarity(vectors[0], vectors[1])

    skill_score, matched, missing = skill_match_score(
        resume_text, sorted(resume.all_skill_keywords()), jd_text
    )
    exp_score, required, candidate_years = experience_match_score(resume, jd_text)
    required_years = required.min_years if required else None
    required_years_max = required.max_years if required else None

    seniority = detect_seniority(jd_text)
    w_semantic, w_skill, w_experience = SENIORITY_WEIGHT_PROFILES[seniority]

    final = (
        w_semantic * semantic
        + w_skill * skill_score
        + w_experience * exp_score
    )
    final = max(0.0, min(1.0, final))

    quality = analyze_content_quality(resume)

    return ScoreBreakdown(
        final_score=final,
        semantic_similarity=semantic,
        skill_match_score=skill_score,
        experience_match_score=exp_score,
        matched_skills=matched,
        missing_skills=missing,
        required_years=required_years,
        required_years_max=required_years_max,
        candidate_years=candidate_years,
        seniority_level=seniority,
        weights_used=(w_semantic, w_skill, w_experience),
        unquantified_bullet_count=len(quality.unquantified_bullets),
        weak_verb_bullet_count=len(quality.weak_verb_bullets),
        passive_voice_count=quality.passive_voice_count,
        unparseable_experience_roles=has_unparseable_dates(resume),
    )
