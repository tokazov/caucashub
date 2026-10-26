"""Optional carrier profile defaults (tonnage is in tonnes).

Revision ID: 021
Revises: 020
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS truck_type VARCHAR(32)")
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tonnage DOUBLE PRECISION")
    else:
        columns = {column["name"] for column in sa.inspect(connection).get_columns("users")}
        if "truck_type" not in columns:
            op.add_column("users", sa.Column("truck_type", sa.String(32), nullable=True))
        if "tonnage" not in columns:
            op.add_column("users", sa.Column("tonnage", sa.Float(), nullable=True))


def downgrade():
    # Dev/test only. Production rollback keeps these additive columns and data.
    op.drop_column("users", "tonnage")
    op.drop_column("users", "truck_type")
