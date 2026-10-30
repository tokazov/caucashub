"""Private immutable first-issued act bundles. No historical backfill.

Revision ID: 029; Revises: 028.
"""
from alembic import op
import sqlalchemy as sa

revision = '029'
down_revision = '028'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if sa.inspect(connection).has_table('deal_act_archives'):
        return
    op.create_table(
        'deal_act_archives',
        sa.Column('deal_id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.Column('ru_pdf', sa.LargeBinary(), nullable=False),
        sa.Column('ge_pdf', sa.LargeBinary(), nullable=False),
        sa.Column('ru_sha256', sa.String(64), nullable=False),
        sa.Column('ge_sha256', sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint('deal_id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id']),
        sa.CheckConstraint('schema_version = 1', name='ck_deal_act_archive_version'),
        sa.CheckConstraint('length(ru_pdf) > 0', name='ck_deal_act_archive_ru_pdf'),
        sa.CheckConstraint('length(ge_pdf) > 0', name='ck_deal_act_archive_ge_pdf'),
        sa.CheckConstraint('length(ru_sha256) = 64', name='ck_deal_act_archive_ru_sha'),
        sa.CheckConstraint('length(ge_sha256) = 64', name='ck_deal_act_archive_ge_sha'),
        sa.CheckConstraint('length(payload_sha256) = 64', name='ck_deal_act_archive_payload_sha'),
    )


def downgrade():
    # A code rollback must preserve issued accounting documents and their bytes.
    pass
