"""Фикс 3 (OQ-008): password_changed_at для инвалидации JWT при смене пароля.

Revision ID: 006_password_changed_at
Revises: 005_track11
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = '006_password_changed_at'
down_revision = '005_track11'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column(
            'password_changed_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Время последней смены пароля. JWT выпущенные ДО этого момента невалидны.'
        ))
    # Backfill: существующим пользователям ставим created_at (все старые токены остаются валидными)
    op.execute("UPDATE users SET password_changed_at = created_at WHERE password_changed_at IS NULL")


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('password_changed_at')
