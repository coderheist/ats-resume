from app.core.scoring.hybrid_score import SENIORITY_WEIGHT_PROFILES, score_resume_against_jd
from app.core.scoring.seniority import SeniorityLevel
from app.schemas.json_resume import Basics, JsonResume, Skill, Work, WorkHighlight


def _sample_resume() -> JsonResume:
    return JsonResume(
        basics=Basics(summary="Backend engineer focused on scalable systems."),
        work=[
            Work(
                name="Acme Corp",
                position="Software Engineer",
                start_date="2020",
                end_date="2024",
                highlights=[
                    WorkHighlight(text="Scaled database infrastructure to handle 10,000 concurrent users"),
                    WorkHighlight(text="Led migration to React for the customer dashboard"),
                ],
            )
        ],
        skills=[Skill(name="Backend", keywords=["software engineering", "postgresql", "react"])],
    )


def test_strong_match_scores_higher_than_weak_match():
    resume = _sample_resume()

    strong_jd = "Looking for a software engineer with 3+ years experience in React and PostgreSQL."
    weak_jd = "Looking for a marketing manager with 5+ years experience in brand strategy."

    strong = score_resume_against_jd(resume, strong_jd)
    weak = score_resume_against_jd(resume, weak_jd)

    assert strong.final_score > weak.final_score


def test_synonym_normalization_matches_across_phrasing():
    """
    Core claim from the blueprint: 'software development' in the JD should
    match 'software engineering' on the resume, unlike plain TF-IDF/keyword
    matching.
    """
    resume = _sample_resume()
    jd = "Seeking a candidate with strong software development experience."

    result = score_resume_against_jd(resume, jd)

    assert "software_engineering" in result.matched_skills
    assert "software_engineering" not in result.missing_skills


def test_experience_gap_is_reflected_and_named():
    resume = _sample_resume()  # 2020-2024 -> 4 years
    jd = "Requires 10+ years of experience in software engineering."

    result = score_resume_against_jd(resume, jd)

    assert result.required_years == 10.0
    assert result.candidate_years == 4.0
    assert result.experience_match_score < 1.0


def test_score_breakdown_sums_to_weighted_final():
    resume = _sample_resume()
    jd = "Software engineering role, React, PostgreSQL, 2+ years experience."

    result = score_resume_against_jd(resume, jd)
    expected = (
        0.5 * result.semantic_similarity
        + 0.3 * result.skill_match_score
        + 0.2 * result.experience_match_score
    )

    assert abs(result.final_score - expected) < 1e-9
    # No seniority signal in this JD -> MID baseline, matching the
    # pre-dynamic-weighting formula exactly.
    assert result.seniority_level == SeniorityLevel.MID


def test_seniority_is_detected_and_reported():
    resume = _sample_resume()
    jd = "Staff Software Engineer, React, PostgreSQL. 8+ years experience."

    result = score_resume_against_jd(resume, jd)

    assert result.seniority_level == SeniorityLevel.STAFF
    assert result.weights_used == SENIORITY_WEIGHT_PROFILES[SeniorityLevel.STAFF]


def test_score_breakdown_sums_to_weighted_final_for_non_mid_seniority():
    """Same weighted-sum contract as the MID test above, but for a JD that
    resolves to a different seniority profile -- the formula should use
    whatever weights `seniority_level` implies, not the hardcoded defaults."""
    resume = _sample_resume()
    jd = "Entry-level Software Engineer role, React, PostgreSQL."

    result = score_resume_against_jd(resume, jd)
    w_semantic, w_skill, w_experience = result.weights_used

    expected = (
        w_semantic * result.semantic_similarity
        + w_skill * result.skill_match_score
        + w_experience * result.experience_match_score
    )

    assert result.seniority_level == SeniorityLevel.ENTRY
    assert abs(result.final_score - expected) < 1e-9


def test_entry_level_weighting_softens_experience_penalty_vs_mid_baseline():
    """
    The core claim behind the dynamic-weighting change: a candidate with a
    real experience gap against the JD's stated years-required should be
    penalized less under an entry-level weight profile (where experience
    counts for less of the total) than under the MID baseline -- same
    resume, same experience_match_score, different final score.
    """
    resume = _sample_resume()  # 2020-2024 -> 4 years
    entry_jd = "Entry-level role. Requires 10+ years of experience in software engineering."

    result = score_resume_against_jd(resume, entry_jd)
    w_semantic, w_skill, w_experience = SENIORITY_WEIGHT_PROFILES[SeniorityLevel.ENTRY]

    # Recompute what the MID-baseline formula would have produced for the
    # exact same component scores, to isolate the effect of the weight
    # change itself.
    mid_equivalent = (
        0.5 * result.semantic_similarity
        + 0.3 * result.skill_match_score
        + 0.2 * result.experience_match_score
    )

    assert result.seniority_level == SeniorityLevel.ENTRY
    assert result.experience_match_score < 1.0  # there is a real gap
    assert result.final_score > mid_equivalent  # but it costs less under ENTRY weights
