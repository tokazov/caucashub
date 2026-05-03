"""Audit log переходов состояний (Трек 8)."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.database import Base


class StatusChange(Base):
    __tablename__ = "status_changes"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(20), nullable=False, index=True)   # load / response / deal
    entity_id   = Column(Integer, nullable=False, index=True)
    from_status = Column(String(30), nullable=True)   # None при создании
    to_status   = Column(String(30), nullable=False)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=True)  # null = система
    changed_at  = Column(DateTime(timezone=True), server_default=func.now())
    reason      = Column(Text, nullable=True)
