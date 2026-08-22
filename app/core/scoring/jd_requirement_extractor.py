"""
Layer 1 of the Semantic Fit spec: read the JD like a recruiter would,
before ever touching the resume.

Pulls every requirement out of JD text -- skills (reusing the shared
CANONICAL_SKILLS vocabulary), the experience-years requirement
(experience_match.py), and the education-level requirement
(education_match.py) -- and classifies each into one of five tiers based
on the JD's own wording, not a fixed per-skill judgment call:

    knockout  -- "required", "must have", "mandatory", "minimum",
                 "at least X years", "must possess"
    critical  -- (reserved for a future finer-grained pass; not yet
                 distinguished from "important" by this heuristic layer)
    important -- mentioned plainly, no strong cue either way (the default)
    preferred -- "preferred", "nice to have", "bonus", "plus", "advantage"
    optional  -- (reserved; same caveat as "critical")

Per the spec: do NOT classify every JD keyword as a knockout requirement.
Tier is driven by the sentence a requirement appears in, not the skill
itself -- the same skill can be a knockout in one JD and merely preferred
in another.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.core.scoring.education_match import extract_education_requirement
from app.core.scoring.experience_match import extract_required_years
from app.core.scoring.skill_extraction import CANONICAL_SKILLS, phrase_present


class RequirementTier(str, Enum):
    KNOCKOUT = "knockout"
    CRITICAL = "critical"
    IMPORTANT = "important"
    PREFERRED = "preferred"
    OPTIONAL = "optional"


class RequirementKind(str, Enum):
    SKILL = "skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"


MANDATORY_CUES = [
    "required", "must have", "must possess", "mandatory", "minimum",
    "at least", "essential qualification", "eligible candidates must",
    "required qualification",
]
NON_MANDATORY_CUES = [
    "preferred", "desirable", "nice to have", "plus", "bonus",
    "advantage", "preferred qualification",
]


@dataclass
class Requirement:
    kind: RequirementKind
    label: str  # display label, e.g. "React", "3+ years of experience", "Bachelor's degree"
    tier: RequirementTier
    canonical_skill: str | None = None  # only set for kind == SKILL
    sentence: str = ""  # the JD sentence it was found in -- context for tiering, shown in the report


def _split_sentences(jd_text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.\n])\s+", jd_text) if s.strip()]


def _sentence_containing(sentences: list[str], phrase: str) -> str:
    for sentence in sentences:
        if phrase_present(phrase, sentence.lower()):
            return sentence
    return ""


def _tier_for_sentence(sentence: str) -> RequirementTier:
    lowered = sentence.lower()
    if any(cue in lowered for cue in NON_MANDATORY_CUES):
        return RequirementTier.PREFERRED
    if any(cue in lowered for cue in MANDATORY_CUES):
        return RequirementTier.KNOCKOUT
    return RequirementTier.IMPORTANT


def _is_experience_type_descriptor(phrase: str, sentence: str) -> bool:
    """True when `phrase` appears as "...years of {phrase} experience"
    (or "...years {phrase} experience") in its own sentence -- i.e. it's
    naming the *domain* of the years-of-experience requirement, not a
    separately mandatory skill. Only suppresses the match when the
    sentence also actually contains a years-of-experience figure, so a
    skill phrase immediately followed by the word "experience" in an
    unrelated sentence (e.g. "React experience with production apps")
    is unaffected."""
    if not sentence or not re.search(r"\d+\+?\s*years?", sentence, re.IGNORECASE):
        return False
    return re.search(rf"{re.escape(phrase)}\s+experience", sentence, re.IGNORECASE) is not None


def extract_jd_requirements(jd_text: str) -> list[Requirement]:
    sentences = _split_sentences(jd_text)
    lowered = jd_text.lower()
    requirements: list[Requirement] = []
    seen_skills: set[str] = set()

    # -- Skills --
    for phrase, canonical in CANONICAL_SKILLS.items():
        if canonical in seen_skills:
            continue
        if not phrase_present(phrase, lowered):
            continue
        sentence = _sentence_containing(sentences, phrase)
        if _is_experience_type_descriptor(phrase, sentence):
            # e.g. "3 years of software engineering experience" -- this
            # is describing the years-of-experience requirement, not a
            # separate mandatory skill; experience_match.py already
            # captures the years figure itself below. Extracting this as
            # its own top-level requirement double-counts it and, worse,
            # would inherit KNOCKOUT tier from the years clause's own
            # "minimum"/"required" wording even though nothing actually
            # made *this specific skill* mandatory on its own.
            continue
        tier = _tier_for_sentence(sentence) if sentence else RequirementTier.IMPORTANT
        requirements.append(Requirement(
            kind=RequirementKind.SKILL,
            label=phrase,
            tier=tier,
            canonical_skill=canonical,
            sentence=sentence,
        ))
        seen_skills.add(canonical)

    # -- Experience --
    required_years = extract_required_years(jd_text)
    if required_years is not None:
        label = (
            f"{required_years.min_years:g}-{required_years.max_years:g} years of experience"
            if required_years.is_range
            else f"{required_years.min_years:g}+ years of experience"
        )
        sentence = next((s for s in sentences if "year" in s.lower()), "")
        tier = _tier_for_sentence(sentence) if sentence else RequirementTier.IMPORTANT
        requirements.append(Requirement(
            kind=RequirementKind.EXPERIENCE, label=label, tier=tier, sentence=sentence,
        ))

    # -- Education --
    education_req = extract_education_requirement(jd_text)
    if education_req is not None:
        sentence = _sentence_containing(sentences, education_req.level_name)
        tier = RequirementTier.KNOCKOUT if education_req.is_mandatory else RequirementTier.IMPORTANT
        requirements.append(Requirement(
            kind=RequirementKind.EDUCATION,
            label=f"{education_req.level_name.title()}'s degree",
            tier=tier,
            sentence=sentence,
        ))

    return requirements
