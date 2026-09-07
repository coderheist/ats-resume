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


def test_keyword_stuffing_is_flagged_when_a_skill_repeats_excessively():
    jd = "Requires Python and AWS."
    resume = JsonResume(
        basics=Basics(summary="Python Python Python engineer specializing in Python."),
        work=[Work(
            name="Acme", position="Python Engineer", start_date="2020-01", end_date="2022-01",
            highlights=[
                WorkHighlight(text="Wrote Python scripts to automate Python deployment of Python services using Python."),
            ],
        )],
        skills=[Skill(name="Backend", keywords=["python"])],
    )
    report = screen_resume_against_jd(resume, jd)
    assert any("python" in f.lower() for f in report.keyword_stuffing_flags)


def test_no_stuffing_flag_for_normal_usage():
    report = screen_resume_against_jd(_strong_resume(), _jd())
    assert report.keyword_stuffing_flags == [] or all(
        "python" not in f.lower() for f in report.keyword_stuffing_flags
    )


def test_format_risk_count_lowers_ats_readability_and_adds_a_gap_note():
    without_risk = screen_resume_against_jd(_strong_resume(), _jd())
    with_risk = screen_resume_against_jd(_strong_resume(), _jd(), format_risk_count=2)

    ats_without = next(d for d in without_risk.dimensions if d.name == "ats_readability")
    ats_with = next(d for d in with_risk.dimensions if d.name == "ats_readability")
    assert ats_with.score < ats_without.score
    assert any("formatting risk" in g.lower() for g in with_risk.gaps)


def test_zero_format_risk_count_behaves_like_none():
    a = screen_resume_against_jd(_strong_resume(), _jd(), format_risk_count=0)
    b = screen_resume_against_jd(_strong_resume(), _jd(), format_risk_count=None)
    assert a.overall_score == b.overall_score


def test_keyword_categories_sorts_matches_into_four_buckets():
    resume = JsonResume(
        skills=[Skill(name="Backend", keywords=["python", "docker"])],
        work=[Work(name="Acme", position="Engineer", start_date="2020-01", end_date="2022-01",
                    highlights=[WorkHighlight(text="Built Python services on AWS, cutting latency by 30%.")])],
    )
    jd = "Requires Python, AWS, and Docker. React is a plus."
    report = screen_resume_against_jd(resume, jd)
    cats = report.to_dict()["keyword_categories"]

    assert "python" in [s.lower() for s in cats["exact_matches"]]
    assert "docker" in [s.lower() for s in cats["weak_keywords"]]  # only in skills list
    assert "react" in [s.lower() for s in cats["missing_keywords"]]
    assert set(cats.keys()) == {"exact_matches", "semantic_matches", "missing_keywords", "weak_keywords"}


def test_relevance_gap_flags_off_topic_bullets():
    resume = JsonResume(work=[Work(
        name="Acme", position="Engineer", start_date="2020-01", end_date="2022-01",
        highlights=[
            WorkHighlight(text="Built Python services on AWS, cutting latency by 30%."),
            WorkHighlight(text="Organized the annual company holiday party for 200 employees."),
        ],
    )])
    jd = "Backend Engineer role requiring Python and AWS experience, building scalable APIs."
    report = screen_resume_against_jd(resume, jd)
    assert any("holiday party" in g for g in report.relevance_gaps)
    assert not any("Python services" in g for g in report.relevance_gaps)


def test_confidence_is_high_for_exact_and_missing_medium_for_semantic():
    from app.core.scoring.requirement_matching import MatchType
    from app.core.scoring.screening_report import _confidence_for
    assert _confidence_for(MatchType.EXACT) == "high"
    assert _confidence_for(MatchType.NONE) == "high"
    assert _confidence_for(MatchType.SEMANTIC) == "medium"


def test_requirements_payload_includes_confidence_and_match_type():
    report = screen_resume_against_jd(_strong_resume(), _jd())
    data = report.to_dict()
    for req in data["requirements"]:
        assert req["confidence"] in ("high", "medium")
        assert req["match_type"] in ("exact", "semantic", "none")
