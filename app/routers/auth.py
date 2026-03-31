from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User, UserRole
from app.config import settings
from pydantic import BaseModel
from typing import Optional
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta

router = APIRouter()
pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
bearer_scheme = HTTPBearer()

class RegisterRequest(BaseModel):
    email: str
    password: str
    company_name: str
    phone: str
    role: str = "carrier"
    lang: str = "ru"
    inn: Optional[str] = None
    org_type: Optional[str] = None
    city: Optional[str] = None

class LoginRequest(BaseModel):
    email: str
    password: str

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def create_token(user_id: int):
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expire}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

async def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
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
    import traceback
    try:
        from sqlalchemy import text
        result = await db.execute(text("SELECT COUNT(*) FROM users"))
        count = result.scalar()
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
        await db.delete(test_user)
        await db.commit()
        return {"status": "ok", "users_count": count, "register_test": "passed"}
    except Exception as e:
        return {"status": "error", "error": str(e), "tb": traceback.format_exc()[-500:]}

@router.get("/admin/users")
async def admin_list_users(secret: str, db: AsyncSession = Depends(get_db)):
    import os
    if secret != os.getenv("ADMIN_SECRET", "caucashub-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    result = await db.execute(select(User).order_by(User.id.desc()).limit(30))
    users = result.scalars().all()
    return [{"id": u.id, "email": u.email, "company": u.company_name, "role": str(u.role)} for u in users]

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


class ForgotRequest(BaseModel):
    email: str

class ResetRequest(BaseModel):
    email: str
    code: str
    new_password: str

@router.post("/forgot-password")
async def forgot_password(data: ForgotRequest, db: AsyncSession = Depends(get_db)):
    import secrets, os
    from datetime import datetime, timedelta
    from app.models.user import ResetCode
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    code = str(secrets.randbelow(900000) + 100000)
    if user:
        # Удаляем старые коды для этого email
        from sqlalchemy import delete as sa_delete
        await db.execute(sa_delete(ResetCode).where(ResetCode.email == data.email))
        # Сохраняем новый код в БД
        rc = ResetCode(email=data.email, code=code, expires_at=datetime.utcnow() + timedelta(minutes=15))
        db.add(rc)
        await db.commit()
        
        resend_key = os.getenv("RESEND_API_KEY", "re_UesN9evJ_H9Me3arJbM74gL1d2quF2te1")
        html = f"""<div style="font-family:Arial;padding:20px">
            <h2>Сброс пароля CaucasHub</h2>
            <p>Код подтверждения:</p>
            <div style="font-size:32px;font-weight:bold;background:#f0f0f0;padding:16px;text-align:center;border-radius:8px;letter-spacing:8px">{code}</div>
            <p style="color:#888;font-size:12px">Действителен 15 минут</p>
        </div>"""
        email_sent = False
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                r = await client.post("https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {resend_key}"},
                    json={"from": "CaucasHub <onboarding@resend.dev>",
                          "to": [data.email], "subject": "Код сброса пароля", "html": html},
                    timeout=10)
                if r.status_code == 200:
                    email_sent = True
        except Exception:
            pass

    return {"message": "Если email зарегистрирован — код отправлен",
            "dev_code": code if (user and not email_sent) else None}


@router.post("/reset-password")
async def reset_password(data: ResetRequest, db: AsyncSession = Depends(get_db)):
    from datetime import datetime
    from app.models.user import ResetCode
    from sqlalchemy import delete as sa_delete
    # Проверяем код в БД
    rc_result = await db.execute(select(ResetCode).where(ResetCode.email == data.email, ResetCode.code == data.code))
    rc = rc_result.scalar_one_or_none()
    if not rc or datetime.utcnow() > rc.expires_at:
        raise HTTPException(status_code=400, detail="Неверный или просроченный код")
    # Меняем пароль
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.hashed_password = hash_password(data.new_password)
    await db.execute(sa_delete(ResetCode).where(ResetCode.email == data.email))
    await db.commit()
    return {"message": "Пароль успешно изменён"}
