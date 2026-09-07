"""
FastAPI dependencies wrapping firebase_auth.py's token verification.

Two variants, deliberately different failure behavior:

- get_current_user: 401 if no token or an invalid one. Use on routes
  that genuinely require an account (save resume, view history).
- get_optional_user: returns None if no token was given at all
  (anonymous request, allowed) but still 401s if a token *was* given and
  it's invalid -- a garbled/expired token shouldn't be silently treated
  as "anonymous", that would hide a real client-side bug instead of
  surfacing it. Use on routes that work for both signed-in and anonymous
  callers but want to know which -- e.g. the scoring endpoints, still
  fully public, which record usage against an account only when one is
  present (see services/entitlement_service.py).
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.core.auth.firebase_auth import AuthNotConfiguredError, InvalidTokenError, verify_firebase_token


@dataclass
class AuthenticatedUser:
    uid: str
    email: str | None
    name: str | None


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


async def get_current_user(authorization: str | None = Header(None)) -> AuthenticatedUser:
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in required -- no bearer token provided.")
    try:
        claims = verify_firebase_token(token)
    except AuthNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired session: {exc}") from exc
    return AuthenticatedUser(uid=claims["uid"], email=claims.get("email"), name=claims.get("name"))


async def get_optional_user(authorization: str | None = Header(None)) -> AuthenticatedUser | None:
    token = _extract_bearer_token(authorization)
    if not token:
        return None
    try:
        claims = verify_firebase_token(token)
    except AuthNotConfiguredError:
        # Auth isn't configured at all -- treat as anonymous rather than
        # failing a request that doesn't strictly need an account.
        return None
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired session: {exc}") from exc
    return AuthenticatedUser(uid=claims["uid"], email=claims.get("email"), name=claims.get("name"))
