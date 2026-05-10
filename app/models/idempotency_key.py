"""Model: idempotency_keys — Postgres-backed idempotency store.

response_body хранится как JSONB на Postgres и JSON на SQLite (для тестов).
"""
import os
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, Index, JSON
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base

# На Postgres используем JSONB (индексируемый), на SQLite — JSON (для тестов)
_is_postgres = os.getenv("DATABASE_URL", "sqlite").startswith("postgresql")
_JsonType = JSONB if _is_postgres else JSON


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id              = Column(Integer, primary_key=True)
    key             = Column(String(255), nullable=False)
    user_id         = Column(Integer, nullable=False)          # no FK — faster deletes
    scope           = Column(String(64), nullable=False)
    request_hash    = Column(String(64), nullable=False)       # sha256 of request body
    response_status = Column(Integer, nullable=False)
    response_body   = Column(_JsonType, nullable=False)
    created_at      = Column(DateTime(timezone=True), server_default="NOW()")
    expires_at      = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("scope", "user_id", "key", name="uq_idempotency_scope_user_key"),
        Index("idx_idempotency_expires", "expires_at"),
    )
