from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User, UserRole
from app.config import settings
from pydantic import BaseModel
from typing import Optional
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
import random, string

# Временное хранилище кодов сброса {email: (code, expires_at)}
_reset_codes: dict = {}

router = APIRouter()
pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

class RegisterRequest(BaseModel):
    email: str
    password: str
    company_name: str
    phone: str
    role: str = "carrier"
    lang: str = "ru"
    inn: Optional[str] = None       # ИНН / ID код
    org_type: Optional[str] = None  # ООО / ИП / АО
    city: Optional[str] = None      # Город

class LoginRequest(BaseModel):
    email: str
    password: str

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def create_token(user_id: int):
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expire}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Проверка дубликата
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    if data.phone:
        phone_check = await db.execute(select(User).where(User.phone == data.phone))
        if phone_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Phone already registered")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        company_name=data.company_name,
        phone=data.phone,
        role=UserRole(data.role),
        lang=data.lang,
        inn=data.inn,
        org_type=data.org_type,
        city=data.city,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"token": create_token(user.id), "user_id": user.id}

@router.post("/login")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token(user.id), "user_id": user.id, "role": user.role}

@router.get("/debug-register")
async def debug_register(db: AsyncSession = Depends(get_db)):
    """Debug — проверяем что таблица users существует и регистрация работает"""
    import traceback
    try:
        from sqlalchemy import text
        result = await db.execute(text("SELECT COUNT(*) FROM users"))
        count = result.scalar()
        
        # Пробуем создать тестового пользователя
        from datetime import datetime
        test_email = f"debug_{int(datetime.utcnow().timestamp())}@test.ge"
        test_user = User(
            email=test_email,
            hashed_password=pwd_context.hash("test123"),
            company_name="Debug Test",
            phone=None,
            role=UserRole.carrier
        )
        db.add(test_user)
        await db.commit()
        await db.refresh(test_user)
        
        # Удаляем тестового пользователя
        await db.delete(test_user)
        await db.commit()
        
        return {"status": "ok", "users_count": count, "register_test": "passed"}
    except Exception as e:
        return {"status": "error", "error": str(e), "tb": traceback.format_exc()[-500:]}


class ForgotRequest(BaseModel):
    email: str

class ResetRequest(BaseModel):
    email: str
    code: str
    new_password: str

@router.post("/forgot-password")
async def forgot_password(data: ForgotRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        # Не раскрываем что email не существует
        return {"ok": True, "dev_code": None}

    code = "".join(random.choices(string.digits, k=6))
    expires = datetime.utcnow() + timedelta(minutes=15)
    _reset_codes[data.email] = (code, expires)

    # Отправляем email (всегда возвращаем dev_code пока email не настроен)
    try:
        from app.email_utils import send_reset_code
        await send_reset_code(data.email, code)
    except Exception:
        pass
    return {"ok": True, "dev_code": code, "message": "Если email зарегистрирован — код отправлен"}

@router.post("/reset-password")
async def reset_password(data: ResetRequest, db: AsyncSession = Depends(get_db)):
    entry = _reset_codes.get(data.email)
    if not entry:
        raise HTTPException(status_code=400, detail="Код не найден или истёк")
    code, expires = entry
    if datetime.utcnow() > expires:
        _reset_codes.pop(data.email, None)
        raise HTTPException(status_code=400, detail="Код истёк")
    if code != data.code:
        raise HTTPException(status_code=400, detail="Неверный код")

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    user.hashed_password = hash_password(data.new_password)
    await db.commit()
    _reset_codes.pop(data.email, None)
    return {"ok": True, "message": "Пароль успешно изменён"}

@router.post("/admin/reset-password")
async def admin_reset_password(
    email: str,
    new_password: str,
    secret: str,
    db: AsyncSession = Depends(get_db)
):
    import os
    if secret != os.getenv("ADMIN_SECRET", "caucashub-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(new_password)
    await db.commit()
    return {"ok": True, "email": email}
