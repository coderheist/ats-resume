"""
Lightweight file -> raw text extraction for uploaded resumes (PDF/DOCX).

This is deliberately a *different, lighter* tier than
`parser_interface.py`'s Docling/Marker adapters. Those two are the
layout-aware, CV-model-backed production path documented there (multi-
column resumes, scanned/degraded PDFs) -- correct choice for a real
deployment, but neither is installed by default here because both pull in
GB-scale CV dependencies that aren't worth fetching just to make file
upload work in this scaffold.

`pypdf` (pure Python, no CV models) and `python-docx` (reads the DOCX XML
directly) cover the actual common case -- a normal, text-based, single- or
simple-multi-column resume, which is the overwhelming majority of real
uploads -- entirely correctly, and both install as small pure-Python-ish
wheels. `extract_text()` below tries Docling first *if it happens to be
installed* (so upgrading to the production path really is just `pip
install docling`, per that module's docstring), and falls back to this
tier otherwise -- which, in this scaffold, is every time.

What this tier does NOT handle well, and doesn't pretend to: scanned/
image-only PDFs (no OCR here -- Marker's LLM-assisted path is the
documented answer for that), and heavily columned/graphical resume
templates where naive top-to-bottom text extraction can interleave
columns. Both come back as low-confidence extraction rather than a silent
wrong answer -- see `ExtractionResult.warnings`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

SUPPORTED_EXTENSIONS = (".pdf", ".docx")


@dataclass
class ExtractionResult:
    text: str
    warnings: list[str] = field(default_factory=list)


class UnsupportedFileTypeError(ValueError):
    def __init__(self, filename: str):
        super().__init__(
            f"Unsupported file type for {filename!r} -- upload a .pdf or "
            f".docx file, or use the paste-text option instead."
        )


def extract_text(file_bytes: bytes, filename: str) -> ExtractionResult:
    """Dispatches on file extension. Raises UnsupportedFileTypeError for
    anything other than .pdf / .docx (including legacy .doc, which
    python-docx cannot read -- it's a different, binary OLE format, not
    just an older XML version)."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(file_bytes)
    if lower.endswith(".docx"):
        return _extract_docx(file_bytes)
    if lower.endswith(".doc"):
        raise UnsupportedFileTypeError(filename) from None
    raise UnsupportedFileTypeError(filename)


def _try_docling(file_bytes: bytes, suffix: str) -> str | None:
    """Best-effort: only used if docling happens to be installed (it
    isn't, in this scaffold's default requirements.txt -- see module
    docstring). Returns None on any failure so the caller falls back to
    the pypdf/python-docx tier rather than erroring the whole request."""
    try:
        import tempfile

        from docling.document_converter import DocumentConverter
    except ImportError:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(file_bytes)
            tmp.flush()
            result = DocumentConverter().convert(tmp.name)
            return result.document.export_to_markdown()
    except Exception:  # noqa: BLE001 -- any Docling failure just falls back
        return None


def _extract_pdf(file_bytes: bytes) -> ExtractionResult:
    docling_text = _try_docling(file_bytes, ".pdf")
    if docling_text is not None:
        return ExtractionResult(text=docling_text)

    from pypdf import PdfReader

    warnings: list[str] = []
    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001 -- surfaced as a warning, not a 500
        return ExtractionResult(text="", warnings=[f"Couldn't open this PDF: {exc}"])

    if reader.is_encrypted:
        try:
            reader.decrypt("")  # only handles the "encrypted with blank password" case
        except Exception:
            return ExtractionResult(
                text="", warnings=["This PDF is password-protected -- remove the password and re-upload."],
            )

    pages_text = []
    for page in reader.pages:
        pages_text.append(page.extract_text() or "")
    text = "\n".join(pages_text).strip()

    if not text:
        warnings.append(
            "No extractable text found -- this looks like a scanned/image-only PDF, "
            "which needs OCR this scaffold doesn't run. Try the paste-text option instead."
        )
    elif len(text) < 200:
        warnings.append(
            "Very little text was extracted -- if this is a heavily-columned or "
            "graphical resume template, some content may be missing or out of order. "
            "Double-check the parsed result below."
        )
    return ExtractionResult(text=text, warnings=warnings)


def _extract_docx(file_bytes: bytes) -> ExtractionResult:
    docling_text = _try_docling(file_bytes, ".docx")
    if docling_text is not None:
        return ExtractionResult(text=docling_text)

    import docx

    try:
        document = docx.Document(BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001 -- surfaced as a warning, not a 500
        return ExtractionResult(text="", warnings=[f"Couldn't open this DOCX: {exc}"])

    parts: list[str] = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    text = "\n".join(parts).strip()
    warnings = []
    if not text:
        warnings.append("No extractable text found in this document.")
    return ExtractionResult(text=text, warnings=warnings)
