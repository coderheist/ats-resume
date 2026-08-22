from app.core.scoring.experience_match import (
    RequiredExperience, experience_match_score, extract_required_years,
    has_unparseable_dates, total_years_experience,
)
from app.schemas.json_resume import JsonResume, Work


def _resume_with_years(years: float, start: str = "2020-01") -> JsonResume:
    start_y, start_m = (int(x) for x in start.split("-"))
    end = f"{start_y + int(years)}-{start_m:02d}"
    return JsonResume(work=[Work(name="Acme", position="Engineer", start_date=start, end_date=end)])


# --- extraction -------------------------------------------------------

def test_extracts_floor_only_with_plus():
    req = extract_required_years("5+ years of experience required.")
    assert req == RequiredExperience(min_years=5.0, max_years=None)
    assert req.is_range is False


def test_extracts_floor_only_without_plus():
    req = extract_required_years("3 years of experience preferred.")
    assert req == RequiredExperience(min_years=3.0, max_years=None)


def test_extracts_explicit_dash_range():
    req = extract_required_years("0-2 years of experience.")
    assert req == RequiredExperience(min_years=0.0, max_years=2.0)
    assert req.is_range is True


def test_extracts_explicit_to_range():
    req = extract_required_years("2 to 5 years of experience.")
    assert req == RequiredExperience(min_years=2.0, max_years=5.0)


def test_no_years_mentioned_returns_none():
    assert extract_required_years("Great team, remote friendly.") is None


# --- range scoring, the user's own worked example ----------------------

def test_zero_to_two_range_scores_full_marks_for_zero_through_three_years():
    jd = "Entry role, 0-2 years of experience required."
    for years in (0, 1, 2, 3):
        score, req, candidate = experience_match_score(_resume_with_years(years), jd)
        assert score == 1.0, f"expected 1.0 for {years} years, got {score}"
        assert req.min_years == 0.0 and req.max_years == 2.0


def test_zero_to_two_range_penalizes_massive_overqualification():
    jd = "Entry role, 0-2 years of experience required."
    score, _, _ = experience_match_score(_resume_with_years(10), jd)
    assert score == 0.0


def test_two_to_five_range_within_bounds_scores_full():
    jd = "Mid-level role, 2-5 years of experience."
    for years in (2, 3, 4, 5):
        score, _, _ = experience_match_score(_resume_with_years(years), jd)
        assert score == 1.0


def test_two_to_five_range_moderate_overage_partial_credit():
    jd = "Mid-level role, 2-5 years of experience."
    score, _, _ = experience_match_score(_resume_with_years(9), jd)
    assert 0.0 < score < 1.0


def test_range_score_is_symmetric_grace_around_both_edges():
    """±50% of the range width (2 years wide -> grace 1) pads both the
    floor and the ceiling equally."""
    jd = "2-4 years of experience."  # width=2, grace=1 -> effective band [1,5]
    for years in (1, 2, 3, 4, 5):
        score, _, _ = experience_match_score(_resume_with_years(years), jd)
        assert score == 1.0
    below_score, _, _ = experience_match_score(_resume_with_years(0), jd)
    assert below_score < 1.0


# --- floor-only behavior preserved -------------------------------------

def test_floor_only_never_penalizes_exceeding_it():
    jd = "10+ years of experience in software engineering."
    score, _, _ = experience_match_score(_resume_with_years(40), jd)
    assert score == 1.0


def test_floor_only_penalizes_falling_short():
    jd = "10+ years of experience in software engineering."
    score, _, candidate = experience_match_score(_resume_with_years(4), jd)
    assert score < 1.0


def test_no_requirement_stated_never_penalizes():
    score, req, _ = experience_match_score(_resume_with_years(0), "Great team culture.")
    assert score == 1.0
    assert req is None


# --- month precision + missing dates ------------------------------------

def test_total_years_uses_month_precision_not_just_year():
    resume = JsonResume(work=[Work(name="A", position="Eng", start_date="2020-12", end_date="2021-01")])
    # 1 month of tenure, not 1 year -- would have been rounded up to a
    # full year under the old year-only parsing.
    assert total_years_experience(resume) < 0.2


def test_missing_start_date_excludes_job_from_total():
    resume = JsonResume(work=[
        Work(name="A", position="Engineer", start_date=None, end_date="2022-01"),
        Work(name="B", position="Analyst", start_date="2020-01", end_date="2021-01"),
    ])
    # Only the second job (1 year) should count.
    assert total_years_experience(resume) == 1.0


def test_has_unparseable_dates_names_the_role():
    resume = JsonResume(work=[
        Work(name="A", position="Database Administrator", start_date=None, end_date="2022-01"),
    ])
    assert has_unparseable_dates(resume) == ["Database Administrator"]


def test_has_unparseable_dates_empty_when_all_present():
    resume = JsonResume(work=[Work(name="A", position="Engineer", start_date="2020-01", end_date="2021-01")])
    assert has_unparseable_dates(resume) == []
