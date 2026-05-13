"""Sync schema drift: users columns + reset_codes table (ADR-019 compliance)

Revision ID: 016
Revises: 015
Create Date: 2026-05-13

Context (Schema Drift Audit 2026-05-13):
These 4 objects existed only in emergency_migrations (app/main.py) but had
no corresponding Alembic migration — violating ADR-019 which requires
"every emergency_migrations change also exists in Alembic".

Objects covered:
1. users.responses_this_month  — INTEGER DEFAULT 0 (rate limiting: responses per month)
2. users.responses_month_reset — TIMESTAMP TZ nullable (reset timestamp for counter above)
3. users.is_verified           — BOOLEAN DEFAULT FALSE (company verification flag)
4. reset_codes                 — table for password reset flow

Idempotency: on prod these already exist via emergency_migrations.
We use inspector checks (IF NOT EXISTS pattern) so migration is safe to run
on an already-migrated database.

Exact types copied from emergency_migrations in app/main.py — not invented.
"""
from alembic import op
import sqlalchemy as sa


revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    user_columns = [c['name'] for c in inspector.get_columns('users')]

    # 1. users.responses_this_month (INTEGER DEFAULT 0)
    # From emergency: "ALTER TABLE users ADD COLUMN IF NOT EXISTS responses_this_month INTEGER DEFAULT 0"
    if 'responses_this_month' not in user_columns:
        op.add_column(
            'users',
            sa.Column(
                'responses_this_month',
                sa.Integer(),
                nullable=False,
                server_default='0',
            )
        )

    # 2. users.responses_month_reset (TIMESTAMP WITH TIME ZONE, nullable)
    # From emergency: "ALTER TABLE users ADD COLUMN IF NOT EXISTS responses_month_reset TIMESTAMP WITH TIME ZONE"
    if 'responses_month_reset' not in user_columns:
        op.add_column(
            'users',
            sa.Column(
                'responses_month_reset',
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )

    # 3. users.is_verified (BOOLEAN NOT NULL DEFAULT FALSE)
    # From emergency: "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE"
    if 'is_verified' not in user_columns:
        op.add_column(
            'users',
            sa.Column(
                'is_verified',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    # 4. reset_codes table
    # From emergency:
    #   id SERIAL PRIMARY KEY,
    #   email VARCHAR NOT NULL,
    #   code VARCHAR NOT NULL,
    #   expires_at TIMESTAMP NOT NULL,
    #   created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    if not inspector.has_table('reset_codes'):
        op.create_table(
            'reset_codes',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('email', sa.String(), nullable=False),
            sa.Column('code', sa.String(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column(
                'created_at',
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
        )


def downgrade() -> None:
    """
    WARNING: This downgrade DROPS user counter columns
    and reset_codes table. Data will be lost.
    Use only on dev/test environments, never on prod
    with real user data.
    """
    op.drop_table('reset_codes')
    op.drop_column('users', 'is_verified')
    op.drop_column('users', 'responses_month_reset')
    op.drop_column('users', 'responses_this_month')
