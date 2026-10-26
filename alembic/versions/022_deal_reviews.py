"""Persist attributable per-participant reviews without fabricating old ratings.

Revision ID: 022
Revises: 021
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("deal_reviews"):
        return
    op.create_table(
        "deal_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("rater_id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rater_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"]),
        sa.UniqueConstraint("deal_id", "rater_id", name="uq_deal_reviews_deal_rater"),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_deal_reviews_score_range"),
        sa.CheckConstraint("rater_id <> recipient_id", name="ck_deal_reviews_distinct_people"),
    )
    op.create_index("ix_deal_reviews_deal_id", "deal_reviews", ["deal_id"])
    op.create_index("ix_deal_reviews_recipient_id", "deal_reviews", ["recipient_id"])


def downgrade():
    # Disposable development/test databases only. Production rollback retains reviews.
    op.drop_index("ix_deal_reviews_recipient_id", table_name="deal_reviews")
    op.drop_index("ix_deal_reviews_deal_id", table_name="deal_reviews")
    op.drop_table("deal_reviews")
