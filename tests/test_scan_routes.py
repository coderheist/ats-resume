import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    """No live LLM calls in these tests -- use_llm=True must gracefully
    fall back to the template summary without a key configured."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture
def client():
    return TestClient(app)


def _resume_payload():
    return {
        "basics": {"name": "Jordan Alvarez", "summary": "Backend engineer.", "email": None, "phone": None},
        "work": [{
            "name": "Acme", "position": "Database Administrator",
            "start_date": "2020-01", "end_date": "2022-01",
            "highlights": [{"text": "Was responsible for managing backups."}],
        }],
        "skills": [{"name": "Backend", "keywords": ["software engineering"]}],
    }


def test_jd_match_includes_seniority_and_range_experience_fields(client):
    resp = client.post("/score/jd-match", json={
        "resume": _resume_payload(),
        "jd_text": "Entry-level Software Engineer role, 0-2 years of experience, React required.",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["seniority_detected"] == "entry"
    assert data["experience"]["required_years"] == 0.0
    assert data["experience"]["required_years_max"] == 2.0
    assert "content_quality" in data


def test_standalone_includes_format_issues_and_passive_voice_count(client):
    resp = client.post("/score/standalone", json={"resume": _resume_payload()})
    assert resp.status_code == 200
    data = resp.json()
    assert "missing_email" in data["format_issues"]
    assert "missing_phone" in data["format_issues"]
    assert data["passive_voice_count"] >= 1


def test_suggestions_with_jd_mode(client):
    resp = client.post("/score/suggestions", json={
        "resume": _resume_payload(),
        "jd_text": "Software engineer role requiring React and machine learning experience.",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "with_jd"
    assert len(data["suggestions"]) <= 5
    assert data["summary_source"] == "template"
    categories = {s["category"] for s in data["suggestions"]}
    assert categories  # non-empty -- this resume has real gaps


def test_suggestions_no_jd_mode(client):
    resp = client.post("/score/suggestions", json={"resume": _resume_payload()})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "no_jd"
    assert len(data["suggestions"]) <= 5


def test_suggestions_use_llm_falls_back_to_template_without_api_key(client):
    """No ANTHROPIC_API_KEY configured in this test environment -- the
    route must degrade to the template summary, not 500."""
    resp = client.post("/score/suggestions", json={
        "resume": _resume_payload(),
        "jd_text": "Software engineer role requiring React experience.",
        "use_llm": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary_source"] == "template"
    assert isinstance(data["summary"], str) and data["summary"]


def test_suggestions_ranked_by_descending_impact(client):
    resp = client.post("/score/suggestions", json={
        "resume": _resume_payload(),
        "jd_text": "Software engineer role requiring React, machine learning, and NLP.",
    })
    data = resp.json()
    impacts = [s["estimated_impact"] for s in data["suggestions"]]
    assert impacts == sorted(impacts, reverse=True)


def test_full_report_end_to_end(client):
    resp = client.post("/score/full-report", json={
        "resume": {
            "basics": {"summary": "Backend engineer.", "email": "a@example.com", "phone": "555-1234"},
            "work": [{
                "name": "Acme", "position": "Software Engineer",
                "start_date": "2019-01", "end_date": "2023-01",
                "highlights": [{"text": "Built Python services on AWS Lambda, cutting cold-start latency by 35%."}],
            }],
            "education": [{"institution": "State University", "study_type": "Bachelor", "area": "Computer Science"}],
            "skills": [{"name": "Backend", "keywords": ["python", "docker"]}],
        },
        "jd_text": (
            "Bachelor's degree in Computer Science is required. "
            "Minimum 3 years of professional software engineering experience. "
            "Strong experience with Python and AWS. Docker is a plus."
        ),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_score" in data
    assert data["classification"] in (
        "Strong Match", "Good Match", "Moderate Match", "Weak Match", "Poor Match / High Risk"
    )
    assert data["knockout_risk"] in ("HIGH", "LOW")
    assert len(data["dimensions"]) == 7
    assert "strengths" in data and "where_you_lack" in data
    assert "top_reasons_for_score" in data and "top_improvements_needed" in data


def test_full_report_flags_knockout_risk_for_a_thin_resume(client):
    resp = client.post("/score/full-report", json={
        "resume": {"basics": {"summary": "New grad."}, "work": [], "education": [], "skills": []},
        "jd_text": "Bachelor's degree required. Minimum 5 years of experience. Python required.",
    })
    data = resp.json()
    assert data["knockout_risk"] == "HIGH"
