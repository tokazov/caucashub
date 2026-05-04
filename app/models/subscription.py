"""
Модель подписки на маршрут (ADR-014).
Пользователь подписывается на пару from_city/to_city и получает TG/email
уведомление когда появляется новый груз по этому маршруту.

Лимиты:
- Сейчас: 50 подписок на пользователя (safety-cap, защита от абуза)
- Pro-лимиты добавим позже после решения Тимура по тарифам
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class RouteSubscription(Base):
    __tablename__ = "route_subscriptions"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    from_city    = Column(String(100), nullable=False)   # нормализованное название (lowercase strip)
    to_city      = Column(String(100), nullable=False)   # нормализованное название
    # Каналы уведомлений
    notify_tg    = Column(Boolean, default=True)         # через Telegram
    notify_email = Column(Boolean, default=False)        # через email
    # Дополнительные фильтры (опционально, null = любой)
    truck_type   = Column(String(50), nullable=True)     # тип кузова ("gazel", "tent", ...)
    max_weight_t = Column(Integer, nullable=True)        # макс вес в тоннах
    # Состояние
    is_active    = Column(Boolean, default=True, index=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    last_notified_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="subscriptions")
