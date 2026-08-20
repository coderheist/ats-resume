from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import bias_audit, billing, resume, scan, voice

app = FastAPI(
    title="Dual-Mode AI ATS & Conversational Resume Optimizer",
    description=(
        "Reference implementation of the architecture described in the "
        "product blueprint: hybrid semantic/skill/experience resume "
        "scoring, JD-less readiness scoring, JD bias auditing, and a "
        "voice-editing agent loop."
    ),
    version="0.1.0",
)

# The reference frontend (frontend/) is served as a separate static origin
# (e.g. a local dev server on :5500) so it needs CORS to call this API on
# :8000. CORS_ALLOWED_ORIGINS defaults to the two local dev origins the
# frontend README tells you to use; override with a comma-separated list
# in production rather than opening this to "*" -- credentials aren't used
# here (no cookies/auth on these endpoints yet), but a wide-open origin
# list is still worth tightening once real auth is added.
_default_origins = "http://localhost:5500,http://127.0.0.1:5500"
_allowed_origins = os.environ.get("CORS_ALLOWED_ORIGINS", _default_origins).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(scan.router)
app.include_router(resume.router)
app.include_router(bias_audit.router)
app.include_router(voice.router)
app.include_router(billing.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
