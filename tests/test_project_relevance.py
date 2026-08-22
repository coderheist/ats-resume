from app.core.scoring.project_relevance import project_relevance_score
from app.schemas.json_resume import JsonResume, Project


def test_no_jd_skills_never_penalizes():
    resume = JsonResume(projects=[Project(name="X")])
    score, relevant = project_relevance_score(resume, set())
    assert score == 1.0
    assert relevant == []


def test_no_projects_at_all_scores_zero_when_skills_required():
    resume = JsonResume(projects=[])
    score, relevant = project_relevance_score(resume, {"python"})
    assert score == 0.0


def test_relevant_project_is_identified_by_name():
    resume = JsonResume(projects=[
        Project(name="Churn predictor", description="Built with Python and scikit-learn."),
        Project(name="Portfolio site", description="A personal website in plain HTML/CSS."),
    ])
    score, relevant = project_relevance_score(resume, {"python"})
    assert relevant == ["Churn predictor"]
    assert score == 0.5  # 1 of min(2,3)=2 -> 0.5


def test_score_normalizes_against_at_most_three_projects():
    """A candidate with many projects and 3+ relevant ones shouldn't be
    penalized relative to one with exactly 3 projects, all relevant."""
    resume = JsonResume(projects=[
        Project(name=f"Proj{i}", description="Python project.") for i in range(6)
    ])
    score, relevant = project_relevance_score(resume, {"python"})
    assert score == 1.0
    assert len(relevant) == 6
