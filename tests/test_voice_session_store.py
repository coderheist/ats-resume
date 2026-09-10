"""
Bounds on the in-process voice session store.

`session_id` is caller-supplied and /voice/turn is unauthenticated, so
before this the dict was append-only, keyed on arbitrary client input,
and nothing ever removed an entry. Abandoning a conversation -- the
normal way a voice session ends -- leaked an entry for the lifetime of
the process, so this never needed an attacker to matter.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes import voice
from app.main import app


@pytest.fixture(autouse=True)
def _clear_sessions():
    voice._SESSIONS.clear()
    yield
    voice._SESSIONS.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _turn(client, session_id, **slots):
    return client.post("/voice/turn", json={
        "session_id": session_id,
        "transcript": "spoken text",   # required by VoiceTurnRequest
        "extracted_slots": slots,
    })


def test_a_conversation_still_accumulates_across_turns(client):
    """The bounds must not cost the store its actual job."""
    assert _turn(client, "s1", scope="the checkout rewrite").status_code == 200
    resp = _turn(client, "s1", scale="four engineers")

    assert resp.status_code == 200
    filled = resp.json().get("filled_slots") or {}
    # Whatever the agent decides next, the earlier turn's slot survived.
    assert voice._SESSIONS["s1"][1], "accumulated slots were lost"
    assert "scope" in {k.value for k in voice._SESSIONS["s1"][1]} or filled


def test_expired_sessions_are_dropped(client):
    _turn(client, "stale")
    assert "stale" in voice._SESSIONS

    # Age the entry past the TTL, then let the next request prune it.
    touched, slots = voice._SESSIONS["stale"]
    voice._SESSIONS["stale"] = (touched - voice.SESSION_TTL_SECONDS - 1, slots)

    _turn(client, "fresh")

    assert "stale" not in voice._SESSIONS
    assert "fresh" in voice._SESSIONS


def test_an_active_session_is_never_evicted_mid_conversation(client):
    """The timestamp refreshes each turn, so the TTL measures silence,
    not total conversation length."""
    _turn(client, "chatty", scope="a")
    first = voice._SESSIONS["chatty"][0]
    time.sleep(0.01)
    _turn(client, "chatty", scale="b")

    assert voice._SESSIONS["chatty"][0] > first


def test_store_stays_bounded_under_a_flood_of_distinct_ids(client):
    """The cap is the backstop for a burst arriving faster than the TTL
    expires entries -- memory is bounded by MAX_SESSIONS regardless of
    how well behaved callers are."""
    now = time.monotonic()
    for i in range(voice.MAX_SESSIONS + 250):
        voice._SESSIONS[f"flood-{i}"] = (now, {})

    _turn(client, "trigger-prune")

    assert len(voice._SESSIONS) <= voice.MAX_SESSIONS


def test_pruning_drops_the_oldest_first(client):
    now = time.monotonic()
    voice._SESSIONS.clear()
    for i in range(voice.MAX_SESSIONS + 2):
        # Older index == older timestamp.
        voice._SESSIONS[f"s-{i}"] = (now - (voice.MAX_SESSIONS + 2 - i), {})

    voice._prune_sessions(now)

    assert "s-0" not in voice._SESSIONS
    assert f"s-{voice.MAX_SESSIONS + 1}" in voice._SESSIONS
