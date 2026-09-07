from app.core.scoring.hybrid_score import score_resume_against_jd
from app.core.scoring.readiness import score_standalone_readiness
from app.core.scoring.suggestion_engine import top_suggestions
from app.schemas.json_resume import Basics, JsonResume, Skill, Work, WorkHighlight


def _resume_with_gaps() -> JsonResume:
    return JsonResume(
        basics=Basics(summary="Backend engineer.", email=None, phone=None),
        work=[Work(
            name="Acme", position="Database Administrator",
            start_date="2020-01", end_date="2022-01",
            highlights=[
                WorkHighlight(text="Was responsible for managing backups."),  # passive, no metric, weak verb
            ],
        )],
        skills=[Skill(name="Backend", keywords=["software engineering"])],
    )


def test_jd_mode_ranks_missing_skills_and_bullet_issues():
    resume = _resume_with_gaps()
    jd = "Software engineer role requiring React and machine learning experience."
    breakdown = score_resume_against_jd(resume, jd)

    ranked = top_suggestions(resume, breakdown, limit=5)
    assert len(ranked) <= 5
    # Descending order by estimated impact.
    impacts = [s.estimated_impact for s in ranked]
    assert impacts == sorted(impacts, reverse=True)

    # Missing skills are real suggestions the engine produces -- confirm
    # with a generous limit rather than assuming they win a tight top-5
    # cutoff against bullet-quality issues, which is a legitimate ranking
    # outcome depending on how many JD skills vs. bullets exist.
    full_ranked = top_suggestions(resume, breakdown, limit=10)
    categories = {s.category for s in full_ranked}
    assert "missing_skill" in categories


def test_jd_mode_content_quality_labeled_as_readability_not_match_score():
    """Content-quality fixes don't move final_score in JD mode (no weight
    for them in that formula) -- must be labeled honestly."""
    resume = _resume_with_gaps()
    jd = "Software engineer role requiring React experience."
    breakdown = score_resume_against_jd(resume, jd)

    ranked = top_suggestions(resume, breakdown, limit=10)
    content_suggestions = [s for s in ranked if s.category in ("unquantified_bullet", "weak_verb", "passive_voice")]

    assert content_suggestions  # the passive/weak/unquantified bullet should be caught
    assert all(s.score_context == "readability" for s in content_suggestions)


def test_no_jd_mode_content_quality_labeled_as_match_score():
    """Same fixes, but in No-JD mode they DO move overall_score() via
    readiness.py's own 0.3/0.3 weights."""
    resume = _resume_with_gaps()
    breakdown = score_standalone_readiness(resume)

    ranked = top_suggestions(resume, breakdown, limit=10)
    content_suggestions = [s for s in ranked if s.category in ("unquantified_bullet", "weak_verb")]

    assert content_suggestions
    assert all(s.score_context == "match_score" for s in content_suggestions)


def test_format_issues_surfaced_in_both_modes():
    resume = _resume_with_gaps()  # no email/phone set

    jd_breakdown = score_resume_against_jd(resume, "Software engineer role.")
    jd_ranked = top_suggestions(resume, jd_breakdown, limit=10)
    assert any(s.category == "format_issue" for s in jd_ranked)

    readiness_breakdown = score_standalone_readiness(resume)
    readiness_ranked = top_suggestions(resume, readiness_breakdown, limit=10)
    assert any(s.category == "format_issue" for s in readiness_ranked)


def test_missing_date_suggestion_names_the_role():
    resume = JsonResume(
        basics=Basics(email="a@example.com", phone="555-1234"),
        work=[Work(name="Acme", position="Backend Engineer", start_date=None, end_date="2022-01",
                    highlights=[WorkHighlight(text="Reduced latency by 20%.")])],
    )
    breakdown = score_resume_against_jd(resume, "Software engineer role.")
    ranked = top_suggestions(resume, breakdown, limit=10)

    date_suggestions = [s for s in ranked if s.category == "missing_date"]
    assert len(date_suggestions) == 1
    assert date_suggestions[0].target == "Backend Engineer"


def test_limit_is_respected():
    resume = _resume_with_gaps()
    jd = "Software engineer role requiring React, machine learning, and NLP experience."
    breakdown = score_resume_against_jd(resume, jd)
    ranked = top_suggestions(resume, breakdown, limit=2)
    assert len(ranked) == 2


def test_perfect_resume_returns_empty_or_minimal_suggestions():
    resume = JsonResume(
        basics=Basics(summary="Great engineer.", email="a@example.com", phone="555-0000"),
        work=[Work(
            name="Acme", position="Software Engineer", start_date="2020-01", end_date="2024-01",
            highlights=[WorkHighlight(text="Led the migration effort, cutting latency by 40%.")],
        )],
        skills=[Skill(name="Backend", keywords=["react"])],
    )
    breakdown = score_resume_against_jd(resume, "Software engineer role requiring React experience.")
    ranked = top_suggestions(resume, breakdown, limit=5)
    # No missing skills, no bullet issues -- only structural format issues
    # (e.g. missing Education section) should remain, if any.
    categories = {s.category for s in ranked}
    assert "missing_skill" not in categories
    assert "unquantified_bullet" not in categories
    assert "weak_verb" not in categories
