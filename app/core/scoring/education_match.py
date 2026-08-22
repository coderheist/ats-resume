"""
Education Match sub-score (Semantic Fit spec, scoring dimension #6).

Compares the JD's stated minimum degree level (if any) against the
candidate's highest attained degree level, extracted from JsonResume's
`education[].study_type` field. Same lightweight regex-heuristic
philosophy as the rest of app/core/scoring/ -- production swap is a real
education-taxonomy lookup, not a hand-maintained rank table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.json_resume import JsonResume

# Degree name -> rank, higher outranks lower. "b.tech"/"bsc" etc. are
# common resume/JD phrasings that don't literally contain "bachelor".
_DEGREE_LEVELS: dict[str, int] = {
    "phd": 4, "ph.d": 4, "doctorate": 4,
    "master": 3, "m.tech": 3, "mtech": 3, "mba": 3, "msc": 3, "m.s.": 3,
    "bachelor": 2, "b.tech": 2, "btech": 2, "bsc": 2, "b.s.": 2, "undergraduate": 2,
    "associate": 1, "diploma": 1,
}

_MANDATORY_CUES = ("required", "must have", "mandatory", "minimum", "must possess")
_NON_MANDATORY_CUES = ("preferred", "desirable", "nice to have", "plus", "bonus", "not required")


@dataclass
class EducationRequirement:
    level_name: str
    level_rank: int
    is_mandatory: bool


def extract_education_requirement(jd_text: str) -> EducationRequirement | None:
    lowered = jd_text.lower()
    best: tuple[str, int] | None = None
    for name, rank in _DEGREE_LEVELS.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered) and (best is None or rank > best[1]):
            best = (name, rank)
    if best is None:
        return None

    name, rank = best
    sentence = next((s for s in re.split(r"(?<=[.\n])\s+", jd_text) if name in s.lower()), lowered)
    lowered_sentence = sentence.lower()
    if any(cue in lowered_sentence for cue in _NON_MANDATORY_CUES):
        is_mandatory = False
    else:
        is_mandatory = any(cue in lowered_sentence for cue in _MANDATORY_CUES)
    return EducationRequirement(level_name=name, level_rank=rank, is_mandatory=is_mandatory)


def highest_candidate_degree_rank(resume: JsonResume) -> int:
    best_rank = 0
    for edu in resume.education:
        study_type = (edu.study_type or "").lower()
        for name, rank in _DEGREE_LEVELS.items():
            if name in study_type and rank > best_rank:
                best_rank = rank
    return best_rank


def education_match_score(resume: JsonResume, jd_text: str) -> tuple[float, EducationRequirement | None, bool]:
    """Returns (score in [0,1], requirement-or-None, is_knockout_risk)."""
    requirement = extract_education_requirement(jd_text)
    if requirement is None:
        return 1.0, None, False

    candidate_rank = highest_candidate_degree_rank(resume)
    if candidate_rank >= requirement.level_rank:
        return 1.0, requirement, False
    if candidate_rank == 0:
        return 0.0, requirement, requirement.is_mandatory
    # Has some degree, just below the stated level -- partial credit,
    # proportional to how close the candidate's level is.
    score = candidate_rank / requirement.level_rank
    return score, requirement, requirement.is_mandatory
