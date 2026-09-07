"""
Regression tests for a real, reproduced bug: a SQLite dev.db predating a
schema change (most concretely, User.firebase_uid being added in Phase 3)
crashed any request that touched the missing column with an uncaught
OperationalError -- a genuine 500, not a hypothetical one. See
app/db/session.py's _heal_sqlite_schema_drift docstring for the full story.
"""
import os
import sqlite3

from sqlalchemy import create_engine, inspect

from app.db.session import _heal_sqlite_schema_drift
from app.db.models import Base


def _make_stale_db(path: str) -> None:
    """A users table shaped like it was before firebase_uid/name existed --
    the exact real-world scenario this fix addresses."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, created_at TIMESTAMP)")
    conn.commit()
    conn.close()


def test_heals_a_stale_users_table_missing_newer_columns(tmp_path):
    db_path = str(tmp_path / "stale.db")
    _make_stale_db(db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    _heal_sqlite_schema_drift(engine)
    Base.metadata.create_all(bind=engine)  # what session.py does right after healing

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("users")}
    assert "firebase_uid" in columns
    assert "name" in columns


def test_a_fresh_db_with_no_tables_is_left_alone_by_the_healer(tmp_path):
    """The healer should only ever act on tables that already exist with
    a mismatched shape -- a brand-new file with no tables at all isn't
    "drifted", it's just new, and create_all() (called right after)
    handles that case correctly on its own."""
    db_path = str(tmp_path / "fresh.db")
    engine = create_engine(f"sqlite:///{db_path}")

    _heal_sqlite_schema_drift(engine)  # should be a no-op, nothing to heal
    assert not os.path.exists(db_path) or os.path.getsize(db_path) == 0


def test_an_up_to_date_schema_is_not_touched(tmp_path):
    """The healer must not recreate a database that's already correct --
    only genuinely mismatched schemas should trigger it."""
    db_path = str(tmp_path / "current.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)  # a fully up-to-date schema
    mtime_before = os.path.getmtime(db_path)

    _heal_sqlite_schema_drift(engine)

    assert os.path.exists(db_path)
    assert os.path.getmtime(db_path) == mtime_before  # untouched, not recreated


def test_end_to_end_authenticated_request_survives_a_stale_db(tmp_path, monkeypatch):
    """The actual regression: a real API call (not just the healer in
    isolation) against a stale dev.db must succeed, not 500."""
    from unittest.mock import patch
    import importlib

    db_path = str(tmp_path / "stale_e2e.db")
    _make_stale_db(db_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.db.session as session_module
    importlib.reload(session_module)  # re-run the module-level healing logic with the new env var

    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.api.routes import auth as auth_routes

    test_app = FastAPI()
    test_app.include_router(auth_routes.router)
    test_app.dependency_overrides[session_module.get_db] = lambda: session_module.SessionLocal()

    client = TestClient(test_app)
    with patch("app.core.auth.dependencies.verify_firebase_token", return_value={"uid": "u1", "email": "j@example.com", "name": "J"}):
        resp = client.get("/auth/me", headers={"Authorization": "Bearer fake"})

    assert resp.status_code == 200
    assert resp.json()["tier"] == "free"
