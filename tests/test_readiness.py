from app.core.scoring.readiness import score_standalone_readiness
from app.schemas.json_resume import Basics, Education, JsonResume, Skill, Work, WorkHighlight


def test_strong_resume_scores_higher_than_weak_resume():
    strong = JsonResume(
        basics=Basics(summary="Software engineer."),
        work=[
            Work(
                name="Acme",
                position="Engineer",
                start_date="2021",
                highlights=[
                    WorkHighlight(text="Scaled infrastructure to serve 1M requests/day"),
                    WorkHighlight(text="Led a team of 4 engineers on a critical migration"),
                ],
            )
        ],
        education=[Education(institution="State University", study_type="Bachelor")],
        skills=[Skill(name="Backend", keywords=["software engineering", "react"])],
    )

    weak = JsonResume(
        work=[
            Work(
                name="Acme",
                position="Engineer",
                highlights=[WorkHighlight(text="Worked on databases")],
            )
        ],
    )

    strong_result = score_standalone_readiness(strong)
    weak_result = score_standalone_readiness(weak)

    assert strong_result.overall_score() > weak_result.overall_score()
    assert "summary" in weak_result.missing_sections


def test_infers_role_from_skills():
    resume = JsonResume(
        skills=[Skill(name="Backend", keywords=["software engineering", "react", "postgresql"])]
    )
    result = score_standalone_readiness(resume)
    assert result.inferred_role == "software_engineer"
