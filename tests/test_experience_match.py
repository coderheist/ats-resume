from app.core.scoring.experience_match import (
    experience_match_score,
    extract_required_years,
    extract_required_years_range,
)
from app.schemas.json_resume import JsonResume


def test_extracts_inclusive_lower_and_upper_experience_bounds():
    assert extract_required_years_range("Requires 3-5 years of experience") == (3.0, 5.0)
    assert extract_required_years_range("Requires 3 to 5 years experience") == (3.0, 5.0)
    assert extract_required_years_range("Requires 0-1 yrs experience") == (0.0, 1.0)
    assert extract_required_years("Requires 3-5 years of experience") == 3.0


def test_explicit_experience_range_includes_both_boundaries(monkeypatch):
    resume = JsonResume()
    jd = "Requires 3-5 years of experience"

    monkeypatch.setattr(
        "app.core.scoring.experience_match.total_years_experience",
        lambda _: 3.0,
    )
    assert experience_match_score(resume, jd)[0] == 1.0

    monkeypatch.setattr(
        "app.core.scoring.experience_match.total_years_experience",
        lambda _: 5.0,
    )
    assert experience_match_score(resume, jd)[0] == 1.0


def test_zero_candidate_experience_fits_zero_to_one_year_range(monkeypatch):
    resume = JsonResume()
    monkeypatch.setattr(
        "app.core.scoring.experience_match.total_years_experience",
        lambda _: 0.0,
    )

    score, required, candidate = experience_match_score(
        resume, "Requires 0-1 yrs experience"
    )

    assert score == 1.0
    assert required == 0.0
    assert candidate == 0.0
