"""
SQLAlchemy models. Canonical resume content lives in `resumes.data` as JSONB
(the JSON Resume schema) -- see blueprint Section 4.5. Embeddings live
alongside it in `resumes.embedding` via pgvector so re-scoring after a live
voice edit is a single indexed lookup, not a re-embed-the-world operation.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Integer, String, JSON, Boolean,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    # The real external identity reference once Firebase Auth is
    # configured (see app/core/auth/firebase_auth.py) -- nullable because
    # this column was added after `email` already existed as the sole
    # identifier; a User row is looked up/created by firebase_uid going
    # forward (services/user_service.py), with email kept for display
    # and as a fallback lookup for any pre-auth data.
    firebase_uid = Column(String, unique=True, nullable=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    resumes = relationship("Resume", back_populates="owner")
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    usage_logs = relationship("UsageLog", back_populates="user")


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    data = Column(JSON, nullable=False)  # JsonResume.model_dump()
    # embedding: Vector(384) -- requires the pgvector extension; see
    # infra/schema.sql. Declared there rather than via the SQLAlchemy base
    # so this file has no hard dependency on the pgvector python package.
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="resumes")
    scan_results = relationship("ScanResult", back_populates="resume")


class ScanResult(Base):
    __tablename__ = "scan_results"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    resume_id = Column(UUID(as_uuid=False), ForeignKey("resumes.id"), nullable=False)
    mode = Column(String, nullable=False)  # "jd_match" | "standalone"
    jd_text = Column(String, nullable=True)
    final_score = Column(Float, nullable=False)
    breakdown = Column(JSON, nullable=False)  # ScoreBreakdown.to_xai_dict()
    created_at = Column(DateTime, default=datetime.utcnow)

    resume = relationship("Resume", back_populates="scan_results")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), unique=True, nullable=False)
    tier = Column(String, nullable=False, default="free")  # see app/config.py PRICING_TIERS
    voice_minutes_used_this_period = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    renews_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="subscription")


class Payment(Base):
    """
    One row per checkout attempt -- created in "created" status the
    moment a Razorpay order is created (before the user has necessarily
    paid), then updated to "paid" or "failed". Kept even for
    never-completed checkouts (status stays "created") -- that's real,
    useful signal (abandoned checkouts), not noise to discard.

    razorpay_order_id is set immediately; razorpay_payment_id is only
    set once a payment actually completes (nullable until then).
    Amount/currency are stored in the smallest currency unit (cents/
    paise), matching what Razorpay's own API expects and returns --
    storing a float dollar amount here would just reintroduce the
    rounding questions the smallest-unit convention exists to avoid.
    """
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    tier = Column(String, nullable=False)  # which tier this checkout was for -- see app/config.py
    # The pass length this payment bought, as a label like "7d"/"30d"/"90d".
    # Named billing_cycle for historical reasons -- it held "monthly" /
    # "annual" when plans auto-renewed. Kept rather than renamed because
    # it is purely a record of what was sold (useful for reconciliation
    # and refunds) and nothing reads it to make a decision: activation
    # takes the duration from the tier, so a rename would be a migration
    # with no behavioural payoff.
    billing_cycle = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)  # smallest currency unit
    currency = Column(String, nullable=False)  # "USD" | "INR" | ...
    razorpay_order_id = Column(String, nullable=False, unique=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True, index=True)
    status = Column(String, nullable=False, default="created")  # created | paid | failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class UsageLog(Base):
    """
    One row per billable/countable action -- both LLM calls (cost
    tracking, Phase 7 of the architecture plan) and scoring requests
    (entitlement enforcement, Phase 9: jd_match_scans_per_month in
    config.py's Tier is checked by counting this table, not a separate
    counter that could drift out of sync with what actually happened).

    user_id is nullable: an anonymous (unauthenticated) scoring request
    is still worth recording for aggregate cost visibility, it's just
    never counted against any user's monthly entitlement.
    """
    __tablename__ = "usage_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String, nullable=False)  # "jd_match_scan" | "standalone_scan" | "llm_call"
    provider = Column(String, nullable=True)  # "claude" | "gemini" | "groq" -- only for llm_call
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="usage_logs")
