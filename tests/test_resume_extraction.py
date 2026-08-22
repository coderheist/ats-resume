import json
import os
from unittest.mock import patch

import pytest

from app.core.parsing.resume_extraction import parse_resume_text

SAMPLE_RESUME_TEXT = """\
Jordan Alvarez
Backend Engineer
jordan.alvarez@example.com | (555) 123-4567 | Denver, CO

SUMMARY
Backend engineer focused on scalable systems and developer tooling.

EXPERIENCE
Software Engineer, Northwind Data
Mar 2021 - Present
- Led migration of the ingestion pipeline to a queue-based architecture, cutting processing latency 42%.
- Scaled the primary Postgres cluster to handle 12,000 concurrent connections during peak load.

Junior Software Engineer, Fieldstone Labs
Jun 2019 - Feb 2021
- Implemented automated test coverage for the billing service, catching 15 regressions pre-release.

EDUCATION
Bachelor of Science in Computer Science
Colorado State University
2019

SKILLS
Languages: Python, JavaScript, SQL
Frameworks: React, Flask, FastAPI

PROJECTS
Plant Disease Detector — React, Flask, PyTorch
- Built a full-stack AI-powered plant disease detection platform.
- Trained and deployed a ResNet34 model, achieving 98% test accuracy.
"""

TWO_LINE_HEADER_TEXT = """\
Priya Sharma
priya.sharma@gmail.com
+1 415-555-0199

WORK EXPERIENCE
Data Scientist
Vertex Analytics
2022 - Present
* Built a churn prediction model improving retention by 18%.
* Automated the weekly reporting pipeline using Airflow.

EDUCATION
M.S. Data Science
NYU
2022

TECHNICAL SKILLS
Python, R, SQL, TensorFlow

KEY PROJECTS
Fraud Detection System
* Built an ensemble fraud detection model achieving 92% precision.
"""


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


def test_empty_text_returns_empty_resume_with_warning():
    result = parse_resume_text("")
    assert result.parse_method == "heuristic"
    assert "No text to parse." in result.warnings


def test_no_provider_configured_falls_back_to_heuristic_with_warning():
    result = parse_resume_text(SAMPLE_RESUME_TEXT, prefer_llm=True)
    assert result.parse_method == "heuristic"
    assert any("ANTHROPIC_API_KEY" in w and "advanced" in w for w in result.warnings)
    assert len(result.resume.work) == 2


def test_heuristic_extracts_basics():
    result = parse_resume_text(SAMPLE_RESUME_TEXT, prefer_llm=False)
    b = result.resume.basics
    assert b.name == "Jordan Alvarez"
    assert b.email == "jordan.alvarez@example.com"
    assert b.phone == "(555) 123-4567"
    assert b.location == "Denver, CO"
    assert "developer tooling" in (b.summary or "")


def test_heuristic_extracts_work_entries_single_line_header():
    result = parse_resume_text(SAMPLE_RESUME_TEXT, prefer_llm=False)
    work = result.resume.work
    assert len(work) == 2
    assert work[0].name == "Northwind Data"
    assert work[0].position == "Software Engineer"
    assert work[0].start_date == "Mar 2021"
    assert work[0].end_date is None  # "Present" -> None
    assert len(work[0].highlights) == 2
    assert work[1].name == "Fieldstone Labs"
    assert work[1].end_date == "Feb 2021"


def test_heuristic_extracts_work_entries_two_line_header():
    result = parse_resume_text(TWO_LINE_HEADER_TEXT, prefer_llm=False)
    work = result.resume.work
    assert len(work) == 1
    assert work[0].position == "Data Scientist"
    assert work[0].name == "Vertex Analytics"
    assert work[0].start_date == "2022"
    assert len(work[0].highlights) == 2


def test_heuristic_extracts_education():
    result = parse_resume_text(SAMPLE_RESUME_TEXT, prefer_llm=False)
    edu = result.resume.education
    assert len(edu) == 1
    assert edu[0].institution == "Colorado State University"
    assert edu[0].area == "Computer Science"
    assert edu[0].study_type and "bachelor" in edu[0].study_type.lower()
    assert edu[0].end_date == "2019"


def test_heuristic_extracts_labeled_skills():
    result = parse_resume_text(SAMPLE_RESUME_TEXT, prefer_llm=False)
    skill_names = {s.name for s in result.resume.skills}
    assert "Languages" in skill_names
    assert "Frameworks" in skill_names
    languages = next(s for s in result.resume.skills if s.name == "Languages")
    assert "Python" in languages.keywords


