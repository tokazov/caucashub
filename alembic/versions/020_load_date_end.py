"""Persist the optional end of a loading period.

Revision ID: 020
Revises: 019
"""
from alembic import op
import sqlalchemy as sa

revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade():
    # Railway's fallback may have added this column before Alembic (ADR-019).
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE loads ADD COLUMN IF NOT EXISTS load_date_end TIMESTAMP WITH TIME ZONE')
    elif 'load_date_end' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('loads')}:
        op.add_column('loads', sa.Column('load_date_end', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('loads', 'load_date_end')
