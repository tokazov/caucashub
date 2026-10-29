"""Persist exact typed route endpoints without changing historical rows.
Revision ID: 026; Revises: 025.
"""
from alembic import op
import sqlalchemy as sa
revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None

def upgrade():
    for table in ('loads', 'transport_offers'):
        inspector = sa.inspect(op.get_bind())
        if not inspector.has_table(table):
            continue
        columns = {column['name'] for column in inspector.get_columns(table)}
        for name in ('from_location', 'to_location'):
            if name not in columns:
                op.add_column(table, sa.Column(name, sa.JSON(none_as_null=True), nullable=True))

def downgrade():
    # Keep user-selected coordinates on rollback; older apps ignore the columns.
    pass
