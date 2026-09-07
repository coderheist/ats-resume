from __future__ import annotations

import os

# .env is already loaded by this point -- app/__init__.py's load_dotenv()
# call runs before any app.* submodule (including this one) executes its
# own top-level code, see that file for why it lives there instead of here.
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, bias_audit, billing, history, payments, resume, scan, voice
from app.core.rate_limit import RateLimitMiddleware

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

# Rate limiting (app/core/rate_limit.py) added BEFORE CORS below is
# intentional, not arbitrary: Starlette's middleware stack executes the
# LAST-added middleware outermost, so registering CORS after this makes
# CORS wrap the rate limiter -- meaning a CORS preflight (OPTIONS)
# request gets handled and short-circuited by CORSMiddleware itself
# before ever reaching the rate limiter, which is the correct order.
# Swapping this order would make preflight requests count against the
# rate limit too, for no benefit.
app.add_middleware(RateLimitMiddleware)

# The reference frontend (frontend/) is served as a separate static origin
# (e.g. a local dev server on :5500) so it needs CORS to call this API on
# :8000. The React report app (frontend-react/) follows the same pattern
# on :5174 (dev) / :5175 (preview of the production build) -- dev mode
# doesn't actually need this (Vite's own proxy forwards API calls, see
# frontend-react/vite.config.js), but `npm run preview` calls the API
# directly and does. CORS_ALLOWED_ORIGINS defaults to all of these; override
# with a comma-separated list in production rather than opening this to "*".
_default_origins = "http://localhost:5500,http://127.0.0.1:5500,http://localhost:5174,http://localhost:5175"
_allowed_origins = os.environ.get("CORS_ALLOWED_ORIGINS", _default_origins).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    # "Authorization" is required now that Firebase Auth is wired up
    # (app/core/auth/) -- the frontend sends `Authorization: Bearer
    # <id_token>` on requests from a signed-in user. Without this, a
    # browser's CORS preflight silently strips that header on any
    # cross-origin request, and every authenticated call would look
    # anonymous to the backend with no visible error -- exactly the kind
    # of bug that's invisible in same-origin testing (curl, TestClient)
    # and only shows up against a real browser.
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(scan.router)
app.include_router(resume.router)
app.include_router(bias_audit.router)
app.include_router(voice.router)
app.include_router(billing.router)
app.include_router(auth.router)
app.include_router(history.router)
app.include_router(payments.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
