"""pgvector embedding column on resumes

Folds infra/schema.sql's manual step into the migration chain, as the
README says production should do ("run infra/schema.sql after the
SQLAlchemy tables are created ... or migrate both via Alembic"). schema.sql
is left in place as documentation of what this does, but this migration is
now the thing that actually runs it.

384 dims matches all-MiniLM-L6-v2, the default SBERT model referenced in
app/core/scoring/embeddings.py's production path. If EMBEDDING_BACKEND is
switched to a model with a different output size, this column's dimension
needs a follow-up migration to match.

Guarded to a no-op on non-Postgres backends (e.g. the SQLite dev fallback
in app/db/session.py) since neither the `vector` extension nor the
`vector(384)` type exist there. `alembic upgrade head` against SQLite will
skip this migration with a warning rather than fail outright; the real
target (Postgres+pgvector, per docker-compose.yml) applies it fully.

Revision ID: e2c91358026a
Revises: bf91f6a3a4e3
Create Date: 2026-08-10 11:52:45.240826

"""
import warnings
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e2c91358026a'
down_revision: Union[str, Sequence[str], None] = 'bf91f6a3a4e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        warnings.warn(
            f"Skipping pgvector migration on '{bind.dialect.name}' backend "
            "(requires Postgres + the pgvector extension). This is expected "
            "for the local SQLite dev fallback; production runs on Postgres."
        )
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE resumes ADD COLUMN IF NOT EXISTS embedding vector(384)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE resumes DROP COLUMN IF EXISTS embedding")
    # Extension is left in place on downgrade -- other tables/features may
    # depend on it, and DROP EXTENSION would fail loudly if so anyway.
