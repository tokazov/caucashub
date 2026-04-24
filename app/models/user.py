from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.sql import func
import enum
from app.database import Base

class UserRole(str, enum.Enum):
    carrier = "carrier"      # перевозчик
    shipper = "shipper"      # грузовладелец
    both = "both"            # оба

class UserPlan(str, enum.Enum):
    free = "free"
    standard = "standard"
    pro = "pro"
    pro_plus = "pro_plus"

class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    email         = Column(String, unique=True, index=True, nullable=False)
    phone         = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    company_name  = Column(String, nullable=True)
    full_name     = Column(String, nullable=True)
    role          = Column(Enum(UserRole), default=UserRole.carrier)
    plan          = Column(Enum(UserPlan), default=UserPlan.free)
    is_verified   = Column(Boolean, default=False)
    is_active     = Column(Boolean, default=True)
    telegram_id   = Column(String, nullable=True)
    rating        = Column(Integer, default=50)  # 0-50 → display as 0-5.0
    trips_count   = Column(Integer, default=0)
    lang          = Column(String, default="ru")  # ru / ge / en
    # Реквизиты (для документов / rs.ge)
    inn           = Column(String, nullable=True)   # ИНН / ID код Грузия
    org_type      = Column(String, nullable=True)   # ООО / ИП / АО
    city          = Column(String, nullable=True)   # Город работы
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    # Тарификация — счётчик откликов
    responses_this_month  = Column(Integer, default=0)
    responses_month_reset = Column(DateTime, nullable=True)


class ResetCode(Base):
    __tablename__ = "reset_codes"
    id         = Column(Integer, primary_key=True)
    email      = Column(String, index=True)
    code       = Column(String)
    expires_at = Column(DateTime)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
