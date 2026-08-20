"""
Engine/session wiring for the SQLAlchemy models in `app/db/models.py`.

This didn't exist before: `models.py` defined the ORM classes but nothing
in the app ever read `DATABASE_URL` or created an engine from them, even
though docker-compose.yml already sets that env var. Alembic needs a real
URL to introspect and migrate against, so this fills that gap.

Defaults to a local SQLite file when DATABASE_URL isn't set, purely so
`alembic upgrade head` and any future DB-touching tests have something to
run against without requiring Postgres. Production always sets
DATABASE_URL (see docker-compose.yml / infra deployment config) and points
it at Postgres+pgvector.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dev.db")

# check_same_thread only matters for the SQLite dev fallback.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency: yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
