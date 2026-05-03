from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base

class ResponseStatus(str, enum.Enum):
    pending  = "pending"
    accepted = "accepted"
    rejected = "rejected"

class Response(Base):
    __tablename__ = "responses"

    id        = Column(Integer, primary_key=True, index=True)
    load_id   = Column(Integer, ForeignKey("loads.id"), nullable=False)
    user_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    message   = Column(Text, nullable=True)
    price_usd = Column(Integer, nullable=True)  # предложенная цена
    status    = Column(Enum(ResponseStatus), default=ResponseStatus.pending)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    load = relationship("Load", backref="responses")
    user = relationship("User", backref="responses")
