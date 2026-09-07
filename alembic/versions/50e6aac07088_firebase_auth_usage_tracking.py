"""firebase auth, usage tracking

Revision ID: 50e6aac07088
Revises: e2c91358026a
Create Date: 2026-09-05 05:56:30.203780

Autogenerate also reported six `alter_column ... NUMERIC() -> UUID()`
changes across resumes/scan_results/subscriptions/users -- stripped out
here. Those are a reflection artifact of diffing against the SQLite dev
fallback (SQLite has no native UUID type, so it reflects these columns
back as generic NUMERIC regardless of what the Python model declares);
the original migration already created these correctly on the real
target database (Postgres), so there's no genuine drift to fix there.
Running six no-op ALTER COLUMN statements against production for a
change that isn't real isn't worth the risk of a mistake in a migration
nobody asked for.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '50e6aac07088'
down_revision: Union[str, Sequence[str], None] = 'e2c91358026a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'usage_logs',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('user_id', sa.UUID(as_uuid=False), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_usage_logs_created_at'), 'usage_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_usage_logs_user_id'), 'usage_logs', ['user_id'], unique=False)

    op.add_column('users', sa.Column('firebase_uid', sa.String(), nullable=True))
    op.add_column('users', sa.Column('name', sa.String(), nullable=True))
    op.create_index(op.f('ix_users_firebase_uid'), 'users', ['firebase_uid'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_firebase_uid'), table_name='users')
    op.drop_column('users', 'name')
    op.drop_column('users', 'firebase_uid')

    op.drop_index(op.f('ix_usage_logs_user_id'), table_name='usage_logs')
    op.drop_index(op.f('ix_usage_logs_created_at'), table_name='usage_logs')
    op.drop_table('usage_logs')
