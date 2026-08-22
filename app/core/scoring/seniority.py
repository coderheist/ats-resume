"""
Seniority detection from JD text.

Feeds the dynamic weighting addition to Mode 1 (hybrid_score.py): a JD's
seniority level shifts how much the semantic/skill/experience components
should count toward the final score -- an entry-level posting shouldn't be
scored on the same rubric as a staff-level one (see hybrid_score.py's
SENIORITY_WEIGHT_PROFILES).

Deliberately a transparent, auditable regex/keyword heuristic, same
philosophy as jd_bias_scanner.py and experience_match.py's years-required
pattern: provable without a live model call. Production can swap this for
an LLM classification call behind the same `detect_seniority` signature.
"""
from __future__ import annotations

import re
from enum import Enum


class SeniorityLevel(str, Enum):
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"


# Title/phrase cues, checked in priority order (most senior first) --
# an explicit title cue is a stronger signal than an incidental years
# figure, so these are checked before falling back to _YEARS_PATTERN.
_STAFF_TERMS = re.compile(
    r"\b(staff|principal|distinguished|head of|vp\b|vice president|director)\b",
    re.IGNORECASE,
)
_SENIOR_TERMS = re.compile(r"\b(senior|sr\.?|lead|manager)\b", re.IGNORECASE)
_ENTRY_TERMS = re.compile(
    r"\b(entry[- ]level|junior|jr\.?|intern(?:ship)?|new grad(?:uate)?|"
    r"recent graduate|no experience required)\b",
    re.IGNORECASE,
)

_YEARS_PATTERN = re.compile(
    r"(\d+)\+?\s*(?:-\s*\d+\s*)?years?\s+(?:of\s+)?experience", re.IGNORECASE
)


def detect_seniority(jd_text: str) -> SeniorityLevel:
    """
    Title/phrase cues take priority over a years-required figure -- e.g. a
    posting titled "Staff Engineer" that also says "5+ years" should still
    resolve to STAFF, not SENIOR. Falls back to MID when nothing is
    detected, which matches hybrid_score.py's pre-existing static weights
    (0.5/0.3/0.2) exactly, so JDs with no seniority signal at all keep
    scoring the way they always did.
    """
    if _STAFF_TERMS.search(jd_text):
        return SeniorityLevel.STAFF
    if _SENIOR_TERMS.search(jd_text):
        return SeniorityLevel.SENIOR
    if _ENTRY_TERMS.search(jd_text):
        return SeniorityLevel.ENTRY

    years_match = _YEARS_PATTERN.search(jd_text)
    if years_match:
        years = int(years_match.group(1))
        if years <= 1:
            return SeniorityLevel.ENTRY
        if years >= 8:
            return SeniorityLevel.STAFF
        if years >= 5:
            return SeniorityLevel.SENIOR

    return SeniorityLevel.MID
