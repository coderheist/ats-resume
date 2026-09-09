"""
Engine construction: URL normalization and connection-pool options.

Both of these are startup-time production concerns that no other test
covers, and both fail in ways that are hard to attribute from the
outside -- one kills the process before it binds a port, the other
surfaces as an intermittent database error long after deploy.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from app.db.session import SQLITE_FALLBACK_URL, engine_kwargs_for, normalize_database_url


class TestNormalizeDatabaseUrl:
    """`postgres://` is what Heroku, Render and Railway inject; SQLAlchemy
    2.x removed that dialect alias, so create_engine() raises
    NoSuchModuleError at import and the container never starts."""

    def test_postgres_scheme_is_rewritten(self):
        assert normalize_database_url("postgres://u:p@host:5432/db") == "postgresql://u:p@host:5432/db"

    def test_rewrite_preserves_query_parameters(self):
        # ?sslmode=require is mandatory on Supabase -- losing it here would
        # trade a startup crash for a connection refused.
        assert normalize_database_url("postgres://u:p@host:5432/db?sslmode=require") == (
            "postgresql://u:p@host:5432/db?sslmode=require"
        )

    def test_correct_scheme_is_left_alone(self):
        url = "postgresql://u:p@host:5432/db?sslmode=require"
        assert normalize_database_url(url) == url

    def test_surrounding_whitespace_is_stripped(self):
        # A secret manager or a copy-paste into a dashboard field commonly
        # carries a trailing newline.
        assert normalize_database_url("  postgres://u:p@host/db\n") == "postgresql://u:p@host/db"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_unset_falls_back_to_sqlite(self, raw):
        assert normalize_database_url(raw) == SQLITE_FALLBACK_URL

    def test_normalized_url_actually_builds_an_engine(self):
        """The point of the rewrite: this exact call raised
        `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres`
        before it. create_engine() does not connect, so no server is needed."""
        engine = create_engine(normalize_database_url("postgres://u:p@host:5432/db"))
        assert engine.dialect.name == "postgresql"


class TestEngineKwargs:
    def test_postgres_gets_pre_ping_and_recycle(self):
        kwargs = engine_kwargs_for("postgresql://u:p@host:5432/db")
        assert kwargs["pool_pre_ping"] is True
        assert kwargs["pool_recycle"] > 0

    def test_recycle_is_configurable(self, monkeypatch):
        monkeypatch.setenv("DB_POOL_RECYCLE_SECONDS", "240")
        assert engine_kwargs_for("postgresql://u:p@host/db")["pool_recycle"] == 240

    def test_sqlite_keeps_check_same_thread_and_no_pooling_flags(self):
        kwargs = engine_kwargs_for(SQLITE_FALLBACK_URL)
        assert kwargs == {"connect_args": {"check_same_thread": False}}

    def test_pre_ping_reaches_the_built_engine(self):
        """Asserted on the engine, not just the dict, so a future change to
        how these are passed can't quietly drop them."""
        engine = create_engine("postgresql://u:p@host:5432/db", **engine_kwargs_for("postgresql://u:p@host/db"))
        assert engine.pool._pre_ping is True
