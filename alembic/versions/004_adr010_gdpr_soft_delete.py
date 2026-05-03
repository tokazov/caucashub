"""ADR-010: GDPR soft delete — is_deleted, deleted_at для users.

Revision ID: 004_adr010
Revises: 003_track8
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa

revision = '004_adr010'
down_revision = '003_track8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column(
            'is_deleted', sa.Boolean(), nullable=False, server_default='0',
            comment='Soft delete flag (ADR-010 GDPR)'
        ))
        batch_op.add_column(sa.Column(
            'deleted_at', sa.DateTime(timezone=True), nullable=True,
            comment='Timestamp of account deletion'
        ))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('deleted_at')
        batch_op.drop_column('is_deleted')
