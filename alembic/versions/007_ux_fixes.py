"""UX fixes: completed_deals_count, ratings_received_count, act_number padding.

Revision ID: 007_ux_fixes
Revises: 006_password_changed_at
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = '007_ux_fixes'
down_revision = '006_password_changed_at'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 3.1: Добавляем новые счётчики
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column(
            'completed_deals_count', sa.Integer(), nullable=False, server_default='0',
            comment='Количество завершённых сделок (3.1)'
        ))
        batch_op.add_column(sa.Column(
            'ratings_received_count', sa.Integer(), nullable=False, server_default='0',
            comment='Количество полученных оценок (3.1)'
        ))
    # Backfill: копируем существующий trips_count → completed_deals_count
    op.execute("UPDATE users SET completed_deals_count = trips_count")


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('completed_deals_count')
        batch_op.drop_column('ratings_received_count')
