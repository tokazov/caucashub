"""
TransportOffer — предложение транспорта от перевозчика (ADR-016).

Перевозчик размещает: маршрут, дату, тип кузова, вместимость, цену.
Грузовладелец видит и откликается через TransportRequest.
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base


class TransportOfferStatus(str, enum.Enum):
    active    = "active"     # открыто для откликов
    taken     = "taken"      # принят отклик, сделка создана
    completed = "completed"  # сделка завершена
    canceled  = "canceled"   # снято с публикации


class TransportOffer(Base):
    __tablename__ = "transport_offers"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # перевозчик

    # Маршрут
    from_city    = Column(String(100), nullable=False)
    to_city      = Column(String(100), nullable=False)
    from_city_id = Column(Integer, ForeignKey("cities.id"), nullable=True)
    to_city_id   = Column(Integer, ForeignKey("cities.id"), nullable=True)

    # Характеристики
    truck_type   = Column(String(50), nullable=False)     # tent/gazel/ref/open/container
    capacity_kg  = Column(Float, nullable=False)          # вместимость в кг

    # Даты
    available_from = Column(DateTime(timezone=True), nullable=False)   # с какой даты
    available_to   = Column(DateTime(timezone=True), nullable=True)    # по какую дату

    # Цена
    price        = Column(Float, nullable=True)    # цена перевозки (в GEL)
    price_usd    = Column(Float, nullable=True)    # цена в USD

    # Доп. поля
    status       = Column(String(20), default="active", index=True)
    urgent       = Column(Boolean, default=False)
    notes        = Column(Text, nullable=True)       # комментарий перевозчика
    views        = Column(Integer, default=0)
    is_demo      = Column(Boolean, default=False)

    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    carrier        = relationship("User", foreign_keys=[user_id])
    requests       = relationship("TransportRequest", back_populates="offer",
                                  cascade="all, delete-orphan")
