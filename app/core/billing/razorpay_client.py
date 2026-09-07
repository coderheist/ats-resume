"""
Razorpay integration -- lazily initialized from RAZORPAY_KEY_ID /
RAZORPAY_KEY_SECRET, same "degrade to a clear error, never crash the
app" pattern as app/core/auth/firebase_auth.py. Genuinely optional: if
unset, billing routes return a clear 503 rather than the app failing to
start, and every non-billing endpoint is completely unaffected.

Two signature-verification paths, both HMAC-SHA256, both real security
boundaries -- neither is a formality:

1. verify_payment_signature -- the frontend's Razorpay Checkout callback
   hands back an order_id/payment_id/signature triple after a payment
   completes. This is what proves that triple actually came from
   Razorpay and wasn't fabricated by a malicious client claiming "I
   paid" without having paid. Signature = HMAC-SHA256("{order_id}|
   {payment_id}", key_secret).

2. verify_webhook_signature -- Razorpay's own server-to-server webhook
   (payment.captured, payment.failed, etc.), the recommended source of
   truth per Razorpay's own docs precisely because it doesn't depend on
   the client's browser staying open or the client-side callback firing
   at all. Signature = HMAC-SHA256(raw_request_body, webhook_secret) --
   a SEPARATE secret from key_secret, configured in the Razorpay
   dashboard's webhook settings.

Both are implemented via the official `razorpay` SDK's own verification
methods (razorpay.errors.SignatureVerificationError on mismatch), not a
hand-rolled HMAC comparison -- no reason to reimplement something the
SDK already gets right, especially for something security-critical.
"""
from __future__ import annotations

import os

_client = None
_init_attempted = False


class BillingNotConfiguredError(Exception):
    """No RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET configured -- billing
    features are unavailable. Never raised for non-billing routes."""


class PaymentVerificationError(Exception):
    """A payment or webhook signature failed verification -- the request
    claims a payment happened but the cryptographic proof doesn't check
    out. Treat as a potential forgery attempt, not a retry-able error."""


def _get_client():
    global _client, _init_attempted
    if _client is not None:
        return _client
    if _init_attempted:
        raise BillingNotConfiguredError(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set -- billing features are unavailable."
        )
    _init_attempted = True

    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise BillingNotConfiguredError(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set -- billing features are unavailable. "
            "Set both (from the Razorpay dashboard's API Keys section) to enable checkout."
        )

    import razorpay

    _client = razorpay.Client(auth=(key_id, key_secret))
    return _client


def get_public_key_id() -> str:
    """RAZORPAY_KEY_ID specifically (not the secret) -- this is meant to
    be embedded in frontend Checkout widget calls per Razorpay's own
    docs, safe to expose in an API response, unlike key_secret."""
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    if not key_id:
        raise BillingNotConfiguredError("RAZORPAY_KEY_ID is not set -- billing features are unavailable.")
    return key_id


def create_order(*, amount: int, currency: str, receipt: str, notes: dict) -> dict:
    """amount is in the smallest currency unit (e.g. cents for USD, paise
    for INR) -- Razorpay's own convention, matching db/models.py's
    Payment.amount. Returns the raw Razorpay order dict (has "id",
    "amount", "currency", "status", ...)."""
    client = _get_client()
    return client.order.create({
        "amount": amount,
        "currency": currency,
        "receipt": receipt,
        "notes": notes,
        "payment_capture": 1,  # auto-capture -- don't require a separate manual capture step
    })


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> None:
    """Raises PaymentVerificationError on a mismatch; returns None (not a
    bool) on success -- there's nothing meaningful to do with a "verified
    but false" result, only "verified" or "an exception was raised", so
    the calling code shouldn't have a branch for a case that can't
    actually happen."""
    client = _get_client()
    from razorpay.errors import SignatureVerificationError

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
    except SignatureVerificationError as exc:
        raise PaymentVerificationError(str(exc)) from exc


def verify_webhook_signature(raw_body: str, signature: str) -> None:
    """Raises PaymentVerificationError on a mismatch. Uses
    RAZORPAY_WEBHOOK_SECRET specifically -- a different secret than
    key_secret, configured separately in the Razorpay dashboard's
    Webhooks section, precisely because a webhook signature and a
    payment signature protect against different things and shouldn't
    share a key."""
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not webhook_secret:
        raise BillingNotConfiguredError(
            "RAZORPAY_WEBHOOK_SECRET is not set -- webhook verification is unavailable."
        )

    client = _get_client()
    from razorpay.errors import SignatureVerificationError

    try:
        client.utility.verify_webhook_signature(raw_body, signature, webhook_secret)
    except SignatureVerificationError as exc:
        raise PaymentVerificationError(str(exc)) from exc


def reset_for_testing() -> None:
    """Test-only: clears the cached client, mirroring
    firebase_auth.py's reset_for_testing()."""
    global _client, _init_attempted
    _client = None
    _init_attempted = False
