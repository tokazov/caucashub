"""Committed inbox events and independently tracked external deliveries."""
from uuid import uuid4
from sqlalchemy import (Column, Integer, String, DateTime, ForeignKey, JSON,
                        UniqueConstraint, CheckConstraint, Index)
from sqlalchemy.sql import func
from app.database import Base

class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("event_key", "recipient_id", name="uq_notifications_event_recipient"),
        Index("ix_notifications_recipient_created", "recipient_id", "created_at"),
        Index("ix_notifications_recipient_read", "recipient_id", "read_at"),
    )
    id = Column(Integer, primary_key=True)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    event_key = Column(String(160), nullable=False)
    kind = Column(String(48), nullable=False)
    data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)

class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("notification_id", "channel", name="uq_notification_deliveries_channel"),
        UniqueConstraint("idempotency_key", name="uq_notification_deliveries_idempotency"),
        CheckConstraint("channel IN ('email', 'telegram')", name="ck_notification_deliveries_channel"),
        CheckConstraint("status IN ('pending', 'sending', 'sent', 'failed', 'unknown', 'skipped')",
                        name="ck_notification_deliveries_status"),
        CheckConstraint("attempts >= 0", name="ck_notification_deliveries_attempts"),
        Index("ix_notification_deliveries_due", "status", "next_attempt_at"),
    )
    id = Column(Integer, primary_key=True)
    notification_id = Column(Integer, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    idempotency_key = Column(String(36), nullable=False, default=lambda: str(uuid4()))
    next_attempt_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    claim_token = Column(String(36), nullable=True)
    provider_id = Column(String(250), nullable=True)
    last_error = Column(String(96), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
