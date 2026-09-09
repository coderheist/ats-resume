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
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.db.models import Base

SQLITE_FALLBACK_URL = "sqlite:///./dev.db"


def normalize_database_url(raw: str | None) -> str:
    """DATABASE_URL as given -> a URL SQLAlchemy 2.x will actually accept.

    Rewrites the `postgres://` scheme to `postgresql://`. This is not
    cosmetic: SQLAlchemy 2.x removed the `postgres` dialect alias, so a
    `postgres://` URL raises

        NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres

    from create_engine() at import time -- which means the process dies
    during startup, before uvicorn binds a port, and the platform reports
    only a generic "container failed to start" with no hint at the cause.

    It matters because several managed platforms still hand out exactly
    that scheme in the connection string they inject: Heroku, Render and
    Railway all do. Nobody types this URL by hand, so "just write it
    correctly" isn't available as a fix -- the value arrives from the
    platform already wrong for this library. Supabase (what this repo is
    set up for, see docs/DEPLOYMENT.md) gives `postgresql://` and is
    unaffected, which is precisely why this can go unnoticed until the
    day someone deploys somewhere else.

    Everything else is passed through untouched, including query
    parameters like `?sslmode=require`.
    """
    if not raw or not raw.strip():
        return SQLITE_FALLBACK_URL
    url = raw.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def engine_kwargs_for(url: str) -> dict[str, Any]:
    """create_engine() options appropriate to the database behind `url`.

    A function rather than inline setup so the choice can be asserted
    directly, without reimporting this module to rebuild the engine.
    """
    if url.startswith("sqlite"):
        # check_same_thread only matters for the SQLite dev fallback.
        return {"connect_args": {"check_same_thread": False}}
    # Pooled connections outlive the network path they were opened over.
    # A managed Postgres (Supabase, RDS, a pgbouncer in front of either)
    # closes connections that have been idle for a few minutes, and a
    # load balancer or NAT gateway silently drops the flow even sooner --
    # none of which the pool is told about. The next request checks out a
    # socket that looks fine and only discovers otherwise mid-query:
    #
    #   OperationalError: server closed the connection unexpectedly
    #   OperationalError: SSL connection has been closed unexpectedly
    #
    # The failure shape is what makes this expensive to diagnose from the
    # outside: it is intermittent, it clusters after quiet periods
    # (overnight, or the first request after a lull), and it disappears on
    # retry, so it reads like a flaky database rather than a pool that is
    # handing out dead sockets.
    #
    # pool_pre_ping issues a cheap liveness check on checkout and
    # transparently replaces a connection that has gone away. pool_recycle
    # additionally retires connections before they get old enough to be
    # reaped -- 30 minutes is comfortably under the common idle timeouts.
    # Deliberately applied only to non-SQLite: a local file database has
    # no connection to lose, so this would be pure overhead there.
    return {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE_SECONDS", "1800")),
    }


DATABASE_URL = normalize_database_url(os.environ.get("DATABASE_URL"))
_using_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(DATABASE_URL, **engine_kwargs_for(DATABASE_URL))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _heal_sqlite_schema_drift(engine) -> None:
    """
    Real, reproduced bug this fixes: `Base.metadata.create_all()` only
    creates tables that don't exist yet -- it never adds a column to a
    table that already exists. Across many iterations of this project,
    `models.py` gained new columns on existing tables (User.firebase_uid,
    most recently) and new tables (Payment, UsageLog). A `dev.db` left
    over from before those columns existed still has the *old* `users`
    table shape, and `create_all()` sees "users already exists" and skips
    it entirely -- the column is just never added. The next request that
    queries `User.firebase_uid` (any signed-in call to /auth/me,
    /score/standalone, or /score/full-report) then crashes with an
    uncaught `OperationalError: no such column: users.firebase_uid` --
    confirmed by deliberately reproducing it against a hand-built stale
    schema, not assumed.

    Since this file is explicitly a throwaway local convenience database
    (production always uses real Alembic migrations against Postgres,
    see the module docstring above), the safe fix is detecting the drift
    and recreating it fresh -- not silently leaving a 500 for the next
    request to hit, and not attempting in-place ALTER TABLE migrations
    for a file nothing depends on keeping.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue  # a genuinely new table -- create_all() below handles this correctly
        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        expected_columns = {col.name for col in table.columns}
        if not expected_columns.issubset(existing_columns):
            missing = expected_columns - existing_columns
            # The engine's OWN resolved path, not the module-level
            # DATABASE_URL global -- this function must act on whatever
            # engine it's actually given (tests pass in a different one
            # deliberately), not assume it's always the module default.
            db_path = str(engine.url.database)
            print(
                f"[db] {db_path} schema is out of date (table '{table_name}' is missing "
                f"column(s) {sorted(missing)}) -- this is a local convenience database, "
                f"not a persistent one, so it's being recreated fresh. If you need to keep "
                f"data across schema changes, point DATABASE_URL at real Postgres and use "
                f"`alembic upgrade head` instead."
            )
            engine.dispose()
            if db_path and db_path != ":memory:" and os.path.exists(db_path):
                os.remove(db_path)
            return  # recreated from scratch below by create_all()


if _using_sqlite:
    # Auto-create tables and heal schema drift for ANY SQLite database --
    # not just the narrower "DATABASE_URL was left unset" case. The real
    # distinction that matters is SQLite (dev/test convenience, no
    # migration tooling expected -- see _heal_sqlite_schema_drift's
    # docstring for the bug this specifically fixes) versus Postgres
    # (production, where Alembic migrations are the only source of
    # truth and must never be silently touched here, dev-fallback or not).
    _heal_sqlite_schema_drift(engine)
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
