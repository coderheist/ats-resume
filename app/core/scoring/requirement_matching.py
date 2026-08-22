"""
Layer 2 of the Semantic Fit spec: for each JD requirement (Layer 1,
jd_requirement_extractor.py), determine not just whether it's *present*
in the resume, but *how strongly it's demonstrated* and *where* -- an
isolated skills-list mention scores very differently from a
work-experience bullet with real implementation detail, even though a
flat keyword matcher would treat them identically.

Knockout logic: a requirement's *tier* only ever elevates its status to
KNOCKOUT_RISK -- it never lowers a genuinely satisfied requirement. A
knockout-tier requirement that's fully matched is just MATCHED; the same
requirement missing, or only partially satisfied (e.g. "3 years required"
but only 1.5 demonstrated), becomes KNOCKOUT_RISK specifically because it
failed *and* was mandatory. Presence and mandatoriness are independent
axes -- conflating them would misreport an easily-satisfied mandatory
requirement as if it were somehow risky.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.scoring.content_quality import BulletIssue, analyze_content_quality
from app.core.scoring.education_match import education_match_score
from app.core.scoring.experience_match import experience_match_score
from app.core.scoring.jd_requirement_extractor import (
    Requirement, RequirementKind, RequirementTier,
)
from app.core.scoring.skill_extraction import CANONICAL_SKILLS, phrase_present
from app.schemas.json_resume import JsonResume


class MatchStatus(str, Enum):
    MATCHED = "matched"
    PARTIALLY_MATCHED = "partially_matched"
    MISSING = "missing"
    KNOCKOUT_RISK = "knockout_risk"


class EvidenceStrength(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "no_evidence"


class MatchType(str, Enum):
    EXACT = "exact"
    SEMANTIC = "semantic"
    NONE = "none"


@dataclass
class RequirementMatch:
    requirement: Requirement
    status: MatchStatus
    evidence_strength: EvidenceStrength
    match_type: MatchType
    evidence_location: str | None
    evidence_text: str | None
    detail: str = ""  # human-readable specifics, e.g. "1.5 years demonstrated"


def _elevate_if_knockout(base_status: MatchStatus, tier: RequirementTier) -> MatchStatus:
    if tier == RequirementTier.KNOCKOUT and base_status != MatchStatus.MATCHED:
        return MatchStatus.KNOCKOUT_RISK
    return base_status


def _bullet_demonstrating(skill_canonical: str, bullets: list[BulletIssue]) -> BulletIssue | None:
    phrases = [p for p, c in CANONICAL_SKILLS.items() if c == skill_canonical]
    for bullet in bullets:
        lowered = bullet.highlight_text.lower()
        if any(phrase_present(p, lowered) for p in phrases):
            return bullet
    return None


def _match_skill_requirement(requirement: Requirement, resume: JsonResume) -> RequirementMatch:
    quality = analyze_content_quality(resume)
    resume_text_lower = resume.all_text().lower()
    phrases = [p for p, c in CANONICAL_SKILLS.items() if c == requirement.canonical_skill]
    found = any(phrase_present(p, resume_text_lower) for p in phrases)

    if not found:
        status = _elevate_if_knockout(MatchStatus.MISSING, requirement.tier)
        return RequirementMatch(
            requirement=requirement, status=status,
            evidence_strength=EvidenceStrength.NONE, match_type=MatchType.NONE,
            evidence_location=None, evidence_text=None,
            detail="No mention found anywhere in the resume.",
        )

    demonstrating_bullet = _bullet_demonstrating(requirement.canonical_skill, quality.bullet_issues)
    if demonstrating_bullet is not None:
        if demonstrating_bullet.has_metric:
            strength = EvidenceStrength.STRONG
        elif len(demonstrating_bullet.highlight_text.split()) > 8:
            strength = EvidenceStrength.MODERATE
        else:
            strength = EvidenceStrength.WEAK
        base_status = MatchStatus.MATCHED if strength != EvidenceStrength.WEAK else MatchStatus.PARTIALLY_MATCHED
        return RequirementMatch(
            requirement=requirement,
            status=_elevate_if_knockout(base_status, requirement.tier),
            evidence_strength=strength,
            match_type=MatchType.EXACT,
            evidence_location=f"Work Experience: {demonstrating_bullet.job_title}",
            evidence_text=demonstrating_bullet.highlight_text,
            detail="Demonstrated with real context in a work-experience bullet.",
        )

    # Present, but only as a bare keyword (skills list / summary) -- no
    # supporting bullet found.
    return RequirementMatch(
        requirement=requirement,
        status=_elevate_if_knockout(MatchStatus.PARTIALLY_MATCHED, requirement.tier),
        evidence_strength=EvidenceStrength.WEAK,
        match_type=MatchType.EXACT,
        evidence_location="Skills section (no supporting experience found)",
        evidence_text=None,
        detail="Listed as a keyword only -- not demonstrated through experience or a project.",
    )


def _match_experience_requirement(requirement: Requirement, resume: JsonResume, jd_text: str) -> RequirementMatch:
    score, _, candidate_years = experience_match_score(resume, jd_text)
    if score >= 1.0:
        base_status = MatchStatus.MATCHED
    elif score > 0.0:
        base_status = MatchStatus.PARTIALLY_MATCHED
    else:
        base_status = MatchStatus.MISSING
    strength = EvidenceStrength.STRONG if score >= 1.0 else (EvidenceStrength.MODERATE if score > 0 else EvidenceStrength.NONE)
    return RequirementMatch(
        requirement=requirement,
        status=_elevate_if_knockout(base_status, requirement.tier),
        evidence_strength=strength,
        match_type=MatchType.EXACT,
        evidence_location="Work Experience (computed from role dates)",
        evidence_text=None,
        detail=f"{candidate_years:g} years of experience identified.",
    )


def _match_education_requirement(requirement: Requirement, resume: JsonResume, jd_text: str) -> RequirementMatch:
    score, edu_req, _ = education_match_score(resume, jd_text)
    if score >= 1.0:
        base_status = MatchStatus.MATCHED
    elif score > 0.0:
        base_status = MatchStatus.PARTIALLY_MATCHED
    else:
        base_status = MatchStatus.MISSING
    strength = EvidenceStrength.STRONG if score >= 1.0 else (EvidenceStrength.MODERATE if score > 0 else EvidenceStrength.NONE)
    highest = resume.education[0].study_type if resume.education else None
    return RequirementMatch(
        requirement=requirement,
        status=_elevate_if_knockout(base_status, requirement.tier),
        evidence_strength=strength,
        match_type=MatchType.EXACT,
        evidence_location="Education section",
        evidence_text=None,
        detail=f"Highest degree on file: {highest or 'none listed'}.",
    )


def match_requirements(requirements: list[Requirement], resume: JsonResume, jd_text: str) -> list[RequirementMatch]:
    matches: list[RequirementMatch] = []
    for req in requirements:
        if req.kind == RequirementKind.SKILL:
            matches.append(_match_skill_requirement(req, resume))
        elif req.kind == RequirementKind.EXPERIENCE:
            matches.append(_match_experience_requirement(req, resume, jd_text))
        elif req.kind == RequirementKind.EDUCATION:
            matches.append(_match_education_requirement(req, resume, jd_text))
    return matches
