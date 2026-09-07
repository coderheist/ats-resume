import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
        resp = client.post("/payments/create-order", json={"tier": "pro", "billing_cycle": "monthly", "currency": "USD"})
        assert resp.status_code == 401

    def test_unknown_tier_is_400(self, client):
        resp = client.post("/payments/create-order", json={"tier": "nonexistent", "billing_cycle": "monthly", "currency": "USD"}, headers=AUTH_HEADERS)
        assert resp.status_code == 400

    def test_free_tier_cannot_be_checked_out(self, client):
        resp = client.post("/payments/create-order", json={"tier": "free", "billing_cycle": "monthly", "currency": "USD"}, headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "free plan" in resp.json()["detail"].lower()

    def test_billing_cycle_not_offered_by_tier_is_400(self, client):
        # pro_plus has annual_price_usd=None in config.py
        resp = client.post("/payments/create-order", json={"tier": "pro_plus", "billing_cycle": "annual", "currency": "USD"}, headers=AUTH_HEADERS)
        assert resp.status_code == 400
        assert "annual" in resp.json()["detail"]

    def test_invalid_billing_cycle_string_is_400(self, client):
        resp = client.post("/payments/create-order", json={"tier": "pro", "billing_cycle": "weekly", "currency": "USD"}, headers=AUTH_HEADERS)
        assert resp.status_code == 400

    def test_returns_503_when_razorpay_not_configured(self, client, monkeypatch):
        monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
        resp = client.post("/payments/create-order", json={"tier": "pro", "billing_cycle": "monthly", "currency": "USD"}, headers=AUTH_HEADERS)
        assert resp.status_code == 503


class TestCreateOrderSuccess:
    def test_creates_a_payment_row_and_returns_order_details(self, client, db_session, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")

        with patch("app.api.routes.payments.create_order", return_value={"id": "order_fake123", "amount": 2900, "currency": "USD", "status": "created"}):
            resp = client.post("/payments/create-order", json={"tier": "pro", "billing_cycle": "monthly", "currency": "USD"}, headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["order_id"] == "order_fake123"
        assert body["amount"] == 2900  # $29.00 -> 2900 cents
        assert body["key_id"] == "rzp_test_fake"  # public key exposed, correctly
        assert "key_secret" not in body and "fake_secret" not in json.dumps(body)  # secret never exposed

        payment = db_session.query(Payment).filter(Payment.razorpay_order_id == "order_fake123").first()
        assert payment is not None
        assert payment.status == "created"
        assert payment.tier == "pro"
        assert payment.amount == 2900


class TestVerifyPayment:
    def _seed_payment(self, db_session, order_id="order_abc", tier="pro", billing_cycle="monthly"):
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
        db_session.add(Payment(user_id=user.id, tier="pro", billing_cycle="monthly", amount=2900, currency="USD", razorpay_order_id=order_id, status="created"))
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
