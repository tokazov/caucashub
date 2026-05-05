from sqlalchemy import Column, Integer, Float, DateTime, Enum, ForeignKey, Text, Numeric
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base

class ResponseStatus(str, enum.Enum):
    pending   = "pending"
    accepted  = "accepted"
    rejected  = "rejected"
    withdrawn = "withdrawn"  # перевозчик отозвал отклик (ADR-008 / Трек 8)

class Response(Base):
    __tablename__ = "responses"

    id        = Column(Integer, primary_key=True, index=True)
    load_id   = Column(Integer, ForeignKey("loads.id"), nullable=False)
    user_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    message   = Column(Text, nullable=True)
    price_usd = Column(Numeric(12, 2), nullable=True)    # предложенная цена в USD
    price_gel = Column(Numeric(12, 2), nullable=True)    # предложенная цена в GEL
    exchange_rate_at_creation = Column(Numeric(12, 6), nullable=True)  # GEL/USD из NBG
    status    = Column(Enum(ResponseStatus), default=ResponseStatus.pending)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    load = relationship("Load", backref="responses")
    user = relationship("User", backref="responses")
