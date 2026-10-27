"""Persist password-recovery verification and email-request budgets.

Revision ID: 024
Revises: 023
"""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    user_columns = {item["name"] for item in inspector.get_columns("users")}
    if "password_version" not in user_columns:
        op.add_column("users", sa.Column("password_version", sa.Integer(), nullable=False, server_default="0"))
    if not inspector.has_table("reset_codes"):
        op.create_table(
            "reset_codes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("code", sa.String(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_reset_codes_email", "reset_codes", ["email"])
        return
    columns = {item["name"] for item in inspector.get_columns("reset_codes")}
    for name in ("attempts", "request_count"):
        if name not in columns:
            op.add_column("reset_codes", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    # Recovery state is short lived, but production rollback preserves the
    # additive columns and previously issued codes rather than rewriting them.
    pass
