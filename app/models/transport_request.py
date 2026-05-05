"""
TransportRequest — отклик грузовладельца на TransportOffer (ADR-016).

Симметрично Response (отклик перевозчика на груз),
но инвертировано: грузовладелец откликается на транспорт.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Numeric
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base


class TransportRequestStatus(str, enum.Enum):
    pending  = "pending"   # ожидает ответа перевозчика
    accepted = "accepted"  # перевозчик принял → создана Deal
    rejected = "rejected"  # перевозчик отклонил
    canceled = "canceled"  # грузовладелец отозвал


class TransportRequest(Base):
    __tablename__ = "transport_requests"

    id                 = Column(Integer, primary_key=True, index=True)
    transport_offer_id = Column(Integer, ForeignKey("transport_offers.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    user_id            = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # грузовладелец

    # Описание груза
    cargo_description  = Column(Text, nullable=True)
    weight_kg          = Column(Float, nullable=True)

    # Предложенная цена (опционально)
    price              = Column(Numeric(12, 2), nullable=True)   # в GEL
    message            = Column(Text, nullable=True)

    # Статус
    status             = Column(String(20), default="pending", index=True)

    created_at         = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    offer   = relationship("TransportOffer", back_populates="requests")
    shipper = relationship("User", foreign_keys=[user_id])
