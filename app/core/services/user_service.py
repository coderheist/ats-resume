"""
Bridges a verified Firebase identity (AuthenticatedUser, from a request's
bearer token) to a local User row. Firebase owns "who is this person";
this app's DB owns "what do we know about them" (subscription, saved
resumes, usage) -- this is the one place those two get connected.
"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
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
    try:
        db.add(user)
        db.flush()  # populate user.id before creating the FK-dependent row

        db.add(Subscription(user_id=user.id, tier="free"))
        db.commit()
    except IntegrityError:
        # Lost a race with another request for the SAME new user, which
        # is not an exotic case -- it is the ordinary first page load.
        # The lookup above and this insert are separate statements, so
        # two requests can both read "no such user" before either
        # writes. DashboardPage issues GET /auth/me and GET /history
        # without awaiting one before the other, and both handlers are
        # sync `def`, so FastAPI runs them in the threadpool at the same
        # moment and both call this function. Whichever flushes second
        # violates users.firebase_uid's unique constraint and, before
        # this, surfaced as an uncaught 500 -- on the very first
        # authenticated request a new account ever makes.
        #
        # The constraint is doing its job, so the fix is to treat it as
        # the answer rather than an error: roll back (which also leaves
        # the session usable, since a failed flush poisons it until
        # something does) and re-read. The winning request has committed
        # by definition -- that is what made this one fail -- so the row
        # is now visible and is the same row this request would have
        # created.
        db.rollback()
        existing = db.query(User).filter(User.firebase_uid == auth_user.uid).first()
        if existing is not None:
            return existing
        # Not the race: nothing exists under this uid, so the conflict
        # was on users.email instead -- a second Firebase account
        # carrying an address already registered to a different uid,
        # possible only when "one account per email address" is turned
        # off in the Firebase console. Retrying cannot help, and
        # inventing a new email would silently split one person across
        # two accounts, so this is left to surface rather than guessed
        # at.
        raise
    db.refresh(user)
    return user
