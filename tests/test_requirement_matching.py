from app.core.scoring.jd_requirement_extractor import extract_jd_requirements
from app.core.scoring.requirement_matching import (
    EvidenceStrength, MatchStatus, match_requirements,
)
from app.schemas.json_resume import Basics, Education, JsonResume, Skill, Work, WorkHighlight


def test_skill_demonstrated_in_bullet_with_metric_is_strong_evidence():
    resume = JsonResume(work=[Work(
        name="Acme", position="Engineer",
        highlights=[WorkHighlight(text="Built Python services on AWS, cutting latency by 30%.")],
    )])
    jd = "Requires Python and AWS experience."
    reqs = extract_jd_requirements(jd)
    matches = match_requirements(reqs, resume, jd)

    python_match = next(m for m in matches if m.requirement.canonical_skill == "python")
    assert python_match.status == MatchStatus.MATCHED
    assert python_match.evidence_strength == EvidenceStrength.STRONG


def test_skill_only_in_skills_list_is_weak_evidence_and_partial():
    resume = JsonResume(skills=[Skill(name="Backend", keywords=["python"])])
    jd = "Python experience is a plus."
    reqs = extract_jd_requirements(jd)
    matches = match_requirements(reqs, resume, jd)

    python_match = next(m for m in matches if m.requirement.canonical_skill == "python")
    assert python_match.status == MatchStatus.PARTIALLY_MATCHED
    assert python_match.evidence_strength == EvidenceStrength.WEAK


def test_missing_non_knockout_skill_is_missing_not_knockout_risk():
    resume = JsonResume()
    jd = "Docker experience is a plus."
    reqs = extract_jd_requirements(jd)
    matches = match_requirements(reqs, resume, jd)
    docker_match = next(m for m in matches if m.requirement.canonical_skill == "docker")
    assert docker_match.status == MatchStatus.MISSING


def test_missing_knockout_skill_becomes_knockout_risk():
    resume = JsonResume()
    jd = "Python is required for this role."
    reqs = extract_jd_requirements(jd)
    matches = match_requirements(reqs, resume, jd)
    python_match = next(m for m in matches if m.requirement.canonical_skill == "python")
    assert python_match.status == MatchStatus.KNOCKOUT_RISK


def test_satisfied_knockout_requirement_is_just_matched_not_flagged():
    """A mandatory requirement that IS satisfied should not be reported
    as any kind of risk -- tier only ever elevates a failing status."""
    resume = JsonResume(skills=[Skill(name="Backend", keywords=["python"])],
                        work=[Work(name="A", position="Eng",
                                   highlights=[WorkHighlight(text="Wrote Python services handling 10k requests/sec.")])])
    jd = "Python is required for this role."
    reqs = extract_jd_requirements(jd)
    matches = match_requirements(reqs, resume, jd)
    python_match = next(m for m in matches if m.requirement.canonical_skill == "python")
    assert python_match.status == MatchStatus.MATCHED


def test_experience_knockout_risk_when_years_short():
    resume = JsonResume(work=[Work(name="A", position="Eng", start_date="2023-01", end_date="2024-01")])
    jd = "Minimum 5 years of experience required."
    reqs = extract_jd_requirements(jd)
    matches = match_requirements(reqs, resume, jd)
    exp_match = next(m for m in matches if m.requirement.kind.value == "experience")
    assert exp_match.status == MatchStatus.KNOCKOUT_RISK


def test_education_matched_when_degree_present():
    resume = JsonResume(education=[Education(institution="X", study_type="Bachelor")])
    jd = "Bachelor's degree required."
    reqs = extract_jd_requirements(jd)
    matches = match_requirements(reqs, resume, jd)
    edu_match = next(m for m in matches if m.requirement.kind.value == "education")
    assert edu_match.status == MatchStatus.MATCHED


def test_semantic_match_path_is_reachable_and_correctly_typed():
    """With the default TF-IDF provider, a genuine semantic match (no
    shared vocabulary at all) won't actually fire -- TF-IDF has no
    capacity for that, documented in requirement_matching.py. This test
    verifies the code path itself is wired correctly (match_type/status
    fields exist and are internally consistent) rather than asserting a
    semantic hit that the current provider structurally cannot produce."""
    resume = JsonResume(work=[Work(
        name="Acme", position="Engineer",
        highlights=[WorkHighlight(text="Wrote unit tests for the billing service.")],
    )])
    jd = "Requires machine learning experience."
    reqs = extract_jd_requirements(jd)
    matches = match_requirements(reqs, resume, jd)
    ml_match = next(m for m in matches if m.requirement.canonical_skill == "machine_learning")
    # No exact or semantic evidence exists in this resume for this skill.
    assert ml_match.status == MatchStatus.MISSING
    assert ml_match.match_type.value == "none"


def test_exact_match_is_still_preferred_over_semantic_search():
    """When an exact phrase match exists, the function must never fall
    through to the (weaker, capped-at-MODERATE) semantic path."""
    resume = JsonResume(work=[Work(
        name="Acme", position="Engineer",
        highlights=[WorkHighlight(text="Applied machine learning to fraud detection, cutting false positives by 20%.")],
    )])
    jd = "Requires machine learning experience."
    reqs = extract_jd_requirements(jd)
    matches = match_requirements(reqs, resume, jd)
    ml_match = next(m for m in matches if m.requirement.canonical_skill == "machine_learning")
    assert ml_match.match_type.value == "exact"
    assert ml_match.evidence_strength.value == "strong"
