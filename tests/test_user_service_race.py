"""
Concurrent first-sign-in for the same new user.

This is not a hypothetical interleaving. DashboardPage fires GET
/auth/me and GET /history without awaiting one before the other
(frontend-react/src/pages/DashboardPage.jsx), both handlers are sync
`def` so FastAPI runs them in the threadpool simultaneously, and both
call get_or_create_user. For an account that has never been seen before,
both read "no such user" before either writes.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.auth.dependencies import AuthenticatedUser
from app.core.services.user_service import get_or_create_user
from app.db.models import Base, Subscription, User


@pytest.fixture
def sessions(tmp_path):
    """A file-backed SQLite database so two sessions hold genuinely
    separate connections -- an in-memory one shared via StaticPool would
    put both on the same connection and could not express the race."""
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


AUTH = AuthenticatedUser(uid="firebase-uid-123", email="new@example.com", name="New User")


def _let_the_other_request_win(db, Session, auth=AUTH):
    """Commit the competing request's row in the window between this
    session's SELECT and its INSERT -- the exact interleaving that makes
    the unique constraint fire."""
    fired = []

    @event.listens_for(db, "before_flush")
    def competing_request(sess, flush_context, instances):
        if fired:
            return
        fired.append(True)
        other = Session()
        try:
            get_or_create_user(other, auth)
        finally:
            other.close()

    return fired


def test_losing_the_race_returns_the_winners_row_instead_of_raising(sessions):
    db = sessions()
    fired = _let_the_other_request_win(db, sessions)

    user = get_or_create_user(db, AUTH)  # must not raise IntegrityError

    assert fired, "the competing request never ran -- the race wasn't exercised"
    assert user.firebase_uid == AUTH.uid
    assert user.email == AUTH.email
    db.close()


def test_the_race_leaves_exactly_one_user_and_one_subscription(sessions):
    db = sessions()
    _let_the_other_request_win(db, sessions)
    get_or_create_user(db, AUTH)
    db.close()

    check = sessions()
    assert check.query(User).count() == 1
    assert check.query(Subscription).count() == 1
    subscription = check.query(Subscription).one()
    assert subscription.tier == "free"
    assert subscription.user_id == check.query(User).one().id
    check.close()


def test_both_requests_see_the_same_user_id(sessions):
    """Whichever request lost must not hand back a different identity --
    everything downstream (history, entitlements, payments) keys off it."""
    db = sessions()
    _let_the_other_request_win(db, sessions)

    loser_view = get_or_create_user(db, AUTH)
    winner_view = get_or_create_user(sessions(), AUTH)

    assert loser_view.id == winner_view.id
    db.close()


def test_an_email_collision_is_not_swallowed(sessions):
    """The other reason this insert can fail: a different Firebase uid
    carrying an email already registered. Retrying cannot resolve that,
    so it must surface rather than be mistaken for the race."""
    db = sessions()
    get_or_create_user(db, AUTH)

    same_email_different_uid = AuthenticatedUser(
        uid="a-completely-different-uid", email=AUTH.email, name="Impostor",
    )
    with pytest.raises(IntegrityError):
        get_or_create_user(sessions(), same_email_different_uid)
    db.close()


def test_the_ordinary_uncontended_path_is_unchanged(sessions):
    db = sessions()
    created = get_or_create_user(db, AUTH)
    again = get_or_create_user(db, AUTH)

    assert created.id == again.id
    assert db.query(User).count() == 1
    db.close()
