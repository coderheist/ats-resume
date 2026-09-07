"""
Experience/tenure match component (0.2 weight in the hybrid score, subject
to the seniority-dependent profile in hybrid_score.py).

Extracts a years-required figure from JD text and compares it against
total candidate experience computed from the JSON Resume `work[]` array.

Two JD phrasings are handled differently, deliberately:

- Floor-only ("5+ years", "5 years of experience"): the JD signals a
  minimum with no stated ceiling. Falling short is penalized
  proportionally; exceeding it is never penalized -- there's no ceiling
  in the text to exceed.
- Explicit range ("0-2 years", "2 to 5 years"): both a floor and a
  ceiling are stated. A candidate within the range scores 1.0. A
  proportional grace band around both edges (width = 50% of the range's
  own width, approved design) also scores 1.0 -- "0-2 years" therefore
  scores 0, 1, 2, *and* 3 years all at 1.0, matching how a human
  recruiter reads "0-2 years" as "roughly entry-level, don't be rigid
  about it" rather than a hard boundary. Beyond the grace band, score
  decays linearly (denominator = the range's own width, floored at 1.0
  year to avoid a degenerate near-zero-width range creating a cliff),
  reaching 0 at grace + one full range-width past the stated edge.
  Worked example for "0-2 years" (width=2, grace=1, denom=2):
    candidate 0/1/2/3 yrs -> 1.0 (within [floor-grace, ceiling+grace] = [0,3])
    candidate 4 yrs -> 0.5   (1 grace-width past the padded ceiling)
    candidate 5+ yrs -> 0.0  (2+ grace-widths past -> "massively over-qualified")
  This curve is a judgment call, not a spec handed down from the JD text
  itself -- if a specific case scores in a way that feels wrong, the fix
  is tuning `denom` below, not the overall shape.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.schemas.json_resume import JsonResume

# Matches "5+ years experience", "5 years of experience", "0-2 years
# experience", "2 to 5 years of experience". Group 1 is always the first
# number; group 2 is the second number of an explicit range, or None for
# floor-only phrasing (including the "+" form).
_RANGE_SEP = r"(?:-|\u2013|\u2014|to)"
_YEARS_PATTERN = re.compile(
    rf"(\d+)\+?\s*(?:{_RANGE_SEP}\s*(\d+))?\s*years?\s+(?:of\s+)?(?:[a-zA-Z]+\s+){{0,4}}experience",
    re.IGNORECASE,
)


@dataclass
class RequiredExperience:
    min_years: float
    max_years: float | None  # None = floor-only (no ceiling stated in the JD)

    @property
    def is_range(self) -> bool:
        return self.max_years is not None


def extract_required_years(jd_text: str) -> RequiredExperience | None:
    match = _YEARS_PATTERN.search(jd_text)
    if not match:
        return None
    min_years = float(match.group(1))
    max_years = float(match.group(2)) if match.group(2) is not None else None
    return RequiredExperience(min_years=min_years, max_years=max_years)


def _parse_year_month(date_str: str | None) -> tuple[int, int] | None:
    """
    Returns (year, month) for "YYYY", "YYYY-MM", or anything containing a
    4-digit year. Month defaults to 1 (January) when not present, same
    convention as treating a year-only date as "start of that year" --
    this only matters for candidates right at a range boundary, but that's
    exactly where precision matters most.
    """
    if not date_str:
        return None
    match = re.search(r"(\d{4})(?:-(\d{1,2}))?", date_str)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else 1
    return year, month


def total_years_experience(resume: JsonResume, as_of: date | None = None) -> float:
    as_of = as_of or date.today()
    total_months = 0
    for job in resume.work:
        start = _parse_year_month(job.start_date)
        if start is None:
            # No parseable start date -- this job silently contributes
            # nothing. See has_unparseable_dates() below to surface that
            # as an actionable data-quality issue rather than a silent
            # undercount.
            continue
        end = _parse_year_month(job.end_date) or (as_of.year, as_of.month)
        months = (end[0] - start[0]) * 12 + (end[1] - start[1])
        total_months += max(0, months)
    return round(total_months / 12, 1)


def has_unparseable_dates(resume: JsonResume) -> list[str]:
    """Job titles/positions whose start date couldn't be parsed, so tenure
    for that role wasn't counted at all. Surfaced by the suggestion engine
    (Task 3) as a data-quality fix, not just swallowed here."""
    return [
        (job.position or job.name or "an unlabeled role")
        for job in resume.work
        if _parse_year_month(job.start_date) is None
    ]


_STRICT_DATE_PATTERN = re.compile(r"^\d{4}(-\d{2})?$")


def date_format_issues(resume: JsonResume) -> list[str]:
    """Semantic Fit spec, Section 6 ("Dates"): flags inconsistent date
    formatting across work entries. What matters for reliably computing
    experience duration is that every entry uses the *same* shape (here:
    YYYY or YYYY-MM) -- not a specific display format, and not whether a
    date is parseable at all (that's has_unparseable_dates() above, a
    separate concern: a date can be a consistent format and still be
    missing entirely, or vice versa -- "Summer 2022" parses a year out
    fine via regex, but isn't format-consistent with "2020-01")."""
    issues = []
    for job in resume.work:
        label_base = job.position or job.name or "a role"
        for field_name, value in (("start date", job.start_date), ("end date", job.end_date)):
            if value is None or value.strip().lower() == "present":
                continue
            if not _STRICT_DATE_PATTERN.match(value.strip()):
                issues.append(
                    f'{label_base}: {field_name} "{value}" isn\'t in a consistent YYYY or YYYY-MM format.'
                )
    return issues


def experience_match_score(resume: JsonResume, jd_text: str) -> tuple[float, RequiredExperience | None, float]:
    """Returns (score in [0,1], RequiredExperience-or-None, candidate_years)."""
    required = extract_required_years(jd_text)
    candidate_years = total_years_experience(resume)

    if required is None:
        # JD didn't specify a tenure requirement -- don't penalize.
        return 1.0, None, candidate_years

    if not required.is_range:
        # Floor-only: no ceiling to exceed, so cap at 1.0 once met.
        if required.min_years == 0:
            return 1.0, required, candidate_years
        score = min(1.0, candidate_years / required.min_years)
        return score, required, candidate_years

    # Explicit range: proportional grace on both edges (approved: 50% of
    # the range's own width), then linear decay outside it.
    width = max(required.max_years - required.min_years, 0.0)
    grace = 0.5 * width
    effective_floor = max(0.0, required.min_years - grace)
    effective_ceiling = required.max_years + grace
    denom = max(width, 1.0)

    if effective_floor <= candidate_years <= effective_ceiling:
        return 1.0, required, candidate_years
    if candidate_years < effective_floor:
        shortfall = effective_floor - candidate_years
        score = max(0.0, 1.0 - shortfall / denom)
    else:
        excess = candidate_years - effective_ceiling
        score = max(0.0, 1.0 - excess / denom)
    return score, required, candidate_years
