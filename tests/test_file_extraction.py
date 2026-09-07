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


def _make_encrypted_pdf(password: str) -> bytes:
    from io import BytesIO
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(password)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_encrypted_pdf_with_real_password_returns_warning_not_a_crash():
    """Regression test for a real, reproduced bug: pypdf's decrypt("")
    returns 0 (failure) rather than raising when the PDF has a real,
    non-blank password -- the previous code only wrapped decrypt() in
    try/except and never checked its return value, so this exact case
    fell through to an unprotected `for page in reader.pages` loop and
    crashed with an uncaught FileNotDecryptedError. Must return a clean
    warning instead, per this module's own "never 500, always return
    something with a clear warning" contract."""
    encrypted_bytes = _make_encrypted_pdf("a-real-password")
    result = extract_text(encrypted_bytes, "resume.pdf")
    assert result.text == ""
    assert any("password-protected" in w for w in result.warnings)


def test_encrypted_pdf_with_blank_password_still_extracts():
    """The one case the original code's intent actually covered
    correctly -- a PDF "encrypted" with a blank/empty password (some
    tools do this) should still decrypt and extract normally, not be
    lumped in with genuinely password-protected files."""
    encrypted_bytes = _make_encrypted_pdf("")
    result = extract_text(encrypted_bytes, "resume.pdf")
    # A blank page has no text either way, but critically: no exception,
    # and no false "password-protected" warning for a file that wasn't
    # really protected.
    assert not any("password-protected" in w for w in result.warnings)
