"""
Covers the two things the pass-based pricing model added: a second,
independent allowance for AI bullet rewrites, and an allowance window
anchored to when a pass was bought rather than to the calendar.

The pass-window tests matter more than they look. Under the previous
calendar-month model, a 7-day Boost bought on the 28th would have had its
whole allowance wiped on the 1st -- four days early, for a customer who
had paid. That is a refund, a support ticket, and a plausible chargeback,
and it is invisible in any test that only ever buys on the 1st.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import B2C_TIERS, entitlement_for
from app.core.services.entitlement_service import (
    check_rewrite_allowance,
    period_bounds,
    record_rewrite,
)
from app.db.models import Base, Subscription, UsageLog
from app.db.session import get_db
from app.main import app

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
BULLETS = ["Responsible for the billing system.", "Helped with monitoring."]


@pytest.fixture
def db_session():
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


def _mock_auth(uid="test-uid"):
    return patch(
        "app.core.auth.dependencies.verify_firebase_token",
        return_value={"uid": uid, "email": "jordan@example.com", "name": "Jordan Alvarez"},
    )


def _fake_rewrite(*args, **kwargs):
    """Stands in for the model call. Returns the shape the route consumes
    so these tests exercise metering and routing without a network call
    or an API key -- the prompt's own behaviour is a separate concern."""
    from app.core.llm.bullet_rewrite import RewrittenBullet
    bullets = args[1] if len(args) > 1 else kwargs["bullets"]
    return [
        RewrittenBullet(original=b, rewritten=f"Rewrote: {b}", needs_metric=True, metric_hint="How many?")
        for b in bullets
    ]


class TestPassPeriodWindow:
    def test_a_seven_day_pass_bought_late_in_the_month_keeps_its_full_window(self):
        """The regression this model was designed around: a calendar-month
        window would reset this pass on the 1st, days before it expires."""
        boost = B2C_TIERS["boost"]
        bought = datetime(2026, 1, 28, 10, 0, 0)
        subscription = Subscription(
            user_id="u1", tier="boost", active=True,
            renews_at=bought + timedelta(days=boost.duration_days),
        )
        start, end = period_bounds(boost, subscription, now=datetime(2026, 2, 2))

        assert start == bought
        assert end == datetime(2026, 2, 4, 10, 0, 0)
        assert (end - start).days == 7
        # The point of the test: the window straddles the month boundary
        # instead of being truncated at it.
        assert start.month == 1 and end.month == 2

    def test_window_length_always_matches_the_tier_that_was_sold(self):
        for tier_id in ("boost", "pro", "pro_season"):
            tier = entitlement_for(tier_id)
            subscription = Subscription(
                user_id="u1", tier=tier_id, active=True,
                renews_at=datetime(2026, 5, 20) + timedelta(days=tier.duration_days),
            )
            start, end = period_bounds(tier, subscription)
            assert (end - start).days == tier.duration_days, tier_id

    def test_free_tier_falls_back_to_the_calendar_month(self):
        """Free has no purchase instant to anchor to, so the calendar
        month is both the honest answer and the least surprising one to
        show a user."""
        start, end = period_bounds(B2C_TIERS["free"], None, now=datetime(2026, 3, 17))
        assert start == datetime(2026, 3, 1)
        assert end == datetime(2026, 4, 1)

    def test_an_expired_subscription_does_not_extend_the_window(self):
        """An inactive subscription must fall back to the calendar month
        rather than keeping a stale renews_at alive as an allowance."""
        subscription = Subscription(
            user_id="u1", tier="pro", active=False,
            renews_at=datetime(2026, 1, 5),
        )
        start, end = period_bounds(B2C_TIERS["free"], subscription, now=datetime(2026, 3, 17))
        assert (start, end) == (datetime(2026, 3, 1), datetime(2026, 4, 1))


