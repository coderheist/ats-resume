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
