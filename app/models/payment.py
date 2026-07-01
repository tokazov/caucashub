"""
Payment model — хранит платёжные записи (планы и продвижение грузов).
"""
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    type            = Column(String, nullable=False)
    # "plan_pro" | "plan_business" | "promote_24h" | "promote_72h" | "promote_168h"
    payload         = Column(JSON, nullable=False, default=dict)
    # для promote: {"load_id": 70, "hours": 24}; для plan: {}
    amount_gel      = Column(Numeric(10, 2), nullable=False)
    status          = Column(String, default="pending", nullable=False)
    # pending | paid | failed | cancelled
    provider        = Column(String, default="manual", nullable=False)
    provider_tx_id  = Column(String, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    paid_at         = Column(DateTime(timezone=True), nullable=True)
