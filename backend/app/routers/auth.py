from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User, UserRole
from app.config import settings
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
from app.email_utils import send_reset_code
import secrets, time

router = APIRouter()
pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

# ── In-memory хранилище reset-кодов: {email: {code, expires}} ──
# При рестарте сервиса сбрасывается — нормально для MVP
_reset_codes: dict = {}

class RegisterRequest(BaseModel):
    email: str
    password: str
    company_name: str
    phone: str
    role: str = "carrier"
    lang: str = "ru"

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

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        company_name=data.company_name,
        phone=data.phone,
        role=UserRole(data.role),
        lang=data.lang
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
    """Генерируем 6-значный код и возвращаем его (MVP — без email).
    В продакшене здесь отправим email/Telegram."""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    # Не раскрываем что юзер не существует — отвечаем одинаково
    if user:
        code = str(secrets.randbelow(900000) + 100000)  # 6-значный
        _reset_codes[data.email] = {
            "code": code,
            "expires": time.time() + 900,  # 15 минут
        }
        sent = await send_reset_code(data.email, code)
        response = {"ok": True, "message": "Код отправлен на email", "expires_in": 900}
        if not sent:
            # SMTP не настроен — возвращаем код (dev режим)
            response["dev_code"] = code
        return response
    return {"ok": True, "message": "Если email зарегистрирован, вы получите код"}


@router.post("/reset-password")
async def reset_password(data: ResetRequest, db: AsyncSession = Depends(get_db)):
    """Принимаем код и новый пароль, обновляем в БД."""
    entry = _reset_codes.get(data.email)
    if not entry:
        raise HTTPException(status_code=400, detail="Код не найден или устарел")
    if time.time() > entry["expires"]:
        del _reset_codes[data.email]
        raise HTTPException(status_code=400, detail="Код истёк. Запросите новый")
    if entry["code"] != data.code:
        raise HTTPException(status_code=400, detail="Неверный код")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Пароль минимум 6 символов")

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    user.hashed_password = pwd_context.hash(data.new_password)
    await db.commit()
    del _reset_codes[data.email]
    return {"ok": True, "message": "Пароль успешно изменён"}
