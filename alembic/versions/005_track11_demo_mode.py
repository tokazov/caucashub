"""Track 11: Demo mode — is_demo для loads и users.

Revision ID: 005_track11
Revises: 004_adr010
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = '005_track11'
down_revision = '004_adr010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # loads.is_demo
    with op.batch_alter_table('loads') as batch_op:
        batch_op.add_column(sa.Column(
            'is_demo', sa.Boolean(), nullable=False, server_default='0',
            comment='Demo load — not counted in stats, blocks real responses'
        ))

    # users.is_demo
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column(
            'is_demo', sa.Boolean(), nullable=False, server_default='0',
            comment='Demo user — owner of demo loads'
        ))

    # Backfill: помечаем грузы с price_gel = 0 как демо
    op.execute(
        "UPDATE loads SET is_demo = 1 WHERE (price_gel = 0 OR price_gel IS NULL) AND price_usd IS NULL"
    )
    # Помечаем владельцев этих грузов как демо-юзеров
    op.execute(
        """UPDATE users SET is_demo = 1 WHERE id IN (
            SELECT DISTINCT user_id FROM loads WHERE is_demo = 1
        )"""
    )


def downgrade() -> None:
    with op.batch_alter_table('loads') as batch_op:
        batch_op.drop_column('is_demo')
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('is_demo')
