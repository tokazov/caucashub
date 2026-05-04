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

    # Источник сделки (ADR-016.1): ровно одно из двух заполнено
    # cargo_id — сделка из груза (старый путь)
    # transport_offer_id — сделка из транспортного предложения (новый путь)
    load_id              = Column(Integer, ForeignKey("loads.id"), nullable=True)   # nullable! (ADR-016)
    transport_offer_id   = Column(Integer, ForeignKey("transport_offers.id"), nullable=True)
    transport_request_id = Column(Integer, ForeignKey("transport_requests.id"), nullable=True)

    # Участники
    shipper_id   = Column(Integer, ForeignKey("users.id"), nullable=False)   # грузовладелец
    carrier_id   = Column(Integer, ForeignKey("users.id"), nullable=False)   # перевозчик
    response_id  = Column(Integer, ForeignKey("responses.id"), nullable=True)  # отклик (груз-путь)

    # Статус
    status       = Column(Enum(DealStatus), default=DealStatus.confirmed, index=True)

    # Финансы (фиксируем на момент сделки)
    agreed_price          = Column(Float, nullable=True)   # согласованная цена (в currency)
    currency              = Column(String(3), default="GEL")  # GEL / USD
    exchange_rate_snapshot = Column(Float, nullable=True)  # GEL/USD зафиксирован при создании
    final_price_gel       = Column(Float, nullable=True)   # итог в GEL (снапшот)
    final_price_usd       = Column(Float, nullable=True)   # итог в USD (снапшот)

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
    load             = relationship("Load",             foreign_keys=[load_id])
    transport_offer  = relationship("TransportOffer",   foreign_keys=[transport_offer_id])
    transport_request= relationship("TransportRequest", foreign_keys=[transport_request_id])
    shipper          = relationship("User",             foreign_keys=[shipper_id])
    carrier          = relationship("User",             foreign_keys=[carrier_id])
    response         = relationship("Response",         foreign_keys=[response_id])

    @property
    def deal_source(self) -> str:
        """'cargo' или 'transport' — тип сделки."""
        return "transport" if self.transport_offer_id else "cargo"
