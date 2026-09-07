"""
Bridges a verified Firebase identity (AuthenticatedUser, from a request's
bearer token) to a local User row. Firebase owns "who is this person";
this app's DB owns "what do we know about them" (subscription, saved
resumes, usage) -- this is the one place those two get connected.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.auth.dependencies import AuthenticatedUser
from app.db.models import Subscription, User


def get_or_create_user(db: Session, auth_user: AuthenticatedUser) -> User:
    user = db.query(User).filter(User.firebase_uid == auth_user.uid).first()
    if user is not None:
        return user

    # A user authenticated via Firebase for the first time -- create the
    # local row (and a free-tier Subscription alongside it, so every
    # user always has one rather than every caller needing to handle
    # "what if there's no subscription row yet").
    user = User(
        firebase_uid=auth_user.uid,
        email=auth_user.email or f"{auth_user.uid}@no-email.firebase",
        name=auth_user.name,
    )
    db.add(user)
    db.flush()  # populate user.id before creating the FK-dependent row

    db.add(Subscription(user_id=user.id, tier="free"))
    db.commit()
    db.refresh(user)
    return user
