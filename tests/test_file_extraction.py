from pathlib import Path

import pytest

from app.core.parsing.file_extraction import UnsupportedFileTypeError, extract_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_extracts_text_from_real_pdf():
    pdf_bytes = (FIXTURES / "sample_resume.pdf").read_bytes()
    result = extract_text(pdf_bytes, "sample_resume.pdf")
    assert "Jordan Alvarez" in result.text
    assert "Northwind Data" in result.text
    assert result.warnings == []


def test_extracts_text_from_real_docx():
    docx_bytes = (FIXTURES / "sample_resume.docx").read_bytes()
    result = extract_text(docx_bytes, "sample_resume.docx")
    assert "Jordan Alvarez" in result.text
    assert "Northwind Data" in result.text
    assert result.warnings == []


def test_pdf_extraction_is_case_insensitive_on_extension():
    pdf_bytes = (FIXTURES / "sample_resume.pdf").read_bytes()
    result = extract_text(pdf_bytes, "SAMPLE_RESUME.PDF")
    assert "Jordan Alvarez" in result.text


def test_legacy_doc_extension_is_rejected_with_a_clear_message():
    with pytest.raises(UnsupportedFileTypeError, match=r"\.pdf or \.docx"):
        extract_text(b"whatever", "resume.doc")


def test_unrelated_extension_is_rejected():
    with pytest.raises(UnsupportedFileTypeError):
        extract_text(b"whatever", "resume.txt")


def test_corrupted_pdf_returns_a_warning_not_a_crash():
    result = extract_text(b"this is not a real pdf file at all", "broken.pdf")
    assert result.text == ""
    assert result.warnings
    assert "couldn't open" in result.warnings[0].lower()


def test_corrupted_docx_returns_a_warning_not_a_crash():
    result = extract_text(b"this is not a real docx file at all", "broken.docx")
    assert result.text == ""
    assert result.warnings


def test_full_pipeline_pdf_to_parsed_resume():
    """The real end-to-end path the API route exercises: uploaded PDF
    bytes -> extracted text -> a valid JsonResume."""
    from app.core.parsing.resume_extraction import parse_resume_text

    pdf_bytes = (FIXTURES / "sample_resume.pdf").read_bytes()
    extracted = extract_text(pdf_bytes, "sample_resume.pdf")
    parsed = parse_resume_text(extracted.text, prefer_llm=False)

    assert parsed.resume.basics.name == "Jordan Alvarez"
    assert parsed.resume.basics.email == "jordan.alvarez@example.com"
    assert len(parsed.resume.work) == 1
    assert parsed.resume.work[0].name == "Northwind Data"
