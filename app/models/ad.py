from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class Ad(Base):
    __tablename__ = "ads"

    id = Column(Integer, primary_key=True, index=True)
    advertiser = Column(String(200), nullable=False)          # Название рекламодателя
    image_url = Column(String(500), nullable=True)            # URL логотипа/баннера
    link_url = Column(String(500), nullable=False)            # Куда ведёт клик
    title = Column(String(200), nullable=True)                # Заголовок (для нативных блоков)
    description = Column(Text, nullable=True)                 # Описание (для нативных блоков)
    cta_text = Column(String(100), nullable=True)             # Текст кнопки CTA
    placement = Column(String(50), nullable=False)            # feed / rates / modal / footer / banner
    clicks = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
