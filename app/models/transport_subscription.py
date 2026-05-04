"""
TransportSubscription — подписка грузовладельца на транспортные предложения (ADR-016).

Аналог RouteSubscription, но инвертирован:
- Грузовладелец подписывается на маршрут
- Уведомление приходит когда перевозчик публикует TransportOffer по этому маршруту
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

TRANSPORT_SUBSCRIPTION_LIMIT = 50  # safety-cap


class TransportSubscription(Base):
    __tablename__ = "transport_subscriptions"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                          nullable=False, index=True)

    from_city    = Column(String(100), nullable=False)   # нормализованное lowercase
    to_city      = Column(String(100), nullable=False)

    # Каналы
    notify_tg    = Column(Boolean, default=True)
    notify_email = Column(Boolean, default=False)

    # Опциональные фильтры
    truck_type   = Column(String(50), nullable=True)
    max_weight_t = Column(Integer, nullable=True)   # мин. вместимость в тоннах (что нужно)

    is_active    = Column(Boolean, default=True, index=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    last_notified_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
