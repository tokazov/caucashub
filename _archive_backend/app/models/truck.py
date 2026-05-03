from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.models.load import TruckType
from app.database import Base

class Truck(Base):
    __tablename__ = "trucks"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Характеристики
    truck_type   = Column(Enum(TruckType), nullable=False)
    capacity_kg  = Column(Float, nullable=False)
    volume_m3    = Column(Float, nullable=True)
    plate        = Column(String, nullable=True)

    # Доступность
    available_from = Column(String, nullable=False)   # город
    available_to   = Column(String, nullable=True)    # куда готов ехать
    available_date = Column(DateTime(timezone=True), nullable=True)
    is_available   = Column(Boolean, default=True)

    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    user         = relationship("User", backref="trucks")
