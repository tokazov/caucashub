"""Модель City — справочник городов (ADR-007)."""
from sqlalchemy import Column, Integer, String, Float, Boolean
from app.database import Base


class City(Base):
    __tablename__ = "cities"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    name_ru       = Column(String(100), nullable=False, index=True)
    name_ge       = Column(String(100), nullable=True)
    country_iso   = Column(String(2), nullable=False, index=True)
    lat           = Column(Float, nullable=True)
    lon           = Column(Float, nullable=True)
    is_popular    = Column(Boolean, server_default='1', nullable=False)
    yandex_geo_id = Column(String(50), nullable=True)  # для Advanced-лицензии
