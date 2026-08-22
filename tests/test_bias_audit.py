from app.core.bias_audit.jd_bias_scanner import DEFAULT_THRESHOLD, audit_job_description


def test_flags_agentic_skewed_jd():
    jd = (
        "We need a dominant, aggressive, competitive, superior candidate "
        "who is fearless and assertive in negotiations."
    )
    result = audit_job_description(jd)

    assert result.flagged is True
    assert result.skew >= 3
    assert "dominant" in result.agentic_terms_found
    assert "dominant" in result.suggestions


def test_does_not_flag_balanced_jd():
    jd = (
        "We're looking for a collaborative, supportive team member with a "
        "results-oriented mindset and strong interpersonal skills."
    )
    result = audit_job_description(jd)

    assert result.flagged is False


def test_neutral_jd_produces_no_flags():
    jd = "Requires 3 years of Python experience and a computer science degree."
    result = audit_job_description(jd)

    assert result.flagged is False
    assert result.agentic_count == 0
    assert result.communal_count == 0
    assert result.ageist_terms_found == []


def test_flags_ageist_phrasing_even_without_agentic_skew():
    """Ageist phrasing should flag the JD on its own, independent of the
    agentic/communal skew count -- it's a separate check, not folded into
    the skew threshold."""
    jd = "Looking for a digital native, recent graduate to join our young and energetic team."
    result = audit_job_description(jd)

    assert result.flagged is True
    assert result.ageist_flagged is True
    assert "digital native" in result.ageist_terms_found
    assert "digital native" in result.suggestions
    # No agentic/communal skew here -- confirms ageist detection is additive,
    # not dependent on the skew threshold being crossed.
    assert result.skew < DEFAULT_THRESHOLD


def test_bias_audit_result_carries_a_disclaimer():
    result = audit_job_description("Requires Python and SQL.")
    assert "not legal or compliance advice" in result.to_dict()["disclaimer"]
