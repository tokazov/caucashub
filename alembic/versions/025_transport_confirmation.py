"""Record explicit transport availability confirmations without legacy backfill.

Revision ID: 025
Revises: 024
"""
from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("transport_offers"):
        # Historical partial-schema release checks have no transport catalogue.
        # The existing application bootstrap creates a fresh table with this
        # nullable field; migration 009 creates it on the regular Alembic path.
        return
    columns = {item["name"] for item in inspector.get_columns("transport_offers")}
    if "last_confirmed_at" not in columns:
        op.add_column("transport_offers", sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    # created_at and updated_at are not owner availability confirmations.


def downgrade():
    # Preserve confirmation history when rolling application code back.
    pass
