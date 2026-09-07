"""
Payment routes: create a Razorpay order, verify a completed payment
(the client-side Checkout callback path), and handle Razorpay's webhook
(the server-to-server path -- see module docstring on why both exist
and how they stay idempotent with each other).

See app/core/billing/razorpay_client.py for the actual Razorpay SDK
wrapper and both signature-verification methods.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import entitlement_for
from app.core.auth.dependencies import AuthenticatedUser, get_current_user
from app.core.billing.razorpay_client import (
    BillingNotConfiguredError, PaymentVerificationError,
    create_order, get_public_key_id, verify_payment_signature, verify_webhook_signature,
)
from app.core.services.user_service import get_or_create_user
from app.db.models import Payment, Subscription, User
from app.db.session import get_db
from app.schemas.api_models import CheckoutRequest, VerifyPaymentRequest

router = APIRouter(prefix="/payments", tags=["payments"])

_BILLING_CYCLE_FIELD = {"monthly": "monthly_price_usd", "annual": "annual_price_usd"}
_BILLING_CYCLE_DAYS = {"monthly": 30, "annual": 365}


def _activate_subscription(db: Session, user: User, tier_id: str, billing_cycle: str) -> None:
    """Shared by both the client-verify path and the webhook path below --
    one place that actually flips a Subscription to a paid tier, so the
    two paths (whichever fires first, or both) can't drift into
    disagreeing about what "activated" means."""
    subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if subscription is None:
        subscription = Subscription(user_id=user.id)
        db.add(subscription)
    subscription.tier = tier_id
    subscription.active = True
    subscription.renews_at = datetime.utcnow() + timedelta(days=_BILLING_CYCLE_DAYS[billing_cycle])


@router.post("/create-order")
def create_order_route(
    request: CheckoutRequest,
    auth_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Requires sign-in -- a checkout needs an account to attach the
    resulting subscription to. Returns the Razorpay order id and the
    PUBLIC key_id (never the secret) for the frontend to open Razorpay's
    Checkout widget with."""
    if request.billing_cycle not in _BILLING_CYCLE_FIELD:
        raise HTTPException(status_code=400, detail="billing_cycle must be 'monthly' or 'annual'.")

    try:
        tier = entitlement_for(request.tier)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown tier '{request.tier}'.") from None

    price = getattr(tier, _BILLING_CYCLE_FIELD[request.billing_cycle])
    if price is None:
        raise HTTPException(status_code=400, detail=f"The '{tier.name}' plan doesn't offer {request.billing_cycle} billing.")
    if price <= 0:
        raise HTTPException(status_code=400, detail="Can't create a checkout for a free plan.")

    user = get_or_create_user(db, auth_user)
    # Smallest currency unit (cents for USD, paise for INR) -- Razorpay's
    # own convention, matching Payment.amount's stored value; a float
    # dollar amount would just reintroduce the rounding questions this
    # convention exists to avoid.
    amount_smallest_unit = round(price * 100)

    try:
        order = create_order(
            amount=amount_smallest_unit, currency=request.currency,
            receipt=f"{user.id}-{tier.id}-{request.billing_cycle}"[:40],  # Razorpay caps receipt at 40 chars
            notes={"user_id": user.id, "tier": tier.id, "billing_cycle": request.billing_cycle},
        )
    except BillingNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    db.add(Payment(
        user_id=user.id, tier=tier.id, billing_cycle=request.billing_cycle,
        amount=amount_smallest_unit, currency=request.currency,
        razorpay_order_id=order["id"], status="created",
    ))
    db.commit()

    return {
        "order_id": order["id"], "amount": amount_smallest_unit, "currency": request.currency,
        "key_id": get_public_key_id(), "tier": tier.id, "tier_name": tier.name,
    }


@router.post("/verify")
def verify_payment_route(
    request: VerifyPaymentRequest,
    auth_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """The client-side path: Razorpay's Checkout widget calls this with
    the order_id/payment_id/signature triple after a payment completes
    in the browser. Verified independently of the webhook below --
    either path activating the subscription first is fine, the other is
    a no-op (see the idempotency check in each)."""
    user = get_or_create_user(db, auth_user)
    payment = (
        db.query(Payment)
        .filter(Payment.razorpay_order_id == request.razorpay_order_id, Payment.user_id == user.id)
        .first()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="No matching order found for this account.")

    try:
        verify_payment_signature(request.razorpay_order_id, request.razorpay_payment_id, request.razorpay_signature)
    except BillingNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PaymentVerificationError as exc:
        payment.status = "failed"
        db.commit()
        raise HTTPException(status_code=400, detail=f"Payment verification failed: {exc}") from exc

    if payment.status != "paid":  # idempotent -- this or the webhook may already have done this
        payment.razorpay_payment_id = request.razorpay_payment_id
        payment.status = "paid"
        _activate_subscription(db, user, payment.tier, payment.billing_cycle)
        db.commit()

    return {"status": "paid", "tier": payment.tier}


@router.post("/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Razorpay's server calls this directly -- no bearer token, no
    get_current_user, since this isn't a signed-in user's request. The
    webhook SIGNATURE (verified below, a separate secret from the
    payment-signature one) is the only thing authenticating this
    request. Per Razorpay's own docs, this is the recommended source of
    truth for payment status specifically because it doesn't depend on
    the client's browser staying open long enough for /verify above to
    ever fire -- a closed tab or a crashed browser shouldn't mean a real
    payment never gets recorded.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    try:
        verify_webhook_signature(raw_body.decode("utf-8"), signature)
    except BillingNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PaymentVerificationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid webhook signature: {exc}") from exc

    payload = json.loads(raw_body)
    event = payload.get("event")

    if event == "payment.captured":
        entity = payload["payload"]["payment"]["entity"]
        payment = db.query(Payment).filter(Payment.razorpay_order_id == entity["order_id"]).first()
        if payment and payment.status != "paid":  # idempotent -- see /verify's docstring
            payment.razorpay_payment_id = entity["id"]
            payment.status = "paid"
            user = db.query(User).filter(User.id == payment.user_id).first()
            if user:
                _activate_subscription(db, user, payment.tier, payment.billing_cycle)
            db.commit()
    elif event == "payment.failed":
        entity = payload["payload"]["payment"]["entity"]
        payment = db.query(Payment).filter(Payment.razorpay_order_id == entity.get("order_id")).first()
        if payment and payment.status == "created":
            payment.status = "failed"
            db.commit()

    return {"status": "ok"}
