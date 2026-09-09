"""CORS configuration parsing and behaviour.

These exist because every failure mode in this area is silent: a browser
blocks the request before it reaches any route, so a misconfigured
allowlist produces no log line, no traceback and no failing test --
just an app that works locally and mysteriously does not in production.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.main import _parse_origin_regex, _parse_origins, app

# Vercel origin shapes: a stable production hostname, and a per-build
# preview hostname whose leading label changes every push.
PRODUCTION = "https://myproject.vercel.app"
PREVIEW = "https://a8onawoux-myproject.vercel.app"
PREVIEW_REGEX = r"https://[a-z0-9-]+-myproject\.vercel\.app"


def test_parse_origins_strips_the_spaces_people_type():
    # The failure this prevents: " https://b.com" is compared to the
    # Origin header by exact equality and never matches.
    assert _parse_origins("https://a.com, https://b.com") == ["https://a.com", "https://b.com"]


def test_parse_origins_strips_a_trailing_slash():
    # An Origin header is scheme + host + port and never carries a path,
    # so "https://a.com/" could not match the "https://a.com" a browser
    # sends. Copying the URL out of an address bar produces exactly this.
    assert _parse_origins("https://a.com/") == ["https://a.com"]
    assert _parse_origins("https://a.com/, https://b.com/") == ["https://a.com", "https://b.com"]
    # A bare "/" is not an origin, only a slash, and must not survive as "".
    assert _parse_origins("/") == []


def test_configured_trailing_slash_still_admits_the_real_browser_origin():
    # The end-to-end version of the bug: configured with a slash, the
    # browser sends none, and the preflight must still succeed.
    client = _client_with(allow_origins=_parse_origins(PRODUCTION + "/"))
    assert _preflight(client, PRODUCTION).headers["access-control-allow-origin"] == PRODUCTION


def test_parse_origins_drops_empty_entries():
    assert _parse_origins("https://a.com,,") == ["https://a.com"]
    assert _parse_origins("") == []
    assert _parse_origins(None) == []


def test_parse_origin_regex_is_none_when_unset_or_blank():
    # None means "no pattern"; "" would compile to a pattern matching
    # nothing under fullmatch, and is not a way to express "allow all".
    assert _parse_origin_regex(None) is None
    assert _parse_origin_regex("") is None
    assert _parse_origin_regex("   ") is None
    assert _parse_origin_regex(r"  https://x\.com  ") == r"https://x\.com"


def test_app_wires_the_origin_regex_through_to_cors_middleware():
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    assert "allow_origin_regex" in cors[0].kwargs


def _client_with(**cors_kwargs) -> TestClient:
    probe = FastAPI()
    probe.add_middleware(
        CORSMiddleware,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
        **cors_kwargs,
    )

    @probe.get("/auth/me")
    def _me():
        return {"ok": True}

    return TestClient(probe)


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/auth/me",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_regex_admits_a_changing_preview_origin_that_the_exact_list_cannot():
    client = _client_with(allow_origins=[PRODUCTION], allow_origin_regex=PREVIEW_REGEX)

    # The stable production alias is covered by the exact list...
    assert _preflight(client, PRODUCTION).headers["access-control-allow-origin"] == PRODUCTION
    # ...and the per-deployment URL, whose hash changes every push, by the pattern.
    assert _preflight(client, PREVIEW).headers["access-control-allow-origin"] == PREVIEW


def test_regex_does_not_admit_a_lookalike_origin():
    client = _client_with(allow_origins=[PRODUCTION], allow_origin_regex=PREVIEW_REGEX)

    # fullmatch: a suffix an attacker can register must not slip through.
    evil = PREVIEW + ".attacker.example"
    assert "access-control-allow-origin" not in _preflight(client, evil).headers
    assert "access-control-allow-origin" not in _preflight(client, "https://evil.example").headers


def test_authorization_survives_preflight_on_a_regex_matched_origin():
    # Without this header a browser strips `Authorization`, and every
    # signed-in request looks anonymous to the backend with no error.
    client = _client_with(allow_origins=[], allow_origin_regex=PREVIEW_REGEX)
    allowed = _preflight(client, PREVIEW).headers["access-control-allow-headers"]
    assert "authorization" in allowed.lower()
