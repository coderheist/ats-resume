"""
Server-side Firebase ID token verification.

React signs a user in directly against Firebase (Google or email/
password) and sends the resulting ID token on every request that needs
identity, as `Authorization: Bearer <token>`. This module is the only
place that token gets verified -- an email/uid claimed directly in a
request body is never trusted, only what comes back from verifying the
signed token itself.

Lazily initializes the Firebase Admin SDK from
FIREBASE_SERVICE_ACCOUNT_JSON (the service account's JSON key *content*,
not a file path -- consistent with this app's "everything via env vars,
nothing baked into the image" pattern for every other credential, see
.env.example). Genuinely optional: if that env var isn't set,
auth-dependent routes return a clear 503 rather than the whole app
failing to start -- the free scoring/analysis endpoints have never
required an account and still don't; only the account-specific features
(save/history, Phase 4) do.
"""
from __future__ import annotations

import json
import os

_app = None
_init_attempted = False


class AuthNotConfiguredError(Exception):
    """No FIREBASE_SERVICE_ACCOUNT_JSON configured (or it's invalid) --
    auth-dependent features are unavailable. Never raised for routes
    that don't require auth."""


class InvalidTokenError(Exception):
    """The provided token failed verification (expired, malformed, wrong
    Firebase project, revoked)."""


def _get_firebase_app():
    global _app, _init_attempted
    if _app is not None:
        return _app
    if _init_attempted:
        raise AuthNotConfiguredError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is not set or invalid -- auth features are unavailable."
        )
    _init_attempted = True

    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise AuthNotConfiguredError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is not set -- auth features are unavailable. "
            "Set it to the Firebase service account key's full JSON content (not a file "
            "path) to enable authentication."
        )

    import firebase_admin
    from firebase_admin import credentials

    try:
        service_account_info = json.loads(raw)
        cred = credentials.Certificate(service_account_info)
        _app = firebase_admin.initialize_app(cred)
    except Exception as exc:
        raise AuthNotConfiguredError(f"FIREBASE_SERVICE_ACCOUNT_JSON is set but invalid: {exc}") from exc
    return _app


def verify_firebase_token(id_token: str) -> dict:
    """Returns {"uid", "email", "name"} for a genuinely valid token.
    Raises AuthNotConfiguredError (no service account configured) or
    InvalidTokenError (bad/expired/malformed token) -- callers translate
    these into the appropriate HTTP status; this module doesn't know
    about FastAPI (see auth/dependencies.py for that layer)."""
    app = _get_firebase_app()  # raises AuthNotConfiguredError

    from firebase_admin import auth as firebase_auth_sdk

    try:
        decoded = firebase_auth_sdk.verify_id_token(id_token, app=app)
    except Exception as exc:
        raise InvalidTokenError(str(exc)) from exc

    return {
        "uid": decoded["uid"],
        "email": decoded.get("email"),
        "name": decoded.get("name"),
    }


def reset_for_testing() -> None:
    """Test-only: clears the cached app so a test can simulate a
    not-configured -> configured transition, or swap credentials between
    test cases, without a process restart."""
    global _app, _init_attempted
    _app = None
    _init_attempted = False
