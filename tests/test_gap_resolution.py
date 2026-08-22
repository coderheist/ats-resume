from app.core.scoring.hybrid_score import score_resume_against_jd
from app.core.voice_agent.gap_resolution import apply_gap_answer, next_gap_prompt
from app.schemas.json_resume import Basics, JsonResume, Skill, Work, WorkHighlight


def _resume_missing_ml() -> JsonResume:
    # "machine learning" is in skill_extraction.py's CANONICAL_SKILLS map
    # (unlike e.g. "AWS", which isn't recognized by this scaffold's starter
    # vocabulary) -- using a term the matcher actually knows about is what
    # makes the missing_skills gap, and its resolution, real.
    return JsonResume(
        basics=Basics(summary="Backend engineer focused on scalable systems."),
        work=[
            Work(
                name="Acme Corp",
                position="Software Engineer",
                start_date="2020",
                end_date="2024",
                highlights=[
                    WorkHighlight(text="Led migration to React for the customer dashboard"),
                ],
            )
        ],
        skills=[Skill(name="Backend", keywords=["software engineering", "react"])],
    )


def test_next_gap_prompt_targets_a_missing_skill():
    resume = _resume_missing_ml()
    jd = "Software engineer role requiring React and machine learning experience."
    breakdown = score_resume_against_jd(resume, jd)

    prompt = next_gap_prompt(breakdown)

    assert prompt is not None
    assert prompt.target_skill in breakdown.missing_skills
    assert prompt.target_skill in prompt.prompt


def test_next_gap_prompt_returns_none_when_no_gaps():
    resume = _resume_missing_ml()
    jd = "Software engineer role requiring React experience."  # no ML ask
    breakdown = score_resume_against_jd(resume, jd)

    assert breakdown.missing_skills == set()
    assert next_gap_prompt(breakdown) is None


def test_apply_gap_answer_patches_resume_and_improves_score():
    resume = _resume_missing_ml()
    jd = "Software engineer role requiring React and machine learning experience."

    result = apply_gap_answer(
        resume, jd,
        answer_text="Built a machine learning model to predict churn, improving retention by 15%.",
    )

    # The answer was appended as a new highlight on the first/most recent job.
    assert any(
        "machine learning model" in h.text for h in result.updated_resume.work[0].highlights
    )
    # Original resume passed in must not be mutated.
    assert not any("machine learning model" in h.text for h in resume.work[0].highlights)
    # The gap is actually closed, and the improved skill coverage should
    # win out over any incidental drift in the semantic-similarity component.
    assert "machine_learning" in result.before.missing_skills
    assert result.after.missing_skills == set()
    assert result.after.skill_match_score > result.before.skill_match_score
    assert result.after.final_score > result.before.final_score
    assert result.score_delta > 0


def test_apply_gap_answer_defaults_out_of_range_job_index():
    resume = _resume_missing_ml()
    jd = "Software engineer role requiring React and machine learning experience."

    result = apply_gap_answer(resume, jd, answer_text="Used ML on a side project.", job_index=99)

    assert len(result.updated_resume.work) == 1
    assert any("ML" in h.text for h in result.updated_resume.work[0].highlights)
