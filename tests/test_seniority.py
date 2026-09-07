from app.core.scoring.seniority import SeniorityLevel, detect_seniority


def test_staff_title_detected():
    assert detect_seniority("We're hiring a Staff Software Engineer.") == SeniorityLevel.STAFF


def test_senior_title_detected():
    assert detect_seniority("Senior Backend Engineer, distributed systems.") == SeniorityLevel.SENIOR


def test_entry_level_phrase_detected():
    assert detect_seniority("Entry-level role, great for a new grad.") == SeniorityLevel.ENTRY


def test_title_cue_wins_over_years_figure():
    """An explicit title cue should outrank an incidental years figure."""
    jd = "Staff Engineer role. 5+ years of experience preferred."
    assert detect_seniority(jd) == SeniorityLevel.STAFF


def test_falls_back_to_years_when_no_title_cue():
    assert detect_seniority("Requires 9+ years of experience.") == SeniorityLevel.STAFF
    assert detect_seniority("Requires 6+ years of experience.") == SeniorityLevel.SENIOR
    assert detect_seniority("Requires 1 year of experience.") == SeniorityLevel.ENTRY


def test_no_signal_defaults_to_mid():
    assert detect_seniority("Looking for a software engineer with React and PostgreSQL.") == SeniorityLevel.MID
