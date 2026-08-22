from app.core.scoring.jd_requirement_extractor import (
    RequirementKind, RequirementTier, extract_jd_requirements,
)


def test_mandatory_wording_produces_knockout_tier():
    reqs = extract_jd_requirements("Python is required for this role.")
    python_req = next(r for r in reqs if r.canonical_skill == "python")
    assert python_req.tier == RequirementTier.KNOCKOUT


def test_preferred_wording_produces_preferred_tier():
    reqs = extract_jd_requirements("Docker experience is a plus.")
    docker_req = next(r for r in reqs if r.canonical_skill == "docker")
    assert docker_req.tier == RequirementTier.PREFERRED


def test_plain_mention_with_no_cue_defaults_to_important():
    reqs = extract_jd_requirements("We use React and PostgreSQL day to day.")
    react_req = next(r for r in reqs if r.canonical_skill == "react")
    assert react_req.tier == RequirementTier.IMPORTANT


def test_not_every_keyword_becomes_a_knockout():
    """A JD with one genuinely mandatory item and several plain mentions
    shouldn't classify all of them as knockouts."""
    jd = "Python is required. We also use React, Docker, and AWS in this role."
    reqs = extract_jd_requirements(jd)
    tiers = {r.canonical_skill: r.tier for r in reqs}
    assert tiers["python"] == RequirementTier.KNOCKOUT
    assert tiers["react"] != RequirementTier.KNOCKOUT
    assert tiers["docker"] != RequirementTier.KNOCKOUT


def test_experience_type_descriptor_is_not_extracted_as_a_separate_skill():
    """'3 years of software engineering experience' shouldn't produce a
    standalone, incorrectly-knockout-tiered 'software engineering' skill
    requirement -- that phrase is describing the years requirement, not a
    separately mandatory skill."""
    jd = "Minimum 3 years of professional software engineering experience required."
    reqs = extract_jd_requirements(jd)
    assert not any(r.canonical_skill == "software_engineering" for r in reqs)
    exp_req = next(r for r in reqs if r.kind == RequirementKind.EXPERIENCE)
    assert exp_req.tier == RequirementTier.KNOCKOUT


def test_skill_mentioned_with_experience_word_elsewhere_is_unaffected():
    """The suppression above shouldn't accidentally eat a skill phrase
    that happens to precede the word 'experience' in an unrelated,
    non-years sentence."""
    jd = "React experience with production applications is expected."
    reqs = extract_jd_requirements(jd)
    assert any(r.canonical_skill == "react" for r in reqs)


def test_education_requirement_extracted_with_mandatory_tier():
    jd = "A Bachelor's degree in Computer Science is required."
    reqs = extract_jd_requirements(jd)
    edu_req = next(r for r in reqs if r.kind == RequirementKind.EDUCATION)
    assert edu_req.tier == RequirementTier.KNOCKOUT


def test_no_duplicate_requirements_for_same_canonical_skill():
    jd = "Python required. Must have strong Python skills."
    reqs = extract_jd_requirements(jd)
    python_reqs = [r for r in reqs if r.canonical_skill == "python"]
    assert len(python_reqs) == 1