def test_heuristic_extracts_unlabeled_skills_as_generic_bucket():
    result = parse_resume_text(TWO_LINE_HEADER_TEXT, prefer_llm=False)
    assert any(s.name == "Skills" and "Python" in s.keywords for s in result.resume.skills)


def test_heuristic_extracts_projects_with_dash_separated_description():
    result = parse_resume_text(SAMPLE_RESUME_TEXT, prefer_llm=False)
    projects = result.resume.projects
    assert len(projects) == 1
    assert projects[0].name == "Plant Disease Detector"
    assert "React" in (projects[0].description or "")
    assert len(projects[0].highlights) == 2


def test_heuristic_on_unstructured_garbage_never_raises_and_warns():
    result = parse_resume_text("asdkjasdkj alskdjaslkdj\n\nqwoeiqwoe", prefer_llm=False)
    assert result.resume is not None
    assert any("couldn't confidently identify" in w.lower() for w in result.warnings)


def test_result_is_always_a_valid_json_resume_object():
    for text in (SAMPLE_RESUME_TEXT, TWO_LINE_HEADER_TEXT, "", "garbage text only"):
        result = parse_resume_text(text, prefer_llm=False)
        # Round-trips through the schema without raising -- this is the
        # actual contract callers depend on (never a malformed resume).
        result.resume.model_dump()


class _FakeExtractionClient:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def create_message(self, **kwargs):
        return {"content": [{"type": "text", "text": self._response_text}]}


