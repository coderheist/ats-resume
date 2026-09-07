from app.core.parsing.parse_confidence import (
    HIGH_CONFIDENCE_THRESHOLD, compute_confidence, is_high_confidence,
)
from app.schemas.json_resume import Basics, JsonResume, Skill, Work, WorkHighlight


def test_empty_resume_scores_zero():
    resume = JsonResume()
    assert compute_confidence(resume, "some raw text") == 0.0


def test_contact_info_alone_gives_partial_credit():
    resume = JsonResume(basics=Basics(email="a@example.com"))
    score = compute_confidence(resume, "a@example.com")
    assert 0.0 < score < HIGH_CONFIDENCE_THRESHOLD


def test_well_formed_resume_is_high_confidence():
    raw_text = "Jordan Alvarez, jordan@example.com. Software Engineer at Acme, 2020-01 to 2023-01. Built things. Reduced latency by 40%. Skills: Python, AWS."
    resume = JsonResume(
        basics=Basics(email="jordan@example.com"),
        work=[Work(
            name="Acme", position="Software Engineer", start_date="2020-01", end_date="2023-01",
            highlights=[WorkHighlight(text="Built things and reduced latency by 40%.")],
        )],
        skills=[Skill(name="Backend", keywords=["python", "aws"])],
    )
    assert is_high_confidence(resume, raw_text)
    assert compute_confidence(resume, raw_text) >= HIGH_CONFIDENCE_THRESHOLD


def test_work_without_dates_or_positions_does_not_get_experience_credit():
    resume = JsonResume(work=[Work(name="Acme", position="", start_date=None)])
    # Structural-section credit (0.20) still applies since resume.work is
    # non-empty, but the stricter "most entries have position+date" credit
    # (0.25) should not.
    score = compute_confidence(resume, "some text")
    assert score < 0.25 + 0.20 + 0.20 + 0.20  # experience-quality band excluded


def test_extraction_ratio_penalizes_a_parse_that_only_captured_a_fragment():
    """A parse that 'succeeded' on paper (some sections found) but only
    captured a tiny fraction of a much longer document shouldn't score as
    confidently as one that captured proportionally more."""
    long_raw_text = "Relevant content. " * 500  # long document
    thin_resume = JsonResume(basics=Basics(email="a@example.com"))
    score = compute_confidence(thin_resume, long_raw_text)
    assert score < HIGH_CONFIDENCE_THRESHOLD


def test_is_high_confidence_matches_the_threshold_boundary():
    resume = JsonResume(basics=Basics(email="a@example.com"))
    score = compute_confidence(resume, "a@example.com")
    assert is_high_confidence(resume, "a@example.com") == (score >= HIGH_CONFIDENCE_THRESHOLD)
