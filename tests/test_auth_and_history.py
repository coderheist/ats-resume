from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app

RESUME = {
    "basics": {"name": "Jordan Alvarez"},
    "work": [{"name": "Acme", "position": "Engineer", "highlights": [{"text": "Built things, cut latency by 40%."}]}],
}
JD_TEXT = "Software engineer role requiring Python and AWS experience."


@pytest.fixture
def db_session():
    """A fresh, isolated in-memory SQLite DB per test -- StaticPool so
    every get_db() call within one test shares the same actual database
    (a plain :memory: engine gives each new connection its own empty DB
    otherwise, which would make persistence invisible across the
    multiple dependency-injected sessions one request touches)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _mock_auth(uid="test-uid", email="jordan@example.com", name="Jordan Alvarez"):
    return patch(
        "app.core.auth.dependencies.verify_firebase_token",
        return_value={"uid": uid, "email": email, "name": name},
    )


AUTH_HEADERS = {"Authorization": "Bearer fake-token"}


class TestAuthNotConfigured:
    def test_me_returns_503_when_firebase_not_configured(self, client):
        """No FIREBASE_SERVICE_ACCOUNT_JSON in this test environment --
        verify_firebase_token raises AuthNotConfiguredError for real, no
        mocking needed to exercise this specific path."""
        resp = client.get("/auth/me", headers=AUTH_HEADERS)
        assert resp.status_code == 503

    def test_no_bearer_token_is_401(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401


class TestAuthMe:
    def test_creates_user_and_free_subscription_on_first_call(self, client):
        with _mock_auth():
            resp = client.get("/auth/me", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["uid"] == "test-uid"
        assert body["tier"] == "free"
        assert body["jd_match_scans_per_month"] == 3
        assert body["jd_match_scans_used_this_month"] == 0

    def test_second_call_reuses_the_same_user_not_a_new_one(self, client, db_session):
        with _mock_auth():
            client.get("/auth/me", headers=AUTH_HEADERS)
            client.get("/auth/me", headers=AUTH_HEADERS)
        from app.db.models import User
        assert db_session.query(User).count() == 1

    def test_invalid_token_is_401(self, client):
        from app.core.auth.firebase_auth import InvalidTokenError
        with patch("app.core.auth.dependencies.verify_firebase_token", side_effect=InvalidTokenError("bad token")):
            resp = client.get("/auth/me", headers=AUTH_HEADERS)
        assert resp.status_code == 401


class TestAnonymousBackwardCompatibility:
    """The whole point of the optional-auth design -- anonymous callers
    must see zero change in behavior from before Phase 3/4/9 existed."""

    def test_standalone_scan_anonymous_is_unrestricted_and_not_persisted(self, client, db_session):
        for _ in range(5):  # far more than the free tier's limit of 3
            resp = client.post("/score/standalone", json={"resume": RESUME})
            assert resp.status_code == 200
        from app.db.models import Resume, UsageLog
        assert db_session.query(Resume).count() == 0
        assert db_session.query(UsageLog).filter(UsageLog.user_id.isnot(None)).count() == 0

    def test_full_report_anonymous_response_shape_unchanged(self, client):
        resp = client.post("/score/full-report", json={"resume": RESUME, "jd_text": JD_TEXT})
        assert resp.status_code == 200
        body = resp.json()
        assert "overall_score" in body and "dimensions" in body  # same shape as always


class TestEntitlementEnforcement:
    def test_signed_in_free_tier_blocked_after_three_scans(self, client):
        with _mock_auth():
            for i in range(3):
                resp = client.post("/score/standalone", json={"resume": RESUME}, headers=AUTH_HEADERS)
                assert resp.status_code == 200, f"scan {i + 1} should succeed"
            blocked = client.post("/score/standalone", json={"resume": RESUME}, headers=AUTH_HEADERS)
        assert blocked.status_code == 429
        assert "Free plan" in blocked.json()["detail"]

    def test_full_report_counts_toward_the_same_monthly_limit(self, client):
        """jd_match and standalone scans share one entitlement pool
        (jd_match_scans_per_month) -- verify a mix of both hits the cap."""
        with _mock_auth():
            client.post("/score/standalone", json={"resume": RESUME}, headers=AUTH_HEADERS)
            client.post("/score/full-report", json={"resume": RESUME, "jd_text": JD_TEXT}, headers=AUTH_HEADERS)
            client.post("/score/standalone", json={"resume": RESUME}, headers=AUTH_HEADERS)
            blocked = client.post("/score/full-report", json={"resume": RESUME, "jd_text": JD_TEXT}, headers=AUTH_HEADERS)
        assert blocked.status_code == 429


class TestHistoryPersistence:
    def test_signed_in_scans_are_saved_and_listed_in_history(self, client):
        with _mock_auth():
            client.post("/score/standalone", json={"resume": RESUME}, headers=AUTH_HEADERS)
            client.post("/score/full-report", json={"resume": RESUME, "jd_text": JD_TEXT}, headers=AUTH_HEADERS)
            hist = client.get("/history", headers=AUTH_HEADERS)
        assert hist.status_code == 200
        entries = hist.json()["history"]
        assert len(entries) == 2
        modes = {e["mode"] for e in entries}
        assert modes == {"standalone", "jd_match"}
        assert all(e["resume_name"] == "Jordan Alvarez" for e in entries)

    def test_history_requires_auth(self, client):
        resp = client.get("/history")
        assert resp.status_code == 401

    def test_two_different_users_do_not_see_each_others_history(self, client):
        with _mock_auth(uid="user-a", email="user-a@example.com"):
            client.post("/score/standalone", json={"resume": RESUME}, headers=AUTH_HEADERS)
        with _mock_auth(uid="user-b", email="user-b@example.com"):
            hist_b = client.get("/history", headers=AUTH_HEADERS)
        assert hist_b.json()["history"] == []
