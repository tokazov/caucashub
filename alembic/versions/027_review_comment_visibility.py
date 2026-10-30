"""Keep all existing review comments private until their author opts in.

Revision ID: 027; Revises: 026.
"""
from alembic import op
import sqlalchemy as sa

revision = '027'
down_revision = '026'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('deal_reviews'):
        return  # 022/fresh bootstrap creates the table before this release gate.
    if 'public_comment' not in {row['name'] for row in inspector.get_columns('deal_reviews')}:
        op.add_column('deal_reviews', sa.Column('public_comment', sa.Boolean(),
                                              nullable=False, server_default=sa.false()))


def downgrade():
    # Retain the consent flag on rollback. Older applications ignore the column.
    pass
