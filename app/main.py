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


def _parse_origins(raw: str | None) -> list[str]:
    """Split the comma-separated env var into an exact-match allowlist.

    The strip() is not cosmetic. An origin is compared to the request's
    `Origin` header by exact string equality, so a value pasted with the
    spaces people naturally type -- "https://a.com, https://b.com" --
    silently fails to match the second origin, and the failure surfaces
    only as a blocked request in a browser with nothing in the server
    logs. Empty entries (a trailing comma) are dropped for the same
    reason: "" can never match an Origin header, so keeping it would only
    make the configured list misleading to read.
    """
    return [origin.strip() for origin in (raw or "").split(",") if origin.strip()]


def _parse_origin_regex(raw: str | None) -> str | None:
    """CORS_ALLOWED_ORIGIN_REGEX, or None when unset/blank.

    Starlette treats `allow_origin_regex=None` as "no pattern matching",
    which is the intended default -- an empty string would instead be a
    pattern that matches every origin by prefix, i.e. an accidental `*`.
    """
    return (raw or "").strip() or None


_allowed_origins = _parse_origins(os.environ.get("CORS_ALLOWED_ORIGINS", _default_origins))

# Exact origins alone cannot cover a platform that mints a new hostname
# per build. Vercel gives a project a stable production alias
# (`<project>-<team>.vercel.app`) *and* a throwaway per-deployment URL
# (`<project>-<hash>-<team>.vercel.app`) whose hash changes on every
# push -- so an allowlist pinned to one deployment's URL is stale as soon
# as the next commit lands, and pinning every preview is impossible.
# CORS_ALLOWED_ORIGIN_REGEX matches those by pattern instead, e.g.
#
#   CORS_ALLOWED_ORIGIN_REGEX=https://myproject-[a-z0-9]+-myteam\.vercel\.app
#
# Starlette compares with re.fullmatch (see its middleware/cors.py), so
# the pattern must describe the WHOLE Origin header -- scheme included,
# no trailing slash, and a trailing `$` is redundant rather than
# required. The mistake that actually bites is an unescaped `.`, which
# is the regex "any character": `https://myproject-.+-myteam.vercel.app`
# also matches `https://myproject-x-myteamXvercelYapp`, an origin an
# attacker can register. Escape every literal dot, as above.
#
# Firebase is the one thing this cannot paper over: its Authorized
# domains list takes no wildcards, so Google sign-in still only works on
# a hostname listed there by hand. Preview deployments can reach the API
# with this pattern set, but cannot complete a Google sign-in.
#
# Keep the production origin in CORS_ALLOWED_ORIGINS regardless: the two
# are OR'd, and the exact list is the one that should still work if this
# pattern is ever removed.
_allowed_origin_regex = _parse_origin_regex(os.environ.get("CORS_ALLOWED_ORIGIN_REGEX"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_allowed_origin_regex,
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
