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

Every call also returns an XAI breakdown object -- per blueprint Section 5,
the score is never shown to a candidate as a single opaque number.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.scoring.embeddings import cosine_similarity, get_embedding_provider
from app.core.scoring.experience_match import experience_match_score, extract_required_years_range
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
    required_years_upper: float | None = None
    candidate_years: float = 0.0
    seniority_level: SeniorityLevel = SeniorityLevel.MID
    weights_used: tuple[float, float, float] = (SEMANTIC_WEIGHT, SKILL_WEIGHT, EXPERIENCE_WEIGHT)

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
                "required_years_upper": self.required_years_upper,
                "candidate_years": self.candidate_years,
            },
            "seniority_detected": self.seniority_level.value,
            "weights_used": {
                "semantic": w_semantic,
                "skill": w_skill,
                "experience": w_experience,
            },
        }


def score_resume_against_jd(resume: JsonResume, jd_text: str) -> ScoreBreakdown:
    provider = get_embedding_provider()
    resume_text = resume.all_text()

    vectors = provider.embed([resume_text, jd_text])
    semantic = cosine_similarity(vectors[0], vectors[1])

    skill_score, matched, missing = skill_match_score(
        resume_text, sorted(resume.all_skill_keywords()), jd_text
    )
    exp_score, required_years, candidate_years = experience_match_score(resume, jd_text)
    required_range = extract_required_years_range(jd_text)

    seniority = detect_seniority(jd_text)
    w_semantic, w_skill, w_experience = SENIORITY_WEIGHT_PROFILES[seniority]

    final = (
        w_semantic * semantic
        + w_skill * skill_score
        + w_experience * exp_score
    )

    return ScoreBreakdown(
        final_score=final,
        semantic_similarity=semantic,
        skill_match_score=skill_score,
        experience_match_score=exp_score,
        matched_skills=matched,
        missing_skills=missing,
        required_years=required_years,
        required_years_upper=required_range[1] if required_range else None,
        candidate_years=candidate_years,
        seniority_level=seniority,
        weights_used=(w_semantic, w_skill, w_experience),
    )
