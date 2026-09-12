import hashlib
import itertools
import hmac
import json
from dataclasses import replace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import B2C_TIERS
from app.core.billing import razorpay_client
from app.db.models import Base, Payment, Subscription
from app.db.session import get_db
from app.main import app

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}


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


@pytest.fixture(autouse=True)
def _mock_auth():
    with patch(
        "app.core.auth.dependencies.verify_firebase_token",
        return_value={"uid": "test-uid", "email": "jordan@example.com", "name": "Jordan"},
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_razorpay_client():
    razorpay_client.reset_for_testing()
    yield
    razorpay_client.reset_for_testing()


def _sign_payment(order_id: str, payment_id: str, key_secret: str) -> str:
    """Replicates razorpay.utility.Utility.verify_payment_signature's own
    algorithm exactly (order_id|payment_id, HMAC-SHA256) -- this is what
    makes the "valid signature succeeds" tests below meaningfully real,
    not just "garbage signature fails", which would be trivial."""
    msg = f"{order_id}|{payment_id}"
    return hmac.new(key_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _sign_webhook(raw_body: bytes, webhook_secret: str) -> str:
    return hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()


class TestCreateOrderValidation:
    def test_requires_auth(self, client):
        resp = client.post("/payments/create-order", json={"tier": "pro", "currency": "USD"})
        assert resp.status_code == 401

    def test_unknown_tier_is_400(self, client):
        resp = client.post("/payments/create-order", json={"tier": "nonexistent", "currency": "USD"}, headers=AUTH_HEADERS)
        assert resp.status_code == 400

    def test_free_tier_cannot_be_checked_out(self, client):
        resp = client.post("/payments/create-order", json={"tier": "free", "currency": "USD"}, headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "free plan" in resp.json()["detail"].lower()

    def test_every_consumer_tier_is_purchasable_in_both_currencies(self, client, monkeypatch):
        """Replaces the old "this tier doesn't offer annual billing"
        tests. Plans are now fixed-length passes with exactly one price
        per currency, so there is no combination that can be unavailable
        -- and that is worth pinning, because the previous model's
        None-priced combinations were a real source of 400s."""
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        seq = itertools.count()
        monkeypatch.setattr(
            "app.api.routes.payments.create_order",
            lambda **kw: {"id": f"order_{next(seq)}", **kw},
        )
        for tier_id in ("boost", "pro", "pro_season"):
            for currency in ("USD", "INR"):
                resp = client.post(
                    "/payments/create-order",
                    json={"tier": tier_id, "currency": currency},
                    headers=AUTH_HEADERS,
                )
                assert resp.status_code == 200, f"{tier_id}/{currency}: {resp.text}"

    def test_returns_503_when_razorpay_not_configured(self, client, monkeypatch):
        monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
        resp = client.post("/payments/create-order", json={"tier": "pro", "currency": "USD"}, headers=AUTH_HEADERS)
        assert resp.status_code == 503


class TestCreateOrderSuccess:
    def test_creates_a_payment_row_and_returns_order_details(self, client, db_session, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")

        with patch("app.api.routes.payments.create_order", return_value={"id": "order_fake123", "amount": 2900, "currency": "USD", "status": "created"}):
            resp = client.post("/payments/create-order", json={"tier": "pro", "currency": "USD"}, headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["order_id"] == "order_fake123"
        assert body["amount"] == 1299  # pro, $12.99 -> 1299 cents
        assert body["key_id"] == "rzp_test_fake"  # public key exposed, correctly
        assert "key_secret" not in body and "fake_secret" not in json.dumps(body)  # secret never exposed

        payment = db_session.query(Payment).filter(Payment.razorpay_order_id == "order_fake123").first()
        assert payment is not None
        assert payment.status == "created"
        assert payment.tier == "pro"
        assert payment.amount == 1299


class TestVerifyPayment:
    def _seed_payment(self, db_session, order_id="order_abc", tier="pro", billing_cycle="30d"):
        from app.core.services.user_service import get_or_create_user
        from app.core.auth.dependencies import AuthenticatedUser
        user = get_or_create_user(db_session, AuthenticatedUser(uid="test-uid", email="jordan@example.com", name="Jordan"))
        db_session.add(Payment(user_id=user.id, tier=tier, billing_cycle=billing_cycle, amount=2900, currency="USD", razorpay_order_id=order_id, status="created"))
        db_session.commit()
        return user

    def test_valid_signature_activates_subscription(self, client, db_session, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        self._seed_payment(db_session, order_id="order_abc")
        signature = _sign_payment("order_abc", "pay_xyz", "fake_secret")

        resp = client.post("/payments/verify", json={
            "razorpay_order_id": "order_abc", "razorpay_payment_id": "pay_xyz", "razorpay_signature": signature,
        }, headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["status"] == "paid"
        payment = db_session.query(Payment).filter(Payment.razorpay_order_id == "order_abc").first()
        assert payment.status == "paid"
        assert payment.razorpay_payment_id == "pay_xyz"
        subscription = db_session.query(Subscription).filter(Subscription.user_id == payment.user_id).first()
        assert subscription.tier == "pro"
        assert subscription.active is True

    def test_invalid_signature_is_rejected_and_marks_payment_failed(self, client, db_session, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        self._seed_payment(db_session, order_id="order_bad_sig")

        resp = client.post("/payments/verify", json={
            "razorpay_order_id": "order_bad_sig", "razorpay_payment_id": "pay_xyz", "razorpay_signature": "not-a-real-signature",
        }, headers=AUTH_HEADERS)

        assert resp.status_code == 400
        payment = db_session.query(Payment).filter(Payment.razorpay_order_id == "order_bad_sig").first()
        assert payment.status == "failed"

    def test_signature_computed_with_wrong_secret_is_rejected(self, client, db_session, monkeypatch):
        """A signature that's real HMAC-SHA256, just with the wrong key --
        proves this isn't accidentally accepting any well-formed hex
        string, only ones signed with the actual configured secret."""
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        self._seed_payment(db_session, order_id="order_wrong_key")
        wrong_signature = _sign_payment("order_wrong_key", "pay_xyz", "a_different_secret")

        resp = client.post("/payments/verify", json={
            "razorpay_order_id": "order_wrong_key", "razorpay_payment_id": "pay_xyz", "razorpay_signature": wrong_signature,
        }, headers=AUTH_HEADERS)
        assert resp.status_code == 400

    def test_verify_is_idempotent_if_called_twice(self, client, db_session, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        self._seed_payment(db_session, order_id="order_twice")
        signature = _sign_payment("order_twice", "pay_xyz", "fake_secret")
        body = {"razorpay_order_id": "order_twice", "razorpay_payment_id": "pay_xyz", "razorpay_signature": signature}

        resp1 = client.post("/payments/verify", json=body, headers=AUTH_HEADERS)
        resp2 = client.post("/payments/verify", json=body, headers=AUTH_HEADERS)
        assert resp1.status_code == 200 and resp2.status_code == 200

    def test_no_matching_order_is_404(self, client, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        resp = client.post("/payments/verify", json={
            "razorpay_order_id": "order_never_existed", "razorpay_payment_id": "pay_xyz", "razorpay_signature": "whatever",
        }, headers=AUTH_HEADERS)
        assert resp.status_code == 404


class TestWebhook:
    def _seed_payment_for_webhook(self, db_session, order_id="order_webhook_1"):
        from app.core.services.user_service import get_or_create_user
        from app.core.auth.dependencies import AuthenticatedUser
        user = get_or_create_user(db_session, AuthenticatedUser(uid="test-uid", email="jordan@example.com", name="Jordan"))
        db_session.add(Payment(user_id=user.id, tier="pro", billing_cycle="30d", amount=2900, currency="USD", razorpay_order_id=order_id, status="created"))
        db_session.commit()
        return user

    def test_valid_webhook_signature_activates_subscription(self, client, db_session, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "webhook_secret_fake")
        self._seed_payment_for_webhook(db_session, order_id="order_webhook_1")

        payload = {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_webhook_1", "order_id": "order_webhook_1"}}},
        }
        raw_body = json.dumps(payload).encode()
        signature = _sign_webhook(raw_body, "webhook_secret_fake")

        resp = client.post("/payments/webhook", content=raw_body, headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"})
        assert resp.status_code == 200
        payment = db_session.query(Payment).filter(Payment.razorpay_order_id == "order_webhook_1").first()
        assert payment.status == "paid"
        subscription = db_session.query(Subscription).filter(Subscription.user_id == payment.user_id).first()
        assert subscription.tier == "pro"

    def test_invalid_webhook_signature_is_rejected(self, client, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "webhook_secret_fake")
        raw_body = json.dumps({"event": "payment.captured", "payload": {}}).encode()
        resp = client.post("/payments/webhook", content=raw_body, headers={"X-Razorpay-Signature": "not-real"})
        assert resp.status_code == 400

    def test_webhook_after_client_verify_is_a_harmless_no_op(self, client, db_session, monkeypatch):
        """The two paths (client /verify and this webhook) racing --
        whichever fires first activates the subscription; the second
        must not error or double-process."""
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "webhook_secret_fake")
        self._seed_payment_for_webhook(db_session, order_id="order_race")

        signature = _sign_payment("order_race", "pay_race", "fake_secret")
        verify_resp = client.post("/payments/verify", json={
            "razorpay_order_id": "order_race", "razorpay_payment_id": "pay_race", "razorpay_signature": signature,
        }, headers=AUTH_HEADERS)
        assert verify_resp.status_code == 200

        payload = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_race", "order_id": "order_race"}}}}
        raw_body = json.dumps(payload).encode()
        webhook_signature = _sign_webhook(raw_body, "webhook_secret_fake")
        webhook_resp = client.post("/payments/webhook", content=raw_body, headers={"X-Razorpay-Signature": webhook_signature})
        assert webhook_resp.status_code == 200  # no error, just a no-op

    def test_payment_failed_event_marks_payment_failed(self, client, db_session, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "webhook_secret_fake")
        self._seed_payment_for_webhook(db_session, order_id="order_will_fail")

        payload = {"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_fail", "order_id": "order_will_fail"}}}}
        raw_body = json.dumps(payload).encode()
        signature = _sign_webhook(raw_body, "webhook_secret_fake")
        resp = client.post("/payments/webhook", content=raw_body, headers={"X-Razorpay-Signature": signature})

        assert resp.status_code == 200
        payment = db_session.query(Payment).filter(Payment.razorpay_order_id == "order_will_fail").first()
        assert payment.status == "failed"


class TestWebhookMalformedPayloads:
    """
    A signed webhook whose body doesn't match the documented shape must
    still be acknowledged, not crash.

    Every payload lookup used to be a subscript, so a missing key raised
    KeyError and became an uncaught 500 -- which is the worst possible
    response here specifically. Razorpay reads 5xx as "delivery failed"
    and retries, so a single unreadable payload turns into a retry loop
    against an endpoint that can never succeed. Acknowledging is correct:
    an order_id we can't find is a webhook we have nothing to do about,
    which is how the unknown-event case already behaved.
    """

    @pytest.fixture(autouse=True)
    def _billing_env(self, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "webhook_secret_fake")

    def _send(self, client, payload):
        raw_body = json.dumps(payload).encode()
        return client.post(
            "/payments/webhook",
            content=raw_body,
            headers={
                "X-Razorpay-Signature": _sign_webhook(raw_body, "webhook_secret_fake"),
                "Content-Type": "application/json",
            },
        )

    @pytest.mark.parametrize("payload", [
        {"event": "payment.captured"},
        {"event": "payment.captured", "payload": {}},
        {"event": "payment.captured", "payload": {"payment": {}}},
        {"event": "payment.captured", "payload": {"payment": {"entity": {}}}},
        {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_1"}}}},
        {"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_1"}}}},
        {"event": "payment.captured", "payload": {"payment": None}},
        {"event": "payment.captured", "payload": None},
    ], ids=lambda p: str(p)[:48])
    def test_malformed_payload_is_acknowledged_not_a_500(self, client, payload):
        assert self._send(client, payload).status_code == 200

    def test_unknown_order_id_is_acknowledged(self, client):
        resp = self._send(client, {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_x", "order_id": "order_never_created"}}},
        })
        assert resp.status_code == 200

    def test_a_well_formed_payload_still_activates(self, client, db_session):
        """The hardening must not have broken the path that matters."""
        from app.core.auth.dependencies import AuthenticatedUser
        from app.core.services.user_service import get_or_create_user

        user = get_or_create_user(db_session, AuthenticatedUser(uid="test-uid", email="j@example.com", name="J"))
        db_session.add(Payment(
            user_id=user.id, tier="pro", billing_cycle="30d", amount=2900,
            currency="USD", razorpay_order_id="order_hardening_1", status="created",
        ))
        db_session.commit()

        resp = self._send(client, {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_h1", "order_id": "order_hardening_1"}}},
        })

        assert resp.status_code == 200
        payment = db_session.query(Payment).filter(Payment.razorpay_order_id == "order_hardening_1").first()
        assert payment.status == "paid"
        assert payment.razorpay_payment_id == "pay_h1"


class TestCreateOrderFailureModes:
    """The two paths Razorpay's own integration checklist calls out:
    an amount below the provider's floor, and the provider itself not
    answering."""

    @pytest.fixture(autouse=True)
    def _billing_env(self, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")

    def _order(self, client, tier="boost"):
        return client.post(
            "/payments/create-order",
            json={"tier": tier, "currency": "USD"},
            headers=AUTH_HEADERS,
        )

    def test_amount_below_the_floor_is_rejected_before_calling_razorpay(self, client, monkeypatch):
        """Catching it here costs nothing; letting it through costs a
        round trip and surfaces as a payment outage rather than a pricing
        mistake."""
        called = []
        monkeypatch.setattr(
            "app.api.routes.payments.create_order",
            lambda **kw: called.append(kw) or {"id": "order_x"},
        )
        # A tier priced under Razorpay's 100-unit floor.
        monkeypatch.setitem(
            B2C_TIERS, "boost",
            replace(B2C_TIERS["boost"], price_usd=0.5),
        )

        resp = self._order(client)

        assert resp.status_code == 400
        assert "minimum" in resp.json()["detail"].lower()
        assert not called, "Razorpay must not be called for an invalid amount"

    def test_provider_failure_is_a_502_and_writes_no_payment_row(self, client, db_session, monkeypatch):
        """A checkout that never reached Razorpay must leave nothing
        behind pretending it did."""
        def boom(**kwargs):
            raise RuntimeError("connection reset by peer")

        monkeypatch.setattr("app.api.routes.payments.create_order", boom)

        resp = self._order(client)

        assert resp.status_code == 502
        assert "no charge was made" in resp.json()["detail"].lower()
        assert db_session.query(Payment).count() == 0

    def test_a_working_order_is_unaffected(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.routes.payments.create_order",
            lambda **kw: {"id": "order_ok_1"},
        )

        resp = self._order(client)

        assert resp.status_code == 200
        body = resp.json()
        assert body["order_id"] == "order_ok_1"
        assert body["amount"] == 499  # boost, $4.99 -> smallest unit
        assert body["key_id"] == "rzp_test_fake"
        # The secret must never appear in a response the browser reads.
        assert "fake_secret" not in resp.text
        assert db_session.query(Payment).filter(Payment.razorpay_order_id == "order_ok_1").count() == 1


class TestCurrency:
    """USD and INR are both listed prices, never conversions of each
    other -- so a customer is charged the number the pricing page showed
    them, with no exchange rate able to move it in between."""

    @pytest.fixture(autouse=True)
    def _billing_env(self, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")

    def _order(self, client, monkeypatch, currency, tier="boost"):
        monkeypatch.setattr(
            "app.api.routes.payments.create_order",
            lambda **kw: {"id": f"order_{currency}_{tier}", **kw},
        )
        return client.post(
            "/payments/create-order",
            json={"tier": tier, "currency": currency},
            headers=AUTH_HEADERS,
        )

    def test_usd_uses_the_usd_price(self, client, monkeypatch):
        body = self._order(client, monkeypatch, "USD").json()
        assert body["currency"] == "USD"
        assert body["amount"] == 499  # $4.99 in cents

    def test_inr_uses_the_listed_inr_price_not_a_conversion(self, client, monkeypatch):
        body = self._order(client, monkeypatch, "INR").json()
        assert body["currency"] == "INR"
        assert body["amount"] == 14900  # Rs 149 in paise -- config.py's own number

    def test_each_pass_length_respects_the_currency_too(self, client, monkeypatch):
        assert self._order(client, monkeypatch, "INR", tier="pro").json()["amount"] == 39900
        assert self._order(client, monkeypatch, "USD", tier="pro").json()["amount"] == 1299
        assert self._order(client, monkeypatch, "INR", tier="pro_season").json()["amount"] == 99900
        assert self._order(client, monkeypatch, "USD", tier="pro_season").json()["amount"] == 2999

    def test_currency_is_case_insensitive(self, client, monkeypatch):
        assert self._order(client, monkeypatch, "inr").json()["currency"] == "INR"

    def test_surrounding_whitespace_is_tolerated(self, client, monkeypatch):
        """A stray space from a config value or a hand-edited request
        otherwise produced a baffling "Unsupported currency ' inr '"
        for a value that is plainly correct."""
        assert self._order(client, monkeypatch, "  inr  ").json()["currency"] == "INR"

    def test_unsupported_currency_is_a_400_naming_the_valid_ones(self, client, monkeypatch):
        resp = self._order(client, monkeypatch, "EUR")
        assert resp.status_code == 400
        assert "USD" in resp.json()["detail"] and "INR" in resp.json()["detail"]

    def test_the_stored_row_records_the_charged_currency(self, client, db_session, monkeypatch):
        """Reconciliation depends on this: an amount without its currency
        is meaningless when two are in play."""
        self._order(client, monkeypatch, "INR")
        row = db_session.query(Payment).filter(Payment.razorpay_order_id == "order_INR_boost").first()
        assert row.currency == "INR"
        assert row.amount == 14900

    def test_the_stored_row_records_the_pass_length_that_was_sold(self, client, db_session, monkeypatch):
        """Payment.billing_cycle is now a record of the pass length
        bought ("7d"/"30d"/"90d"). Nothing reads it to make a decision --
        activation takes the duration from the tier -- but reconciling a
        refund needs to know what the customer actually paid for."""
        self._order(client, monkeypatch, "INR", tier="pro_season")
        row = db_session.query(Payment).filter(Payment.razorpay_order_id == "order_INR_pro_season").first()
        assert row.billing_cycle == "90d"


class TestTiersEndpointCurrencies:
    def test_lists_both_currencies_and_a_default(self, client):
        body = client.get("/billing/tiers").json()
        assert body["currencies"] == ["USD", "INR"]
        assert body["default_currency"] == "USD"

    def test_every_tier_carries_a_price_per_currency(self, client):
        body = client.get("/billing/tiers").json()
        for group in ("consumer", "business"):
            for tid, tier in body[group].items():
                for field in ("price_usd", "price_inr", "duration_days",
                              "jd_match_scans", "ai_rewrites"):
                    assert field in tier, f"{tid} missing {field}"
