"""
Experience/tenure match component (0.2 weight in the hybrid score).

Extracts a "years required" figure from JD text (e.g. "5+ years of
experience") and compares it against total candidate experience computed
from the JSON Resume `work[]` array.
"""
from __future__ import annotations

import re
from datetime import date

from app.schemas.json_resume import JsonResume

_YEARS_REQUIRED_PATTERN = re.compile(
    r"(?P<lower>\d+)\s*(?:(?:-|to)\s*(?P<upper>\d+))?\+?\s*"
    r"(?:years?|yrs?)\s+(?:of\s+)?experience",
    re.IGNORECASE,
)


def extract_required_years_range(jd_text: str) -> tuple[float, float | None] | None:
    match = _YEARS_REQUIRED_PATTERN.search(jd_text)
    if not match:
        return None
    lower = float(match.group("lower"))
    upper = match.group("upper")
    return lower, float(upper) if upper is not None else None


def extract_required_years(jd_text: str) -> float | None:
    required_range = extract_required_years_range(jd_text)
    return required_range[0] if required_range else None


def _parse_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    match = re.search(r"(\d{4})", date_str)
    return int(match.group(1)) if match else None


def total_years_experience(resume: JsonResume, as_of: date | None = None) -> float:
    as_of = as_of or date.today()
    total_months = 0
    for job in resume.work:
        start_year = _parse_year(job.start_date)
        if start_year is None:
            continue
        end_year = _parse_year(job.end_date) or as_of.year
        total_months += max(0, (end_year - start_year) * 12)
    return round(total_months / 12, 1)


def experience_match_score(resume: JsonResume, jd_text: str) -> tuple[float, float | None, float]:
    """Returns (score in [0,1], required_years_or_None, candidate_years)."""
    required_range = extract_required_years_range(jd_text)
    required = required_range[0] if required_range else None
    upper_required = required_range[1] if required_range else None
    candidate_years = total_years_experience(resume)

    if required is None or (required == 0 and upper_required is None):
        # JD didn't specify a tenure requirement -- don't penalize.
        return 1.0, required, candidate_years

    if upper_required is not None:
        # An explicit JD range is an inclusive fit band, including 0-1 years.
        return (1.0 if required <= candidate_years <= upper_required else 0.0), required, candidate_years

    score = min(1.0, candidate_years / required)
    return score, required, candidate_years
