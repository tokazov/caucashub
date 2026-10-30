"""Optional owner-attested Georgian names for private documents. No backfill.

Revision ID: 028; Revises: 027.
"""
from alembic import op
import sqlalchemy as sa

revision = '028'
down_revision = '027'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('users'):
        return
    columns = {item['name'] for item in inspector.get_columns('users')}
    if 'legal_name_ka' not in columns:
        op.add_column('users', sa.Column('legal_name_ka', sa.String(255), nullable=True))
    if 'legal_name_ka_confirmed_at' not in columns:
        op.add_column('users', sa.Column('legal_name_ka_confirmed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Rollback preserves owner-entered private data; older applications ignore it.
    pass
