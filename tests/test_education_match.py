from app.core.scoring.education_match import (
    education_match_score, extract_education_requirement, highest_candidate_degree_rank,
)
from app.schemas.json_resume import Education, JsonResume


def test_extracts_mandatory_bachelor_requirement():
    req = extract_education_requirement("A Bachelor's degree in Computer Science is required.")
    assert req.level_name == "bachelor"
    assert req.is_mandatory is True


def test_extracts_preferred_masters_requirement():
    req = extract_education_requirement("A Master's degree is preferred but not required.")
    assert req.level_name == "master"
    assert req.is_mandatory is False


def test_no_degree_mentioned_returns_none():
    assert extract_education_requirement("Great team, remote friendly.") is None


def test_picks_highest_degree_when_multiple_mentioned():
    req = extract_education_requirement("Bachelor's required; Master's or PhD preferred.")
    assert req.level_name == "phd"


def test_highest_candidate_degree_rank_reads_study_type():
    resume = JsonResume(education=[
        Education(institution="A", study_type="Bachelor"),
        Education(institution="B", study_type="Master"),
    ])
    assert highest_candidate_degree_rank(resume) == 3


def test_education_score_full_credit_when_degree_meets_requirement():
    resume = JsonResume(education=[Education(institution="A", study_type="Bachelor")])
    score, req, knockout = education_match_score(resume, "Bachelor's degree required.")
    assert score == 1.0
    assert knockout is False


def test_education_score_knockout_risk_when_missing_and_mandatory():
    resume = JsonResume(education=[])
    score, req, knockout = education_match_score(resume, "Bachelor's degree is required.")
    assert score == 0.0
    assert knockout is True


def test_education_score_no_penalty_when_not_mandatory_and_missing():
    resume = JsonResume(education=[])
    score, req, knockout = education_match_score(resume, "A Master's degree is a plus.")
    assert score == 0.0
    assert knockout is False  # missing, but JD didn't make it mandatory


def test_education_score_partial_credit_below_requirement():
    resume = JsonResume(education=[Education(institution="A", study_type="Associate")])
    score, req, knockout = education_match_score(resume, "Bachelor's degree required.")
    assert 0.0 < score < 1.0


def test_no_requirement_stated_never_penalizes():
    resume = JsonResume(education=[])
    score, req, knockout = education_match_score(resume, "Great engineering culture.")
    assert score == 1.0
    assert req is None