def test_llm_extraction_used_when_key_configured_and_succeeds(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    resume_json = {
        "basics": {"name": "Test LLM Person", "email": "a@b.com"},
        "work": [{"name": "Acme", "position": "Engineer", "highlights": ["Did a thing."]}],
        "education": [], "skills": [], "projects": [],
    }
    fake_client = _FakeExtractionClient(json.dumps(resume_json))
    with patch("app.core.llm.client_factory.get_client_for", return_value=(fake_client, "claude-sonnet-5")):
        result = parse_resume_text("some resume text", prefer_llm=True)
    assert result.parse_method == "llm"
    assert result.resume.basics.name == "Test LLM Person"
    assert result.warnings == []


def test_llm_extraction_strips_markdown_code_fence(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    fenced = '```json\n{"basics": {"name": "Fenced"}, "work": [], "education": [], "skills": [], "projects": []}\n```'
    fake_client = _FakeExtractionClient(fenced)
    with patch("app.core.llm.client_factory.get_client_for", return_value=(fake_client, "claude-sonnet-5")):
        result = parse_resume_text("some resume text", prefer_llm=True)
    assert result.parse_method == "llm"
    assert result.resume.basics.name == "Fenced"


def test_llm_extraction_falls_back_to_heuristic_on_malformed_output(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    fake_client = _FakeExtractionClient("not json at all")
    with patch("app.core.llm.client_factory.get_client_for", return_value=(fake_client, "claude-sonnet-5")):
        result = parse_resume_text(SAMPLE_RESUME_TEXT, prefer_llm=True)
    assert result.parse_method == "heuristic"
    assert len(result.resume.work) == 2  # heuristic tier still recovers real data
    assert any("didn't succeed" in w for w in result.warnings)


def test_llm_extraction_falls_back_on_client_exception(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")

    class _RaisingClient:
        def create_message(self, **kwargs):
            raise RuntimeError("network error")

    with patch("app.core.llm.client_factory.get_client_for", return_value=(_RaisingClient(), "claude-sonnet-5")):
        result = parse_resume_text(SAMPLE_RESUME_TEXT, prefer_llm=True)
    assert result.parse_method == "heuristic"
    assert len(result.resume.work) == 2


# --------------------------------------------------------------------
# Tier selector -- this is the fix for the actual reported bug: setting
# GEMINI_API_KEY/GROQ_API_KEY alone used to do nothing unless LLM_PROVIDER
# was *also* set to match, because the old code only ever checked
# active_provider()'s key. Passing an explicit tier sidesteps that: the
# provider is exactly what the tier says, regardless of LLM_PROVIDER.
# --------------------------------------------------------------------

def test_basic_tier_uses_groq_key_even_without_llm_provider_env_set(monkeypatch):
    """The exact bug report this fixes: GEMINI_API_KEY/GROQ_API_KEY set,
    LLM_PROVIDER not set (so active_provider() would default to claude) --
    before tiers existed, this always reported "no provider configured."
    Passing tier="basic" should use Groq's key directly, ignoring
    LLM_PROVIDER/active_provider() entirely."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    # Deliberately NOT setting LLM_PROVIDER -- active_provider() would
    # resolve to "claude", which has no key configured in this test.
    resume_json = {"basics": {"name": "Groq Person"}, "work": [], "education": [], "skills": [], "projects": []}
    fake_client = _FakeExtractionClient(json.dumps(resume_json))
    captured_provider = {}

    def fake_get_client_for(task, provider=None):
        captured_provider["provider"] = provider
        return fake_client, "openai/gpt-oss-120b"

    with patch("app.core.llm.client_factory.get_client_for", side_effect=fake_get_client_for):
        result = parse_resume_text(SAMPLE_RESUME_TEXT, tier="basic")
    assert result.parse_method == "llm"
    assert result.resume.basics.name == "Groq Person"
    from app.core.llm.router import Provider
    assert captured_provider["provider"] == Provider.GROQ


def test_medium_tier_uses_gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    resume_json = {"basics": {"name": "Gemini Person"}, "work": [], "education": [], "skills": [], "projects": []}
    fake_client = _FakeExtractionClient(json.dumps(resume_json))
    with patch("app.core.llm.client_factory.get_client_for", return_value=(fake_client, "gemini-3.6-flash")):
        result = parse_resume_text(SAMPLE_RESUME_TEXT, tier="medium")
    assert result.parse_method == "llm"
    assert result.resume.basics.name == "Gemini Person"


def test_advanced_tier_uses_claude_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-claude-key")
    resume_json = {"basics": {"name": "Claude Person"}, "work": [], "education": [], "skills": [], "projects": []}
    fake_client = _FakeExtractionClient(json.dumps(resume_json))
    with patch("app.core.llm.client_factory.get_client_for", return_value=(fake_client, "claude-sonnet-5")):
        result = parse_resume_text(SAMPLE_RESUME_TEXT, tier="advanced")
    assert result.parse_method == "llm"
    assert result.resume.basics.name == "Claude Person"


def test_tier_missing_key_names_exact_missing_env_var_in_warning(monkeypatch):
    """The whole point of the fix: the warning should say EXACTLY which
    env var is missing for the tier that was actually selected, not a
    generic "no provider configured" that doesn't help someone who set
    GEMINI_API_KEY figure out why medium tier still isn't working."""
    result = parse_resume_text(SAMPLE_RESUME_TEXT, tier="medium")  # no GEMINI_API_KEY set
    assert result.parse_method == "heuristic"
    assert any("GEMINI_API_KEY" in w and "medium" in w for w in result.warnings)
    assert not any("ANTHROPIC_API_KEY" in w for w in result.warnings)


def test_invalid_tier_string_raises_value_error():
    with pytest.raises(ValueError):
        parse_resume_text(SAMPLE_RESUME_TEXT, tier="expert")


def test_tier_overrides_llm_provider_env_var(monkeypatch):
    """Even if LLM_PROVIDER is explicitly set to one provider, passing a
    different tier for this specific call should use the tier's provider,
    not the env var -- tiers are a per-request override, not just another
    way to read the same env var."""
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    resume_json = {"basics": {"name": "Groq Override"}, "work": [], "education": [], "skills": [], "projects": []}
    fake_client = _FakeExtractionClient(json.dumps(resume_json))
    with patch("app.core.llm.client_factory.get_client_for", return_value=(fake_client, "openai/gpt-oss-120b")):
        result = parse_resume_text(SAMPLE_RESUME_TEXT, tier="basic")
    assert result.resume.basics.name == "Groq Override"


def test_no_tier_falls_back_to_active_provider_env_var(monkeypatch):
    """Backward-compatible default: omitting tier entirely still respects
    LLM_PROVIDER, same as before tiers existed."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    resume_json = {"basics": {"name": "Env Default"}, "work": [], "education": [], "skills": [], "projects": []}
    fake_client = _FakeExtractionClient(json.dumps(resume_json))
    with patch("app.core.llm.client_factory.get_client_for", return_value=(fake_client, "gemini-3.6-flash")):
        result = parse_resume_text(SAMPLE_RESUME_TEXT)  # no tier passed
    assert result.resume.basics.name == "Env Default"
