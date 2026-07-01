"""Add promoted_until to loads

Revision ID: 017
Revises: 016
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('loads', sa.Column(
        'promoted_until',
        sa.DateTime(timezone=True),
        nullable=True
    ))


def downgrade():
    op.drop_column('loads', 'promoted_until')
