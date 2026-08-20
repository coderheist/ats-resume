"""
JD bias audit (blueprint Section 5).

Before a resume is even scored against a JD, scan the JD for (a) a skew
between agentic-coded and communal-coded language, and (b) ageist
phrasing, and flag either. This is deliberately a simple, auditable
word-list model rather than an opaque classifier -- transparency matters
as much for this check as it does for the candidate score itself.

Both checks are informational only. `audit_job_description` never touches
`hybrid_score.py` or `readiness.py` -- auditing the JD and scoring the
candidate against it are kept structurally separate, so this check can
never silently reweight or "correct" a candidate's score. Callers should
surface it as a heads-up on the posting itself, not as a scoring input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

AGENTIC_WORDS = {
    "aggressive", "dominant", "dominate", "ambitious", "assertive",
    "competitive", "decisive", "independent", "outspoken", "self-reliant",
    "superior", "driven", "fearless", "individualistic",
}

COMMUNAL_WORDS = {
    "collaborative", "supportive", "team-oriented", "nurturing",
    "interpersonal", "considerate", "cooperative", "compassionate",
    "dependable", "empathetic", "inclusive", "helpful",
}

# Common ageist phrasing seen in job postings -- skews toward younger
# applicants either explicitly (age-coded language) or implicitly (framing
# that reads as "we expect you to have little tenure elsewhere").
AGEIST_PHRASES = {
    "digital native", "young and energetic", "recent graduate",
    "energetic self-starter", "fresh out of school", "youthful",
    "high energy team", "reverse mentor", "native to technology",
}

# Difference above which the JD is flagged for agentic/communal skew.
# Tunable; production version should be calibrated against a labeled JD
# corpus rather than a fixed constant.
DEFAULT_THRESHOLD = 3

NEUTRAL_SUGGESTIONS = {
    "aggressive": "results-oriented",
    "dominant": "a strong track record",
    "dominate": "lead",
    "ambitious": "motivated",
    "assertive": "clear and direct",
    "competitive": "performance-driven",
    "superior": "high-quality",
    "fearless": "willing to take initiative",
    "digital native": "comfortable with modern tools",
    "young and energetic": "enthusiastic",
    "recent graduate": "early-career",
    "fresh out of school": "early-career",
}


@dataclass
class BiasAuditResult:
    agentic_count: int
    communal_count: int
    skew: int
    flagged: bool
    agentic_terms_found: list[str] = field(default_factory=list)
    communal_terms_found: list[str] = field(default_factory=list)
    ageist_terms_found: list[str] = field(default_factory=list)
    suggestions: dict[str, str] = field(default_factory=dict)

    @property
    def ageist_flagged(self) -> bool:
        return bool(self.ageist_terms_found)

    def to_dict(self) -> dict:
        return {
            "flagged": self.flagged,
            "agentic_count": self.agentic_count,
            "communal_count": self.communal_count,
            "skew": self.skew,
            "agentic_terms_found": self.agentic_terms_found,
            "communal_terms_found": self.communal_terms_found,
            "ageist_terms_found": self.ageist_terms_found,
            "suggested_rewrites": self.suggestions,
            "disclaimer": "Heuristic wordlist screen, not legal or compliance advice.",
        }


def _find_terms(text: str, vocabulary: set[str]) -> list[str]:
    lowered = text.lower()
    found = []
    for term in vocabulary:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            found.append(term)
    return sorted(found)


def audit_job_description(jd_text: str, threshold: int = DEFAULT_THRESHOLD) -> BiasAuditResult:
    agentic_found = _find_terms(jd_text, AGENTIC_WORDS)
    communal_found = _find_terms(jd_text, COMMUNAL_WORDS)
    ageist_found = _find_terms(jd_text, AGEIST_PHRASES)

    m_count, f_count = len(agentic_found), len(communal_found)
    skew = m_count - f_count
    skew_flagged = skew >= threshold
    flagged = skew_flagged or bool(ageist_found)

    relevant_terms = agentic_found if skew_flagged else []
    suggestions = {
        term: NEUTRAL_SUGGESTIONS[term]
        for term in [*relevant_terms, *ageist_found]
        if term in NEUTRAL_SUGGESTIONS
    }

    return BiasAuditResult(
        agentic_count=m_count,
        communal_count=f_count,
        skew=skew,
        flagged=flagged,
        agentic_terms_found=agentic_found,
        communal_terms_found=communal_found,
        ageist_terms_found=ageist_found,
        suggestions=suggestions,
    )
