"""
Resume ingestion: file upload (PDF/DOCX) or pasted plain text, parsed into
the canonical JsonResume shape every other endpoint in this app expects
(scoring, bias audit, etc. -- see app/schemas/json_resume.py).

Before this existed, the only way to use /score/* was to hand-write JSON
matching the JsonResume schema directly -- fine for testing the API, not
something to actually ask a person uploading their resume to do. These two
endpoints are the "give me a normal resume" front door; both return the
same ResumeParseResponse shape so the frontend (or any client) handles
them identically regardless of which path was used.

Both endpoints take an optional `tier` ("basic"/"medium"/"advanced" --
see router.py's Tier enum) so the caller picks which LLM provider answers
this specific request, independent of the LLM_PROVIDER env var. An
invalid tier value is a 400 here, not something resume_extraction.py
should have to think about -- that module raises ValueError and this
route is the one place that turns it into an HTTP response.

Neither endpoint ever 500s on a parse it can't make sense of -- see
resume_extraction.py's module docstring on the two-tier (LLM, then
heuristic) fallback. A person always gets *something* back to review and
correct, with `warnings` explaining what to double-check.
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.llm.router import active_provider, provider_for_tier
from app.core.parsing.file_extraction import UnsupportedFileTypeError, extract_text
from app.core.parsing.resume_extraction import parse_resume_text
from app.schemas.api_models import ResumeParseResponse, ResumeParseTextRequest

router = APIRouter(prefix="/resume", tags=["resume-parsing"])

# Generous but bounded -- this guards against someone uploading something
# enormous by mistake (a video file with a .pdf extension, say), not
# against legitimate resumes, which are never anywhere near this size.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _resolve_tier(tier: str | None):
    """Returns the Provider this request should use for the LLM tier, or
    None (letting the tier param stay unresolved -- resume_extraction.py's
    parse_resume_text falls back to active_provider() in that case, same
    as before tiers existed). Raises HTTPException(400) for an invalid
    tier string rather than letting the ValueError from provider_for_tier
    become an unhandled 500."""
    if tier is None:
        return active_provider()
    try:
        return provider_for_tier(tier)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{tier}' -- must be one of: basic, medium, advanced.",
        ) from None


@router.post("/parse-file", response_model=ResumeParseResponse)
async def parse_file(file: UploadFile = File(...), tier: str | None = Form(None)) -> ResumeParseResponse:
    """Accepts a .pdf or .docx upload (multipart/form-data), extracts its
    text, and parses that into a JsonResume. `tier` is an optional form
    field alongside the file -- see module docstring."""
    resolved_provider = _resolve_tier(tier)

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (max 10 MB).")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        extraction = extract_text(file_bytes, file.filename or "upload")
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not extraction.text.strip():
        # Nothing extractable (e.g. a scanned/image-only PDF) -- this is a
        # real, expected outcome for this tier (see file_extraction.py's
        # docstring on what it doesn't handle), not a server error.
        return ResumeParseResponse(resume={}, parse_method="heuristic", warnings=extraction.warnings)

    parsed = parse_resume_text(extraction.text, provider=resolved_provider)
    return ResumeParseResponse(
        resume=parsed.resume, parse_method=parsed.parse_method,
        warnings=extraction.warnings + parsed.warnings,
        provider_used=resolved_provider.value if parsed.parse_method == "llm" else None,
    )


@router.post("/parse-text", response_model=ResumeParseResponse)
def parse_text(request: ResumeParseTextRequest) -> ResumeParseResponse:
    """Accepts pasted resume text directly (no file) and parses it into a
    JsonResume -- the "just paste your resume" option. `request.tier` is
    optional -- see module docstring."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="No text provided.")
    resolved_provider = _resolve_tier(request.tier)

    parsed = parse_resume_text(request.text, provider=resolved_provider)
    return ResumeParseResponse(
        resume=parsed.resume, parse_method=parsed.parse_method, warnings=parsed.warnings,
        provider_used=resolved_provider.value if parsed.parse_method == "llm" else None,
    )
