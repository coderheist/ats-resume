import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Make `app.*` importable when alembic is invoked from the project root
# (mirrors PYTHONPATH=. used for pytest/uvicorn elsewhere in this repo).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.models import Base  # noqa: E402
from app.db.session import DATABASE_URL  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Read the DB URL the same way the app does (DATABASE_URL env var, SQLite
# dev fallback) rather than hard-coding it in alembic.ini. This is what
# lets `alembic upgrade head` target either the local dev SQLite file or
# the real Postgres+pgvector instance without editing config.
#
# The doubled "%" is not cosmetic. Alembic's Config is a configparser
# underneath, and configparser applies "%"-interpolation to every value
# it stores -- so a URL whose password contains a percent sign never
# reaches the driver. It fails before any connection attempt with
#
#   ValueError: invalid interpolation syntax in '<the whole URL>'
#
# and the message quotes the URL, which reads like the URL is malformed
# rather than the config layer chewing it. This is not an edge case:
# percent signs get into a password precisely because URL-encoding puts
# them there, and a password containing "@" MUST be encoded as "%40" or
# it terminates the userinfo section early and the host parses wrong.
# So the common, correct way to write a password lands here.
#
# Escaping at the boundary keeps the value intact through configparser;
# what engine_from_config() reads back below is the original string.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def include_object(object, name, type_, reflected, compare_to):
    """Keep autogenerate's hands off the pgvector column.

    `resumes.embedding` is a `vector(384)` created by migration
    e2c91358026a and mirrored in infra/schema.sql. It is declared there
    rather than in models.py on purpose, so this codebase carries no hard
    dependency on the pgvector Python package -- see the comment on that
    column in app/db/models.py.

    The cost of that choice shows up here: autogenerate diffs the live
    database against the model metadata, finds a column the metadata has
    never heard of, and concludes somebody deleted it. Left alone it emits

        op.drop_column('resumes', 'embedding')

    into every new revision -- which, applied, silently destroys every
    stored embedding. It is easy to miss precisely because the rest of the
    generated migration is correct and wanted. (The same blind spot is why
    reflecting this table logs "SAWarning: Did not recognize type
    'vector'".)

    Excluding it here means autogenerate neither adds nor drops it, and the
    column stays owned by the migration that created it.
    """
    return not (type_ == "column" and name == "embedding" and getattr(object.table, "name", None) == "resumes")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
