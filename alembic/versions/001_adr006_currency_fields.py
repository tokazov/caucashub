"""ADR-006: Добавляем поля двойной валюты и курс NBG.

Revision ID: 001_adr006
Revises:
Create Date: 2026-05-03

Изменения:
- loads: добавить exchange_rate_at_creation
- responses: добавить price_gel, exchange_rate_at_creation
- deals: добавить exchange_rate_snapshot, final_price_gel, final_price_usd
"""
from alembic import op
import sqlalchemy as sa

revision = '001_adr006'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── loads ─────────────────────────────────────────────────────────────────
    with op.batch_alter_table('loads') as batch_op:
        batch_op.add_column(sa.Column(
            'exchange_rate_at_creation', sa.Float(), nullable=True,
            comment='Курс GEL/USD из NBG на момент создания груза'
        ))

    # ── responses ─────────────────────────────────────────────────────────────
    with op.batch_alter_table('responses') as batch_op:
        batch_op.add_column(sa.Column(
            'price_gel', sa.Float(), nullable=True,
            comment='Цена предложения в лари'
        ))
        batch_op.add_column(sa.Column(
            'exchange_rate_at_creation', sa.Float(), nullable=True,
            comment='Курс GEL/USD из NBG на момент подачи отклика'
        ))

    # ── deals ─────────────────────────────────────────────────────────────────
    with op.batch_alter_table('deals') as batch_op:
        batch_op.add_column(sa.Column(
            'exchange_rate_snapshot', sa.Float(), nullable=True,
            comment='Курс GEL/USD зафиксированный на момент создания сделки'
        ))
        batch_op.add_column(sa.Column(
            'final_price_gel', sa.Float(), nullable=True,
            comment='Итоговая цена в лари (снапшот)'
        ))
        batch_op.add_column(sa.Column(
            'final_price_usd', sa.Float(), nullable=True,
            comment='Итоговая цена в USD (снапшот)'
        ))


def downgrade() -> None:
    with op.batch_alter_table('deals') as batch_op:
        batch_op.drop_column('final_price_usd')
        batch_op.drop_column('final_price_gel')
        batch_op.drop_column('exchange_rate_snapshot')

    with op.batch_alter_table('responses') as batch_op:
        batch_op.drop_column('exchange_rate_at_creation')
        batch_op.drop_column('price_gel')

    with op.batch_alter_table('loads') as batch_op:
        batch_op.drop_column('exchange_rate_at_creation')
