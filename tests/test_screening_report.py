from app.core.scoring.screening_report import WEIGHTS, screen_resume_against_jd
from app.schemas.json_resume import Basics, Education, JsonResume, Project, Skill, Work, WorkHighlight


def _jd() -> str:
    return (
        "We are hiring a Backend Engineer.\n"
        "Requirements:\n"
        "- Bachelor's degree in Computer Science is required.\n"
        "- Minimum 3 years of professional software engineering experience.\n"
        "- Strong experience with Python and AWS.\n"
        "Preferred:\n"
        "- Familiarity with Docker is a plus.\n"
    )


def _strong_resume() -> JsonResume:
    return JsonResume(
        basics=Basics(summary="Backend engineer.", email="a@example.com", phone="555-1234"),
        work=[Work(
            name="Acme", position="Software Engineer", start_date="2019-01", end_date="2023-01",
            highlights=[WorkHighlight(text="Built Python services on AWS Lambda, cutting cold-start latency by 35%.")],
        )],
        education=[Education(institution="State University", study_type="Bachelor", area="Computer Science")],
        skills=[Skill(name="Backend", keywords=["python", "docker"])],
        projects=[Project(name="Churn predictor", description="Used Python and AWS to build a churn model.")],
    )


def _weak_resume() -> JsonResume:
    return JsonResume(
        basics=Basics(summary="Entry-level engineer.", email=None, phone=None),
        work=[Work(name="Startup", position="Intern", start_date="2023-06", end_date="2023-12",
                    highlights=[WorkHighlight(text="Helped with various tasks.")])],
        education=[],
        skills=[],
        projects=[],
    )


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_strong_resume_scores_higher_than_weak_resume():
    strong = screen_resume_against_jd(_strong_resume(), _jd())
    weak = screen_resume_against_jd(_weak_resume(), _jd())
    assert strong.overall_score > weak.overall_score


def test_strong_resume_has_no_knockout_risk():
    report = screen_resume_against_jd(_strong_resume(), _jd())
    assert report.knockout_risk is False


def test_weak_resume_flags_knockout_risk():
    report = screen_resume_against_jd(_weak_resume(), _jd())
    assert report.knockout_risk is True


def test_classification_bands():
    from app.core.scoring.screening_report import _classification
    assert _classification(90) == "Strong Match"
    assert _classification(75) == "Good Match"
    assert _classification(60) == "Moderate Match"
    assert _classification(45) == "Weak Match"
    assert _classification(20) == "Poor Match / High Risk"


def test_strengths_and_gaps_are_populated_for_a_mixed_resume():
    report = screen_resume_against_jd(_strong_resume(), _jd())
    assert report.strengths  # has real strengths to show
    # Docker is listed as a skill keyword but not demonstrated in a
    # bullet -- expect it flagged as weak/partial somewhere in the report.
    assert any("docker" in s.lower() for s in (report.gaps + [m.requirement.label for m in report.matches]))


def test_top_reasons_and_top_improvements_capped_at_three():
    report = screen_resume_against_jd(_weak_resume(), _jd())
    assert len(report.top_reasons) <= 3
    assert len(report.top_improvements) <= 3


def test_suggestions_never_fabricate_a_skill_not_in_resume():
    """Every suggestion about a genuinely missing skill must be phrased
    conditionally ('if you have...') rather than asserting the candidate
    has it -- the spec's explicit fabrication guardrail."""
    report = screen_resume_against_jd(_weak_resume(), _jd())
    skill_suggestions = [s for s in report.suggestions if "python" in s.lower() or "aws" in s.lower()]
    assert skill_suggestions
    assert all("if you genuinely have" in s.lower() for s in skill_suggestions)


def test_to_dict_shape_is_json_serializable():
    import json
    report = screen_resume_against_jd(_strong_resume(), _jd())
    serialized = json.dumps(report.to_dict())  # raises if anything isn't JSON-safe
    assert '"overall_score"' in serialized
    assert '"knockout_risk"' in serialized
