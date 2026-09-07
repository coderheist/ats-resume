from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    """Route tests exercise the heuristic tier deterministically -- clear
    any provider env so a real network call is never attempted here."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture
def client():
    return TestClient(app)


def test_parse_text_happy_path(client):
    resp = client.post("/resume/parse-text", json={
        "text": "Jordan Alvarez\njordan@example.com\n\nEXPERIENCE\nEngineer, Acme\n2020 - Present\n- Did a thing.",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["resume"]["basics"]["name"] == "Jordan Alvarez"
    assert body["parse_method"] == "heuristic"
    assert isinstance(body["warnings"], list)


def test_parse_text_rejects_empty_text(client):
    resp = client.post("/resume/parse-text", json={"text": "   "})
    assert resp.status_code == 400


def test_parse_file_pdf_happy_path(client):
    with open(FIXTURES / "sample_resume.pdf", "rb") as f:
        resp = client.post(
            "/resume/parse-file",
            files={"file": ("sample_resume.pdf", f, "application/pdf")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resume"]["basics"]["name"] == "Jordan Alvarez"
    assert body["resume"]["work"][0]["name"] == "Northwind Data"
    assert body["format_analysis"] is not None
    assert body["format_analysis"]["file_type"] in ("pdf_text", "pdf_scanned")


def test_parse_file_docx_happy_path(client):
    with open(FIXTURES / "sample_resume.docx", "rb") as f:
        resp = client.post(
            "/resume/parse-file",
            files={"file": ("sample_resume.docx", f,
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resume"]["basics"]["name"] == "Jordan Alvarez"
    assert body["format_analysis"] is not None
    assert body["format_analysis"]["file_type"] == "docx"


def test_parse_file_rejects_unsupported_extension(client):
    resp = client.post(
        "/resume/parse-file",
        files={"file": ("resume.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 422


def test_parse_file_rejects_empty_file(client):
    resp = client.post(
        "/resume/parse-file",
        files={"file": ("resume.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400


def test_parse_file_rejects_oversized_upload(client):
    huge = b"%PDF-1.4\n" + (b"0" * (11 * 1024 * 1024))
    resp = client.post(
        "/resume/parse-file",
        files={"file": ("resume.pdf", huge, "application/pdf")},
    )
    assert resp.status_code == 413


def test_parse_file_scanned_pdf_returns_warnings_not_an_error(client):
    """A PDF with no extractable text (simulated: not a real PDF at all,
    same code path as a scanned/image-only PDF) should come back as a
    200 with warnings, not a 4xx/5xx -- the person should get an editable
    empty resume to fill in, not a hard failure."""
    resp = client.post(
        "/resume/parse-file",
        files={"file": ("scanned.pdf", b"not a real pdf", "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["warnings"]


# --------------------------------------------------------------------
# Tier selector, at the HTTP layer
# --------------------------------------------------------------------

def test_parse_text_invalid_tier_is_400(client):
    resp = client.post("/resume/parse-text", json={"text": "Jordan Alvarez", "tier": "expert"})
    assert resp.status_code == 400
    assert "basic" in resp.json()["detail"] and "medium" in resp.json()["detail"]


def test_parse_file_invalid_tier_is_400(client):
    resp = client.post(
        "/resume/parse-file",
        files={"file": ("resume.pdf", b"%PDF-1.4\nJordan Alvarez", "application/pdf")},
        data={"tier": "expert"},
    )
    assert resp.status_code == 400


def test_parse_text_basic_tier_without_groq_key_falls_back_with_specific_warning(client):
    """No GROQ_API_KEY set (cleared by the autouse fixture) -- tier=basic
    should fall back to heuristic with a warning naming GROQ_API_KEY and
    'basic' specifically, and provider_used should be null since the LLM
    tier never actually answered."""
    resp = client.post("/resume/parse-text", json={
        "text": "Jordan Alvarez\njordan@example.com\n\nEXPERIENCE\nEngineer, Acme\n2020 - Present\n- Did a thing.",
        "tier": "basic",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["parse_method"] == "heuristic"
    assert body["provider_used"] is None
    assert any("GROQ_API_KEY" in w and "basic" in w for w in body["warnings"])


def test_parse_text_medium_tier_without_gemini_key_falls_back_with_specific_warning(client):
    resp = client.post("/resume/parse-text", json={"text": "Jordan Alvarez", "tier": "medium"})
    assert resp.status_code == 200
    body = resp.json()
    assert any("GEMINI_API_KEY" in w and "medium" in w for w in body["warnings"])


def test_parse_text_llm_success_reports_provider_used(client, monkeypatch):
    """When the LLM tier actually succeeds, provider_used should reflect
    which provider answered -- lets the frontend show e.g. "LLM-parsed
    via Groq (basic)" instead of just a generic "LLM-parsed" badge."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    resume_json = {"basics": {"name": "Groq Person"}, "work": [], "education": [], "skills": [], "projects": []}

    class _FakeClient:
        def create_message(self, **kwargs):
            import json
            return {"content": [{"type": "text", "text": json.dumps(resume_json)}]}

    monkeypatch.setattr(
        "app.core.llm.client_factory.get_client_for",
        lambda task, provider=None: (_FakeClient(), "openai/gpt-oss-120b"),
    )
    resp = client.post("/resume/parse-text", json={"text": "some resume text", "tier": "basic"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parse_method"] == "llm"
    assert body["provider_used"] == "groq"
    assert body["resume"]["basics"]["name"] == "Groq Person"


def test_parse_text_omitted_tier_still_works_heuristically(client):
    """No tier passed at all -- backward compatible, falls back to
    active_provider() (no key configured in tests) -> heuristic, same as
    the pre-tier-selector behavior.
    """
    resp = client.post("/resume/parse-text", json={
        "text": "Jordan Alvarez\njordan@example.com\n\nEXPERIENCE\nEngineer, Acme\n2020 - Present\n- Did a thing.",
    })
    assert resp.status_code == 200
    assert resp.json()["parse_method"] == "heuristic"


def test_no_tier_and_high_confidence_never_attempts_llm_at_all(client):
    """Phase 1 regression guard: _resolve_tier(None) must actually return
    None (not silently resolve active_provider()), or every route call
    looks like an explicit tier request and the confidence gate in
    resume_extraction.py never engages in practice -- a real bug this
    exact test caught, invisible to unit tests that call
    parse_resume_text() directly without going through this route."""
    well_formatted = (
        "Jordan Alvarez\njordan.alvarez@example.com | (555) 123-4567\n\n"
        "EXPERIENCE\nSoftware Engineer, Acme Corp\n01/2020 - 01/2023\n"
        "- Led migration to a queue-based architecture, cutting latency 42%.\n\n"
        "SKILLS\nPython, PostgreSQL, React, AWS\n"
    )
    resp = client.post("/resume/parse-text", json={"text": well_formatted})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parse_method"] == "heuristic"
    assert body["warnings"] == []  # no "no API key configured" warning -- the LLM node was never entered


def test_explicit_tier_still_forces_escalation_regardless_of_confidence(client):
    """The other half of the same fix: an explicit tier must still force
    LLM quality even for a resume the heuristic parser would otherwise
    handle confidently -- distinguishing 'no preference' from 'user
    explicitly asked for this' is the whole point of the fix above."""
    well_formatted = (
        "Jordan Alvarez\njordan.alvarez@example.com | (555) 123-4567\n\n"
        "EXPERIENCE\nSoftware Engineer, Acme Corp\n01/2020 - 01/2023\n"
        "- Led migration to a queue-based architecture, cutting latency 42%.\n\n"
        "SKILLS\nPython, PostgreSQL, React, AWS\n"
    )
    resp = client.post("/resume/parse-text", json={"text": well_formatted, "tier": "advanced"})
    assert resp.status_code == 200
    body = resp.json()
    # No ANTHROPIC_API_KEY configured in the test environment -- the LLM
    # node was entered (forced) and correctly reported why it couldn't
    # complete, then kept the heuristic result as a usable fallback.
    assert any("ANTHROPIC_API_KEY" in w for w in body["warnings"])
    assert len(body["resume"]["work"]) == 1


def test_parse_file_encrypted_pdf_returns_200_with_warning_not_500(client):
    """Route-level regression test for a real, reproduced bug: uploading
    a password-protected PDF used to crash this endpoint with an
    uncaught 500 (pypdf's decrypt() fails silently rather than raising
    for a wrong password -- see test_file_extraction.py for the full
    root-cause explanation). This endpoint's own docstring promises it
    never 500s on a parse it can't make sense of; this is the case that
    broke that promise until fixed."""
    from io import BytesIO
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("a-real-password")
    buf = BytesIO()
    writer.write(buf)

    resp = client.post(
        "/resume/parse-file",
        files={"file": ("resume.pdf", buf.getvalue(), "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any("password-protected" in w for w in body["warnings"])
    assert body["resume"] == {} or body["resume"].get("work") == []


def test_parse_file_structural_safety_net_catches_unexpected_extraction_errors(client, monkeypatch):
    """Proves the safety net added at the route level is real, not just
    documentation: even a completely unanticipated exception from
    extract_text() (simulated here, not tied to any specific known bug)
    must still surface as a 200 with a clear warning, per this
    endpoint's own contract -- never an unhandled 500."""
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr("app.api.routes.resume.extract_text", _boom)
    resp = client.post(
        "/resume/parse-file",
        files={"file": ("resume.pdf", b"%PDF-1.4\nfake", "application/pdf")},
    )
    assert resp.status_code == 200
    assert any("Couldn't process this file" in w for w in resp.json()["warnings"])