class TestRewriteAllowanceIsIndependentOfScans:
    def test_spending_every_scan_leaves_rewrites_untouched(self, client, db_session):
        """Two products, two meters. Running out of scans must not block a
        rewrite the user has already paid for."""
        resume = {"basics": {"name": "J"}, "work": [{"name": "Acme", "position": "Eng", "highlights": [{"text": "Did work."}]}]}
        with _mock_auth():
            for _ in range(B2C_TIERS["free"].jd_match_scans):
                client.post("/score/standalone", json={"resume": resume}, headers=AUTH_HEADERS)
            body = client.get("/auth/me", headers=AUTH_HEADERS).json()

        assert body["scans_exhausted"] is True
        assert body["rewrites_used"] == 0
        assert body["rewrites_exhausted"] is False

    def test_rewrites_are_counted_and_then_refused_at_the_limit(self, client, db_session):
        limit = B2C_TIERS["free"].ai_rewrites
        with _mock_auth(), patch("app.api.routes.rewrite.rewrite_bullets", _fake_rewrite), \
                patch("app.api.routes.rewrite.get_client_for", return_value=(object(), "fake-model")):
            for i in range(limit):
                resp = client.post("/resume/rewrite-bullets", json={"bullets": BULLETS}, headers=AUTH_HEADERS)
                assert resp.status_code == 200, f"rewrite {i + 1} should succeed"
                assert resp.json()["rewrites_used"] == i + 1
            blocked = client.post("/resume/rewrite-bullets", json={"bullets": BULLETS}, headers=AUTH_HEADERS)

        assert blocked.status_code == 429
        detail = blocked.json()["detail"]
        assert detail["error"] == "rewrite_limit_reached"
        assert detail["limit"] == limit
        assert "Free plan" in detail["message"]

    def test_one_request_is_one_rewrite_regardless_of_bullet_count(self, client, db_session):
        """The pricing page sells "100 rewrites", and a user counts a
        role's worth of bullets as one. Metering per bullet would make the
        allowance mean something different from what was advertised."""
        with _mock_auth(), patch("app.api.routes.rewrite.rewrite_bullets", _fake_rewrite), \
                patch("app.api.routes.rewrite.get_client_for", return_value=(object(), "fake-model")):
            resp = client.post(
                "/resume/rewrite-bullets",
                json={"bullets": ["one", "two", "three", "four", "five"]},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["rewrites_used"] == 1
        assert db_session.query(UsageLog).filter(UsageLog.action == "ai_rewrite").count() == 1


class TestRewriteFailuresDoNotSpendAllowance:
    def test_a_model_failure_is_a_502_and_costs_nothing(self, client, db_session):
        """The version of this bug people actually complain about: paying
        an allowance unit for a request that errored."""
        def boom(*a, **kw):
            raise RuntimeError("provider exploded")

        with _mock_auth(), patch("app.api.routes.rewrite.rewrite_bullets", boom), \
                patch("app.api.routes.rewrite.get_client_for", return_value=(object(), "fake-model")):
            resp = client.post("/resume/rewrite-bullets", json={"bullets": BULLETS}, headers=AUTH_HEADERS)

        assert resp.status_code == 502
        assert "has not been used" in resp.json()["detail"]
        assert db_session.query(UsageLog).filter(UsageLog.action == "ai_rewrite").count() == 0

    def test_no_configured_provider_is_a_503_and_costs_nothing(self, client, db_session):
        def no_client(*a, **kw):
            raise RuntimeError("no API key configured")

        with _mock_auth(), patch("app.api.routes.rewrite.get_client_for", no_client):
            resp = client.post("/resume/rewrite-bullets", json={"bullets": BULLETS}, headers=AUTH_HEADERS)

        assert resp.status_code == 503
        assert db_session.query(UsageLog).filter(UsageLog.action == "ai_rewrite").count() == 0


class TestRewriteRequiresAnAccount:
    def test_anonymous_rewrite_is_refused(self, client):
        """Scoring is open to anonymous visitors on purpose; a rewrite is
        the metered, paid feature, so serving it unauthenticated would
        hand an uncapped allowance to anyone who clears their cookies."""
        resp = client.post("/resume/rewrite-bullets", json={"bullets": BULLETS})
        assert resp.status_code == 401

    def test_the_allowance_check_itself_refuses_anonymous(self, db_session):
        check = check_rewrite_allowance(db_session, None)
        assert check.allowed is False
        assert check.tier == "anonymous"


class TestRewriteRequestValidation:
    def test_empty_bullets_is_a_400_not_a_wasted_call(self, client):
        with _mock_auth():
            resp = client.post("/resume/rewrite-bullets", json={"bullets": ["", "   "]}, headers=AUTH_HEADERS)
        assert resp.status_code == 400

    def test_too_many_bullets_is_a_400(self, client):
        from app.core.llm.bullet_rewrite import MAX_BULLETS_PER_REQUEST
        with _mock_auth():
            resp = client.post(
                "/resume/rewrite-bullets",
                json={"bullets": ["x"] * (MAX_BULLETS_PER_REQUEST + 1)},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400


class TestTierModelRouting:
    def test_free_and_paid_tiers_route_rewrites_to_different_models(self):
        """The tiers have to actually differ somewhere the user can see,
        and the rewrite is the only place model quality is visible in the
        output -- scores are computed locally and identical on every plan."""
        from app.core.llm.tier_routing import rewrite_task_for_tier, scan_task_for_tier
        from app.core.llm.router import Provider, route

        free_task = rewrite_task_for_tier(B2C_TIERS["free"])
        pro_task = rewrite_task_for_tier(B2C_TIERS["pro"])
        assert free_task is not pro_task
        assert route(free_task, Provider.GEMINI) == "gemini-3.5-flash-lite"
        assert route(pro_task, Provider.GEMINI) == "gemini-3.6-flash"

    def test_scanning_is_the_same_model_on_every_tier(self):
        """Paying more must not buy a different score. The number comes
        from local scoring either way, so charging for a 'better' scan
        model would be selling something that does not exist."""
        from app.core.llm.tier_routing import scan_task_for_tier
        tasks = {scan_task_for_tier(t) for t in B2C_TIERS.values()}
        assert len(tasks) == 1

    def test_an_unknown_quality_label_fails_loudly(self):
        from app.core.llm.tier_routing import task_for_quality
        with pytest.raises(ValueError, match="Unknown model-quality label"):
            task_for_quality("luxury")


class TestBulletRewriteHonesty:
    """The rule the whole feature depends on: never invent a metric.

    A rewrite that fabricates "reduced costs by 30%" writes a claim the
    candidate must defend in an interview and cannot. These pin the
    machinery that keeps the flag honest; the prompt itself carries the
    instruction.
    """

    def test_a_short_model_response_never_drops_a_candidates_bullet(self):
        from app.core.llm.bullet_rewrite import _coerce
        originals = ["first bullet", "second bullet", "third bullet"]
        payload = {"bullets": [{"rewritten": "Rewrote first.", "needs_metric": False}]}
        out = _coerce(payload, originals)
        assert len(out) == 3
        assert out[1].rewritten == "second bullet"  # falls back, never lost
        assert out[2].rewritten == "third bullet"

    def test_needs_metric_is_inferred_when_the_model_omits_it(self):
        from app.core.llm.bullet_rewrite import _coerce
        payload = {"bullets": [
            {"rewritten": "Cut latency from 800ms to 120ms."},
            {"rewritten": "Improved the deployment process."},
        ]}
        out = _coerce(payload, ["a", "b"])
        assert out[0].needs_metric is False  # has a number
        assert out[1].needs_metric is True   # has none

    def test_json_wrapped_in_a_code_fence_is_still_read(self):
        from app.core.llm.bullet_rewrite import _extract_json
        assert _extract_json('```json\n{"bullets": []}\n```') == {"bullets": []}

    def test_a_response_with_no_json_raises_rather_than_guessing(self):
        from app.core.llm.bullet_rewrite import _extract_json
        with pytest.raises(ValueError):
            _extract_json("I'm sorry, I can't help with that.")
