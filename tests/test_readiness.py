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


# --- regression tests for the two verified bugs fixed in this rebuild ---

def test_role_inference_handles_phrasing_variants_not_exact_canonical_strings():
    """Bug 1: role inference used to compare raw, uncanonicalized skill
    strings straight from the Skills field -- "React.js" would never
    match the ontology's canonical "react", so this resume would have
    gotten no role inference at all under the old code."""
    resume = JsonResume(skills=[Skill(name="Frontend", keywords=["React.js", "Postgres", "Git"])])
    result = score_standalone_readiness(resume)
    assert result.inferred_role is not None


def test_role_inference_sees_skills_mentioned_only_in_work_bullets():
    """Bug 1, second half: all_skill_keywords() only reads the dedicated
    Skills section -- a skill mentioned only in a work bullet was
    invisible to role inference entirely under the old code."""
    resume = JsonResume(work=[Work(
        name="Acme", position="Engineer",
        highlights=[WorkHighlight(text="Built backend services in Python with PostgreSQL and deployed via Docker.")],
    )])
    result = score_standalone_readiness(resume)
    assert result.inferred_role is not None
    assert result.skill_coverage_score > 0


def test_expanded_ontology_covers_previously_unsupported_roles():
    """The original ontology had exactly two roles. Devops and data-analyst
    resumes should now get a real inference, not silently fall through."""
    devops_resume = JsonResume(skills=[Skill(name="Infra", keywords=["docker", "kubernetes", "terraform", "aws"])])
    assert score_standalone_readiness(devops_resume).inferred_role == "devops_engineer"

    analyst_resume = JsonResume(skills=[Skill(name="Analytics", keywords=["sql", "excel", "tableau"])])
    assert score_standalone_readiness(analyst_resume).inferred_role == "data_analyst"


def test_no_role_match_is_neutral_not_penalized():
    """Bug-adjacent design requirement: a resume outside this (tech-scoped)
    ontology's coverage must not be penalized for a gap the ontology
    itself doesn't have data for."""
    resume = JsonResume(skills=[Skill(name="Marketing", keywords=["seo", "copywriting", "campaign management"])])
    result = score_standalone_readiness(resume)
    assert result.inferred_role is None
    assert result.skill_coverage_score == 1.0


# --- bug 2: skill coverage and active voice now actually affect the score ---

def _base_resume(skills):
    return JsonResume(
        basics=Basics(summary="Engineer."),
        work=[Work(name="Acme", position="Engineer", start_date="2021",
                    highlights=[WorkHighlight(text="Led the migration, scaling throughput by 40%.")])],
        education=[Education(institution="State University", study_type="Bachelor")],
        skills=[Skill(name="Backend", keywords=skills)],
    )


def test_skill_coverage_actually_changes_overall_score():
    full_coverage = score_standalone_readiness(
        _base_resume(["software engineering", "python", "javascript", "react", "sql", "git"])
    )
    no_coverage = score_standalone_readiness(_base_resume(["software engineering"]))
    assert full_coverage.skill_coverage_score > no_coverage.skill_coverage_score
    assert full_coverage.overall_score() > no_coverage.overall_score()


def test_active_voice_actually_changes_overall_score():
    active = JsonResume(work=[Work(
        name="Acme", position="Engineer",
        highlights=[WorkHighlight(text="Led the redesign, cutting latency by 40%.")],
    )])
    passive = JsonResume(work=[Work(
        name="Acme", position="Engineer",
        highlights=[WorkHighlight(text="Was responsible for the redesign, which cut latency by 40%.")],
    )])
    active_result = score_standalone_readiness(active)
    passive_result = score_standalone_readiness(passive)
    assert active_result.active_voice_score > passive_result.active_voice_score
    assert active_result.overall_score() > passive_result.overall_score()


def test_weights_sum_to_one():
    from app.core.scoring.readiness import WEIGHTS
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_to_xai_dict_includes_new_fields_and_keeps_old_ones():
    """Additive-only contract: every field the frontend already reads
    must still be present, flat, under its original name."""
    resume = _base_resume(["software engineering", "react"])
    data = score_standalone_readiness(resume).to_xai_dict()
    for legacy_field in ("score", "inferred_role", "structural_completeness",
                         "action_verb_density", "quantified_metric_density",
                         "missing_sections", "missing_ontology_skills", "format_issues"):
        assert legacy_field in data
    assert "active_voice_score" in data
    assert "skill_coverage_score" in data
    assert "weights_used" in data
