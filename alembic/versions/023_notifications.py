"""Persistent inbox and per-channel committed delivery queue.

Revision ID: 023
Revises: 022
"""
from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("notifications"):
        op.create_table("notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("recipient_id", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("event_key", sa.String(160), nullable=False),
            sa.Column("kind", sa.String(48), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["recipient_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
            sa.UniqueConstraint("event_key", "recipient_id", name="uq_notifications_event_recipient"))
        op.create_index("ix_notifications_recipient_created", "notifications", ["recipient_id", "created_at"])
        op.create_index("ix_notifications_recipient_read", "notifications", ["recipient_id", "read_at"])
    if not inspector.has_table("notification_deliveries"):
        op.create_table("notification_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("notification_id", sa.Integer(), nullable=False),
            sa.Column("channel", sa.String(16), nullable=False),
            sa.Column("status", sa.String(16), server_default="pending", nullable=False),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("idempotency_key", sa.String(36), nullable=False),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("claim_token", sa.String(36), nullable=True),
            sa.Column("provider_id", sa.String(250), nullable=True),
            sa.Column("last_error", sa.String(96), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("notification_id", "channel", name="uq_notification_deliveries_channel"),
            sa.UniqueConstraint("idempotency_key", name="uq_notification_deliveries_idempotency"),
            sa.CheckConstraint("channel IN ('email', 'telegram')", name="ck_notification_deliveries_channel"),
            sa.CheckConstraint("status IN ('pending', 'sending', 'sent', 'failed', 'unknown', 'skipped')",
                               name="ck_notification_deliveries_status"),
            sa.CheckConstraint("attempts >= 0", name="ck_notification_deliveries_attempts"))
        op.create_index("ix_notification_deliveries_due", "notification_deliveries", ["status", "next_attempt_at"])

def downgrade():
    # Disposable development databases only; preserve production event history.
    op.drop_table("notification_deliveries")
    op.drop_table("notifications")
