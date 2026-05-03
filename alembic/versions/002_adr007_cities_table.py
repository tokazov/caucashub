"""ADR-007: Таблица cities + FK поля в loads.

Revision ID: 002_adr007
Revises: 001_adr006
Create Date: 2026-05-03

Изменения:
- Новая таблица cities (id, name_ru, name_ge, country_iso, lat, lon, is_popular, yandex_geo_id)
- loads: добавить from_city_id, to_city_id (nullable FK на cities, существующие строки сохраняются)
"""
from alembic import op
import sqlalchemy as sa

revision = '002_adr007'
down_revision = '001_adr006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cities table ──────────────────────────────────────────────────────────
    op.create_table(
        'cities',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name_ru', sa.String(100), nullable=False, index=True),
        sa.Column('name_ge', sa.String(100), nullable=True),
        sa.Column('country_iso', sa.String(2), nullable=False, index=True),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lon', sa.Float(), nullable=True),
        sa.Column('is_popular', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('yandex_geo_id', sa.String(50), nullable=True,
                  comment='Yandex GeoObject ID — сохраняем согласно условиям Advanced-лицензии'),
    )

    # ── loads: nullable FK поля (не ломаем существующие данные) ───────────────
    with op.batch_alter_table('loads') as batch_op:
        batch_op.add_column(sa.Column(
            'from_city_id', sa.Integer(), nullable=True,
            comment='FK на cities.id — нормализованный город отправления'
        ))
        batch_op.add_column(sa.Column(
            'to_city_id', sa.Integer(), nullable=True,
            comment='FK на cities.id — нормализованный город назначения'
        ))


def downgrade() -> None:
    with op.batch_alter_table('loads') as batch_op:
        batch_op.drop_column('to_city_id')
        batch_op.drop_column('from_city_id')

    op.drop_table('cities')
