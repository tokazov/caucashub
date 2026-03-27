from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base

class TruckType(str, enum.Enum):
    tent      = "tent"
    ref       = "ref"
    bort      = "bort"
    termos    = "termos"
    gazel     = "gazel"
    container = "container"
    auto      = "auto"       # автовоз
    other     = "other"

class LoadScope(str, enum.Enum):
    local = "local"
    intl  = "intl"

class LoadStatus(str, enum.Enum):
    active   = "active"
    taken    = "taken"
    expired  = "expired"
    canceled = "canceled"

class Load(Base):
    __tablename__ = "loads"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Маршрут
    from_city     = Column(String, nullable=False, index=True)
    from_address  = Column(String, nullable=True)
    to_city       = Column(String, nullable=False, index=True)
    to_address    = Column(String, nullable=True)
    scope         = Column(Enum(LoadScope), default=LoadScope.local, index=True)

    # Груз
    weight_kg     = Column(Float, nullable=False)
    volume_m3     = Column(Float, nullable=True)
    truck_type    = Column(Enum(TruckType), nullable=False)
    cargo_desc    = Column(Text, nullable=True)

    # Цена
    price_usd     = Column(Float, nullable=True)
    price_gel     = Column(Float, nullable=True)
    payment_type  = Column(String, nullable=True)  # нал/безнал

    # Даты
    load_date     = Column(DateTime(timezone=True), nullable=False)
    is_urgent     = Column(Boolean, default=False)
    status        = Column(Enum(LoadStatus), default=LoadStatus.active, index=True)

    # Мета
    views         = Column(Integer, default=0)
    is_boosted    = Column(Boolean, default=False)  # платное поднятие
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    user          = relationship("User", backref="loads")
