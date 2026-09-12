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
        bought = datetime(2026, 5, 20)
        for tier_id in ("boost", "pro", "pro_season"):
            tier = entitlement_for(tier_id)
            subscription = Subscription(
                user_id="u1", tier=tier_id, active=True,
                renews_at=bought + timedelta(days=tier.duration_days),
            )
            # `now` pinned inside the pass, not left to default to the
            # real wall clock: with the pass live/expired check in place,
            # an unpinned `now` on a real date past 2026-05-20 would make
            # every one of these already-expired, which is exactly the
            # condition under test elsewhere -- this test is specifically
            # about a still-live pass's window length.
            start, end = period_bounds(tier, subscription, now=bought + timedelta(hours=1))
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


class _ScriptedClient:
    """A minimal LLMClient stand-in whose create_message returns (or
    raises) one scripted result per call, in order, so a test can assert
    exactly how many times the model was actually called and see what
    each call's messages contained.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create_message(self, *, model, system, messages, tools=None, max_tokens=1024):
        self.calls.append({"model": model, "system": system, "messages": messages})
        if not self.script:
            raise AssertionError("create_message called more times than scripted")
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {"content": [{"type": "text", "text": outcome}]}


VALID_REPLY = '{"bullets": [{"original": "x", "rewritten": "Owned x end to end.", "needs_metric": false, "metric_hint": ""}]}'


class TestRewriteRetriesOnceOnUnparsableReply:
    """The behaviour added after a real, unreproduced 502 in production
    turned up a live bug (a duplicated LLM_PROVIDER env line silently
    routing every call to the wrong provider) but no defect in the retry
    logic itself. This still closes a real gap: a smaller/cheaper model
    occasionally wraps its answer in a stray sentence despite being told
    not to, and one corrective retry is far more reliable than none."""

    def test_a_malformed_first_reply_is_corrected_by_one_retry(self):
        from app.core.llm.bullet_rewrite import rewrite_bullets

        client = _ScriptedClient(["Sure! Here is the answer you wanted.", VALID_REPLY])
        result = rewrite_bullets(client, ["Responsible for x."], model="fake-model")

        assert len(client.calls) == 2
        assert result[0].rewritten == "Owned x end to end."

        # The retry must hand the model concrete feedback, not just repeat
        # the same request and hope for different luck: the bad reply goes
        # back in as an assistant turn, and a plain corrective instruction
        # follows it as a new user turn.
        retry_messages = client.calls[1]["messages"]
        assert retry_messages[-2] == {"role": "assistant", "content": "Sure! Here is the answer you wanted."}
        assert retry_messages[-1]["role"] == "user"
        assert "JSON" in retry_messages[-1]["content"]

    def test_two_bad_replies_in_a_row_raise_rather_than_retry_again(self):
        """One corrective attempt is the policy, not a loop -- a model
        that cannot produce valid JSON twice in a row is a real failure
        to report to the route (which turns it into a 502 and leaves the
        allowance untouched), not something to keep hammering."""
        from app.core.llm.bullet_rewrite import rewrite_bullets

        client = _ScriptedClient(["nope", "still not json"])
        with pytest.raises(ValueError):
            rewrite_bullets(client, ["Responsible for x."], model="fake-model")

        assert len(client.calls) == 2, "must not retry more than once"

    def test_a_client_side_error_is_never_retried(self):
        """A network error, an invalid key, a rate limit -- these are
        provider/infrastructure failures, not 'the model said something
        odd', and retrying them risks hammering an already-failing or
        already-rate-limited API. They must propagate on the first
        attempt with no retry."""
        from app.core.llm.bullet_rewrite import rewrite_bullets

        client = _ScriptedClient([RuntimeError("upstream 429")])
        with pytest.raises(RuntimeError, match="upstream 429"):
            rewrite_bullets(client, ["Responsible for x."], model="fake-model")

        assert len(client.calls) == 1

    def test_a_clean_first_reply_needs_no_retry(self):
        from app.core.llm.bullet_rewrite import rewrite_bullets

        client = _ScriptedClient([VALID_REPLY])
        result = rewrite_bullets(client, ["Responsible for x."], model="fake-model")

        assert len(client.calls) == 1
        assert result[0].rewritten == "Owned x end to end."


class TestExpiredPassFallsBackToFree:
    """Regression coverage for a bug found by manual reproduction:
    Subscription.active is set True at purchase (payments.py) and never
    flipped back off by anything in this codebase -- no cron job, no
    lazy-expiry write-back. Before this fix, a subscription whose pass
    had genuinely ended kept being treated as a live paid tier forever,
    counted against a window frozen at the pass's own expiry instant.
    Reproduced directly: a fully-spent 7-day Boost pass, checked 70 days
    after it ended, reported allowed=True/tier=boost with `used` frozen
    at its pass-week count -- any usage recorded after the real expiry
    fell outside that dead window and was never counted at all.
    """

    def _make_user_with_expired_pass(self, db_session, tier_id, days_since_expiry, scans_used_during_pass=0):
        import uuid
        from app.config import entitlement_for
        from app.db.models import Subscription, User, UsageLog

        user = User(id=str(uuid.uuid4()), firebase_uid=f"fb-{uuid.uuid4()}", email="x@example.com")
        db_session.add(user)
        db_session.commit()

        tier = entitlement_for(tier_id)
        bought = datetime.utcnow() - timedelta(days=tier.duration_days + days_since_expiry)
        renews_at = bought + timedelta(days=tier.duration_days)
        db_session.add(Subscription(user_id=user.id, tier=tier_id, active=True, renews_at=renews_at))
        for i in range(scans_used_during_pass):
            db_session.add(UsageLog(user_id=user.id, action="jd_match_scan", created_at=bought + timedelta(hours=i)))
        db_session.commit()
        return user

    def test_a_pass_that_ended_long_ago_falls_back_to_free_not_stuck_on_the_old_tier(self, db_session):
        from app.core.services.entitlement_service import check_scan_allowance
        user = self._make_user_with_expired_pass(db_session, "boost", days_since_expiry=70, scans_used_during_pass=10)

        check = check_scan_allowance(db_session, user)

        assert check.tier == "free", "an expired Boost pass must not still report as 'boost'"
        assert check.limit == 5, "must be checked against Free's own allowance, not Boost's"
        assert check.used == 0, "this month's real Free usage, not a frozen count from the dead pass"
        assert check.allowed is True

    def test_a_fully_spent_expired_pass_does_not_lock_the_user_out_forever(self, db_session):
        """Before the fix: a buyer who used their whole pass during its
        real week stayed permanently locked out afterwards, because
        `used` was frozen at the limit inside a window that could never
        advance. They must instead get their Free-tier allowance back."""
        from app.core.services.entitlement_service import check_scan_allowance
        from app.config import B2C_TIERS
        # days_since_expiry has to push the purchase into a PRIOR calendar
        # month, not just past the pass's own expiry -- otherwise the old
        # usage logs land inside the current month and get correctly
        # counted against the fresh Free-tier allowance too, which is
        # right behaviour but makes a same-month `days_since_expiry` the
        # wrong choice for isolating "does an old pass's usage keep
        # counting against you forever" from "did you also use Free's
        # monthly allowance up this month".
        user = self._make_user_with_expired_pass(
            db_session, "boost", days_since_expiry=40, scans_used_during_pass=B2C_TIERS["boost"].jd_match_scans,
        )

        check = check_scan_allowance(db_session, user)

        assert check.allowed is True
        assert check.tier == "free"

    def test_usage_after_expiry_is_actually_counted_not_dropped_into_a_dead_window(self, db_session):
        """Before the fix, any scan recorded after the pass's own expiry
        fell outside the frozen [start, end) window and was never counted
        toward anything -- effectively unlimited, permanently free usage.
        It must now count against the live Free-tier month instead."""
        from app.core.services.entitlement_service import check_scan_allowance, record_scan
        from app.config import B2C_TIERS
        user = self._make_user_with_expired_pass(db_session, "boost", days_since_expiry=20)

        for _ in range(B2C_TIERS["free"].jd_match_scans):
            record_scan(db_session, user, "jd_match_scan")

        check = check_scan_allowance(db_session, user)
        assert check.used == B2C_TIERS["free"].jd_match_scans
        assert check.allowed is False, "Free's own limit must actually bind once reached"

    def test_a_pass_still_within_its_window_is_unaffected(self, db_session):
        """The fix must not touch the common, correct case: a live pass
        with time left keeps its own tier and its own allowance."""
        from app.core.services.entitlement_service import check_scan_allowance
        user = self._make_user_with_expired_pass(db_session, "pro", days_since_expiry=-25)  # 25 days still left

        check = check_scan_allowance(db_session, user)

        assert check.tier == "pro"
        assert check.limit == 100

    def test_the_rewrite_route_stops_routing_an_expired_pass_to_the_paid_model(self, client, db_session):
        """The second half of the same bug: the route used to re-derive
        the tier itself from `subscription.active` alone (ignoring
        expiry) purely to pick which model quality serves the rewrite --
        so an expired user could be correctly capped at Free's allowance
        by check_rewrite_allowance, yet still silently routed to the
        paid tier's better model for the one request they had left. The
        route now reuses check.tier instead of re-deriving it."""
        user = self._make_user_with_expired_pass(db_session, "pro", days_since_expiry=5)

        captured = {}

        def _capturing_get_client_for(task, **kwargs):
            captured["task"] = task
            return object(), "fake-model"

        with _mock_auth(uid=user.firebase_uid), \
                patch("app.api.routes.rewrite.rewrite_bullets", _fake_rewrite), \
                patch("app.api.routes.rewrite.get_client_for", _capturing_get_client_for):
            resp = client.post("/resume/rewrite-bullets", json={"bullets": BULLETS}, headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["tier"] == "free", "must report as Free, not the expired Pro tier"
        from app.core.llm.tier_routing import rewrite_task_for_tier
        from app.config import B2C_TIERS
        assert captured["task"] == rewrite_task_for_tier(B2C_TIERS["free"]), (
            "must route to Free's model quality, not Pro's, once the pass has expired"
        )
