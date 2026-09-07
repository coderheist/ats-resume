"""
Layer 3 of the Semantic Fit spec: turn Layers 1-2 (jd_requirement_extractor.py,
requirement_matching.py) plus the existing scoring primitives into one
weighted score and a report a candidate can actually act on.

Weighting (spec Section 9 -- importance over raw keyword count):
    Knockout/Mandatory Requirements   30%
    Technical Skills                  20%
    Semantic Responsibility Match     20%   (reuses embeddings.scaled_similarity)
    Experience Match                  10%   (reuses experience_match.py)
    Projects/Relevance                10%   (project_relevance.py)
    Education/Qualifications           5%   (education_match.py)
    ATS Readability                    5%   (reuses readiness.py's structural check)

Deliberately does NOT replace hybrid_score.py / ScoreBreakdown -- that
formula and its route stay exactly as they are. This is a new, richer
alternative (POST /score/full-report), reusing every scoring primitive
that already exists rather than recomputing anything twice.

Known, stated limitation: "ATS Readability" here is structural/contact-
field completeness only. True layout analysis (multi-column detection,
tables, embedded images, non-standard headings) needs the *original*
file's layout metadata, which isn't captured anywhere past the parsing
step in this codebase today -- that's a separate, larger addition, not
silently faked here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.scoring.content_quality import analyze_content_quality
from app.core.scoring.education_match import education_match_score
from app.core.scoring.embeddings import get_embedding_provider, scaled_similarity
from app.core.scoring.experience_match import (
    date_format_issues, experience_match_score, has_unparseable_dates,
)
from app.core.scoring.jd_requirement_extractor import RequirementKind, RequirementTier, extract_jd_requirements
from app.core.scoring.project_relevance import project_relevance_score
from app.core.scoring.readiness import structural_completeness_score
from app.core.scoring.requirement_matching import (
    EvidenceStrength, MatchStatus, MatchType, RequirementMatch, match_requirements,
)
from app.core.scoring.skill_extraction import CANONICAL_SKILLS, extract_canonical_skills
from app.schemas.json_resume import JsonResume

# Words this short, or this generic, carry no topical signal either way
# -- excluded from the relevance-gap lexical-overlap check below so a
# shared "the"/"with" doesn't count as evidence a bullet is on-topic.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
    "this", "that", "is", "are", "was", "were", "be", "by", "as", "at",
    "it", "its", "from", "using", "across", "into", "over", "our", "their",
}


def _confidence_for(match_type: MatchType) -> str:
    """How confident the *system* is in this status determination -- not
    how important the requirement is (that's tier) and not how strong the
    evidence is (that's evidence_strength). An exact phrase hit is a sure
    thing either way; a semantic hit is inherently less certain; and a
    genuine miss is reported with high confidence because both the exact
    and semantic search paths were tried and both came back empty."""
    if match_type == MatchType.SEMANTIC:
        return "medium"
    return "high"

WEIGHTS = {
    "knockout_requirements": 0.30,
    "technical_skills": 0.20,
    "semantic_fit": 0.20,
    "experience_match": 0.10,
    "project_relevance": 0.10,
    "education_match": 0.05,
    "ats_readability": 0.05,
}

_TIER_WEIGHT = {
    RequirementTier.CRITICAL: 1.0,
    RequirementTier.IMPORTANT: 0.75,
    RequirementTier.PREFERRED: 0.4,
    RequirementTier.OPTIONAL: 0.2,
}

_REASON_LABELS = {
    "knockout_requirements": "One or more mandatory requirements aren't fully satisfied",
    "technical_skills": "Several important technical skills are missing or only loosely demonstrated",
    "semantic_fit": "The resume's overall narrative doesn't closely mirror this job's core responsibilities",
    "experience_match": "Years of experience don't fully align with what the JD asks for",
    "project_relevance": "Projects don't show much direct overlap with this JD's technologies",
    "education_match": "Education doesn't fully match the stated requirement",
    "ats_readability": "Some structural/contact-info completeness issues may affect parsing",
}


def _classification(score_pct: float) -> str:
    if score_pct >= 85:
        return "Strong Match"
    if score_pct >= 70:
        return "Good Match"
    if score_pct >= 55:
        return "Moderate Match"
    if score_pct >= 40:
        return "Weak Match"
    return "Poor Match / High Risk"


@dataclass
class DimensionScore:
    name: str
    score: float  # 0-1
    weight: float


@dataclass
class ScreeningReport:
    overall_score: float  # 0-1
    dimensions: list[DimensionScore]
    matches: list[RequirementMatch]
    knockout_risk: bool
    strengths: list[str]
    gaps: list[str]
    suggestions: list[str]
    top_reasons: list[str]
    top_improvements: list[str]
    keyword_stuffing_flags: list[str] = None  # type: ignore[assignment]
    relevance_gaps: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.keyword_stuffing_flags is None:
            self.keyword_stuffing_flags = []
        if self.relevance_gaps is None:
            self.relevance_gaps = []

    def classification(self) -> str:
        return _classification(round(self.overall_score * 100, 1))

    def to_dict(self) -> dict:
        return {
            "overall_score": round(self.overall_score * 100, 1),
            "classification": self.classification(),
            "knockout_risk": "HIGH" if self.knockout_risk else "LOW",
            "dimensions": {
                d.name: {"score": round(d.score * 100, 1), "weight": d.weight}
                for d in self.dimensions
            },
            "requirements": [
                {
                    "label": m.requirement.label,
                    "kind": m.requirement.kind.value,
                    "tier": m.requirement.tier.value,
                    "status": m.status.value,
                    "evidence_strength": m.evidence_strength.value,
                    "match_type": m.match_type.value,
                    "confidence": _confidence_for(m.match_type),
                    "evidence_location": m.evidence_location,
                    "detail": m.detail,
                }
                for m in self.matches
            ],
            "keyword_categories": _keyword_categories(self.matches),
            "strengths": self.strengths,
            "where_you_lack": self.gaps,
            "relevance_gaps": self.relevance_gaps,
            "suggestions": self.suggestions,
            "top_reasons_for_score": self.top_reasons,
            "top_improvements_needed": self.top_improvements,
            "keyword_stuffing_flags": self.keyword_stuffing_flags,
        }


def _knockout_score(matches: list[RequirementMatch]) -> tuple[float, bool]:
    knockouts = [m for m in matches if m.requirement.tier == RequirementTier.KNOCKOUT]
    if not knockouts:
        return 1.0, False
    matched = sum(1 for m in knockouts if m.status == MatchStatus.MATCHED)
    has_risk = any(m.status == MatchStatus.KNOCKOUT_RISK for m in knockouts)
    return matched / len(knockouts), has_risk


def _technical_skills_score(matches: list[RequirementMatch]) -> float:
    """Non-knockout skill requirements only -- knockout-tier skills are
    already fully accounted for in the knockout dimension above; folding
    them in here too would double-count the same gap against two
    different weights."""
    skill_matches = [
        m for m in matches
        if m.requirement.kind == RequirementKind.SKILL and m.requirement.tier != RequirementTier.KNOCKOUT
    ]
    if not skill_matches:
        return 1.0
    total_weight = earned_weight = 0.0
    for m in skill_matches:
        w = _TIER_WEIGHT.get(m.requirement.tier, 0.75)
        total_weight += w
        if m.status == MatchStatus.MATCHED:
            earned_weight += w
        elif m.status == MatchStatus.PARTIALLY_MATCHED:
            earned_weight += w * 0.5
    return earned_weight / total_weight if total_weight else 1.0


def _keyword_stuffing_flags(matches: list[RequirementMatch], resume: JsonResume) -> list[str]:
    """Semantic Fit spec, Section 5: 'do not encourage keyword stuffing'.
    Counts literal occurrences of each matched skill's phrase(s) across
    the whole resume -- a skill genuinely woven through several distinct
    roles/projects will naturally repeat a few times; the same phrase
    showing up far more than that is more often a sign it's been
    deliberately padded in than a sign of deeper expertise."""
    resume_text_lower = resume.all_text().lower()
    flags = []
    for m in matches:
        if m.requirement.kind != RequirementKind.SKILL or m.status == MatchStatus.MISSING:
            continue
        phrases = [p for p, c in CANONICAL_SKILLS.items() if c == m.requirement.canonical_skill]
        count = sum(len(re.findall(rf"\b{re.escape(p)}\b", resume_text_lower)) for p in phrases)
        if count >= 5:
            flags.append(
                f'"{m.requirement.label}" appears {count} times across the resume -- double-check this '
                f"reads naturally rather than looking like keyword stuffing."
            )
    return flags


def _keyword_categories(matches: list[RequirementMatch]) -> dict[str, list[str]]:
    """Semantic Fit spec, Section 4: display Exact Matches, Semantic
    Matches, Missing Keywords, and Weak Keywords as separate lists --
    the underlying per-requirement match_type/status data already exists
    on each RequirementMatch; this just organizes it into the four named
    buckets the spec asks for, for skill-kind requirements specifically
    (experience/education have their own dedicated dimensions already)."""
    skill_matches = [m for m in matches if m.requirement.kind == RequirementKind.SKILL]
    return {
        "exact_matches": [
            m.requirement.label for m in skill_matches
            if m.match_type == MatchType.EXACT and m.status == MatchStatus.MATCHED
        ],
        "semantic_matches": [
            m.requirement.label for m in skill_matches if m.match_type == MatchType.SEMANTIC
        ],
        "missing_keywords": [
            m.requirement.label for m in skill_matches
            if m.match_type == MatchType.NONE and m.status in (MatchStatus.MISSING, MatchStatus.KNOCKOUT_RISK)
        ],
        "weak_keywords": [
            m.requirement.label for m in skill_matches
            if m.match_type == MatchType.EXACT and m.status == MatchStatus.PARTIALLY_MATCHED
        ],
    }


def _relevance_gap_bullets(resume: JsonResume, jd_text: str, jd_skill_set: set[str]) -> list[str]:
    """Semantic Fit spec, Section 10 ('Relevance Gap' -- content
    unrelated to the target role). A bullet is flagged only when it
    shares *zero* meaningful words with the JD (stopwords/short words
    excluded) AND touches none of the JD's extracted skills -- a
    deliberately conservative, lexical-overlap check rather than an
    embedding-similarity threshold. The latter was tried and rejected:
    the default TF-IDF provider returns near-zero similarity for most
    short-bullet-vs-JD pairs regardless of genuine relevance (see
    requirement_matching.py's semantic-match docstring for the same
    finding), which would over-flag almost everything. Direct word
    overlap is a coarser signal but an honest one that doesn't rely on a
    provider known not to work well at this granularity."""
    jd_words = {w for w in re.findall(r"[a-z]+", jd_text.lower()) if w not in _STOPWORDS and len(w) > 3}
    quality = analyze_content_quality(resume)
    flagged = []
    for bullet in quality.bullet_issues:
        bullet_words = {w for w in re.findall(r"[a-z]+", bullet.highlight_text.lower()) if w not in _STOPWORDS and len(w) > 3}
        bullet_skills = extract_canonical_skills(bullet.highlight_text)
        if not (bullet_skills & jd_skill_set) and not (bullet_words & jd_words):
            flagged.append(f'{bullet.job_title}: "{bullet.highlight_text}"')
    return flagged


def _build_strengths(matches: list[RequirementMatch], relevant_projects: list[str]) -> list[str]:
    strengths = []
    for m in matches:
        if m.requirement.tier == RequirementTier.KNOCKOUT and m.status == MatchStatus.MATCHED:
            strengths.append(f"Satisfies the mandatory requirement: {m.requirement.label}.")
        elif m.status == MatchStatus.MATCHED and m.evidence_strength == EvidenceStrength.STRONG:
            strengths.append(f"Strong, demonstrated evidence for {m.requirement.label}.")
    for p in relevant_projects:
        strengths.append(f'Relevant project on file: "{p}".')
    return strengths


def _build_gaps(matches: list[RequirementMatch], resume: JsonResume) -> list[str]:
    gaps = []
    for m in matches:
        if m.status == MatchStatus.KNOCKOUT_RISK:
            gaps.append(f"Missing mandatory requirement: {m.requirement.label} ({m.detail})")
        elif m.status == MatchStatus.MISSING:
            gaps.append(f"No evidence found for: {m.requirement.label}.")
        elif m.status == MatchStatus.PARTIALLY_MATCHED and m.evidence_strength == EvidenceStrength.WEAK:
            gaps.append(f"{m.requirement.label} appears only as a keyword, not demonstrated through experience.")
    for role in has_unparseable_dates(resume):
        gaps.append(f"Missing start date for your {role} role -- that experience isn't being counted at all.")
    return gaps


def _priority_for(m: RequirementMatch) -> tuple[int, float]:
    """Lower sorts first. Knockout risks always come first; beyond that,
    rank by the requirement's own tier weight so a critical skill gap
    outranks an optional one."""
    tier_weight = _TIER_WEIGHT.get(m.requirement.tier, 0.75)
    if m.status == MatchStatus.KNOCKOUT_RISK:
        return (0, -tier_weight)
    if m.status == MatchStatus.MISSING:
        return (1, -tier_weight)
    if m.status == MatchStatus.PARTIALLY_MATCHED and m.evidence_strength == EvidenceStrength.WEAK:
        return (2, -tier_weight)
    return (3, -tier_weight)


def _build_suggestions(matches: list[RequirementMatch], resume: JsonResume) -> list[str]:
    actionable = [m for m in matches if m.status != MatchStatus.MATCHED]
    actionable.sort(key=_priority_for)

    suggestions: list[str] = []
    for m in actionable:
        req = m.requirement
        if req.kind == RequirementKind.SKILL:
            if m.status == MatchStatus.PARTIALLY_MATCHED and m.evidence_strength == EvidenceStrength.WEAK:
                suggestions.append(
                    f'"{req.label}" is only in your Skills section -- add it to a Work Experience or '
                    f"Project description explaining how you actually used it, rather than only listing it."
                )
            else:
                suggestions.append(
                    f'If you genuinely have experience with "{req.label}", add a project or work-experience '
                    f"bullet describing the task, the technology, and a factual result -- never add a skill you don't have."
                )
        elif req.kind == RequirementKind.EXPERIENCE:
            suggestions.append(
                f"This role asks for {req.label}; {m.detail} Highlight any additional relevant roles, "
                f"internships, or freelance work if you have them -- don't inflate dates."
            )
        elif req.kind == RequirementKind.EDUCATION:
            suggestions.append(
                f"This role lists a {req.label} requirement. {m.detail} Only note this as satisfied if accurate."
            )

    quality = analyze_content_quality(resume)
    for bullet in quality.unquantified_bullets[:3]:
        text = bullet.highlight_text[:60] + ("..." if len(bullet.highlight_text) > 60 else "")
        suggestions.append(
            f'Add factual metrics (accuracy, users, performance improvement, time saved, dataset size) '
            f'to your {bullet.job_title} bullet: "{text}"'
        )

    return suggestions


def _build_top_reasons(dimensions: list[DimensionScore]) -> list[str]:
    ranked = sorted(dimensions, key=lambda d: d.weight * (1 - d.score), reverse=True)
    reasons = []
    for d in ranked:
        if d.score < 1.0:
            reasons.append(f"{_REASON_LABELS[d.name]} (scored {d.score * 100:.0f}%, {d.weight * 100:.0f}% of total weight).")
        if len(reasons) == 3:
            break
    return reasons


def screen_resume_against_jd(
    resume: JsonResume, jd_text: str, format_risk_count: int | None = None,
) -> ScreeningReport:
    requirements = extract_jd_requirements(jd_text)
    matches = match_requirements(requirements, resume, jd_text)

    knockout_score, knockout_risk = _knockout_score(matches)
    technical_score = _technical_skills_score(matches)

    provider = get_embedding_provider()
    vectors = provider.embed([resume.all_text(), jd_text])
    semantic_score = scaled_similarity(vectors[0], vectors[1])

    experience_score, _, _ = experience_match_score(resume, jd_text)
    jd_skill_set = extract_canonical_skills(jd_text)
    project_score, relevant_projects = project_relevance_score(resume, jd_skill_set)
    education_score, _, _ = education_match_score(resume, jd_text)

    ats_score = structural_completeness_score(resume)
    format_gap_note = None
    if format_risk_count:
        # Each real, file-level risk (multi-column layout, tables,
        # embedded images, contact info only in a header/footer, or a
        # scanned/image-only PDF -- see format_analysis.py) knocks the
        # structural score down further. This is additive to, not a
        # replacement for, structural completeness -- a resume can have
        # every section present *and* still be sitting inside a
        # two-column PDF an ATS can't read correctly.
        ats_score = max(0.0, ats_score - 0.15 * format_risk_count)
        format_gap_note = (
            f"{format_risk_count} real formatting risk(s) were detected in the original file "
            f"(see /resume/parse-file's format_analysis for specifics)."
        )

    dimensions = [
        DimensionScore("knockout_requirements", knockout_score, WEIGHTS["knockout_requirements"]),
        DimensionScore("technical_skills", technical_score, WEIGHTS["technical_skills"]),
        DimensionScore("semantic_fit", semantic_score, WEIGHTS["semantic_fit"]),
        DimensionScore("experience_match", experience_score, WEIGHTS["experience_match"]),
        DimensionScore("project_relevance", project_score, WEIGHTS["project_relevance"]),
        DimensionScore("education_match", education_score, WEIGHTS["education_match"]),
        DimensionScore("ats_readability", ats_score, WEIGHTS["ats_readability"]),
    ]
    overall = max(0.0, min(1.0, sum(d.score * d.weight for d in dimensions)))

    strengths = _build_strengths(matches, relevant_projects)
    gaps = _build_gaps(matches, resume)
    gaps.extend(date_format_issues(resume))
    if format_gap_note:
        gaps.append(format_gap_note)
    suggestions = _build_suggestions(matches, resume)
    top_reasons = _build_top_reasons(dimensions)
    stuffing_flags = _keyword_stuffing_flags(matches, resume)
    relevance_gaps = _relevance_gap_bullets(resume, jd_text, jd_skill_set)

    return ScreeningReport(
        overall_score=overall,
        dimensions=dimensions,
        matches=matches,
        knockout_risk=knockout_risk,
        strengths=strengths,
        gaps=gaps,
        suggestions=suggestions,
        top_reasons=top_reasons,
        top_improvements=suggestions[:3],
        keyword_stuffing_flags=stuffing_flags,
        relevance_gaps=relevance_gaps,
    )
