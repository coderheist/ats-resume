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
    email = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    resumes = relationship("Resume", back_populates="owner")
    subscription = relationship("Subscription", back_populates="user", uselist=False)


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
