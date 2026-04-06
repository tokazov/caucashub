"""
Сделка (Deal) — фиксирует факт договорённости между грузовладельцем и перевозчиком.
Хранит полную историю: статусы, даты, документы.
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base


class DealStatus(str, enum.Enum):
    confirmed  = "confirmed"   # перевозчик принят, сделка открыта
    loading    = "loading"     # загрузка
    in_transit = "in_transit"  # груз в пути
    delivered  = "delivered"   # доставлен, ждём подтверждения второй стороны
    completed  = "completed"   # обе стороны подтвердили, акт выписан
    rated      = "rated"       # оценка выставлена
    disputed   = "disputed"    # спор
    canceled   = "canceled"    # отменена


class Deal(Base):
    __tablename__ = "deals"

    id           = Column(Integer, primary_key=True, index=True)

    # Участники
    load_id      = Column(Integer, ForeignKey("loads.id"), nullable=False)
    shipper_id   = Column(Integer, ForeignKey("users.id"), nullable=False)   # грузовладелец
    carrier_id   = Column(Integer, ForeignKey("users.id"), nullable=False)   # перевозчик
    response_id  = Column(Integer, ForeignKey("responses.id"), nullable=True)  # отклик который приняли

    # Статус
    status       = Column(Enum(DealStatus), default=DealStatus.confirmed, index=True)

    # Финансы (фиксируем на момент сделки)
    agreed_price = Column(Float, nullable=True)   # согласованная цена
    currency     = Column(String(3), default="GEL")  # GEL / USD

    # Даты
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    loading_at       = Column(DateTime(timezone=True), nullable=True)   # фактическая загрузка
    delivered_at     = Column(DateTime(timezone=True), nullable=True)   # фактическая доставка
    completed_at     = Column(DateTime(timezone=True), nullable=True)   # закрытие сделки

    # Подтверждения
    shipper_confirmed  = Column(Boolean, default=False)  # грузовладелец подтвердил доставку
    carrier_confirmed  = Column(Boolean, default=False)  # перевозчик подтвердил доставку

    # Документы
    act_number   = Column(String, nullable=True, unique=True)  # номер акта (CH-2026-0001)
    notes        = Column(Text, nullable=True)

    # Связи
    load     = relationship("Load",     foreign_keys=[load_id])
    shipper  = relationship("User",     foreign_keys=[shipper_id])
    carrier  = relationship("User",     foreign_keys=[carrier_id])
    response = relationship("Response", foreign_keys=[response_id])
