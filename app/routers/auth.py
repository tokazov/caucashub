from fastapi import APIRouter, Depends, HTTPException, Request
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
import time
import threading

router = APIRouter()
pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
bearer_scheme = HTTPBearer()

# ── Brute-force protection (4.2.5) ───────────────────────────────────────────
# In-memory store: {ip: {"count": int, "window_start": float, "blocked_until": float}}
_login_attempts: dict = {}
_login_lock = threading.Lock()
_RATE_LIMIT_MAX = 5       # попыток в окне
_RATE_LIMIT_WINDOW = 60   # секунд (окно)
_RATE_LIMIT_BLOCK = 900   # секунд блокировки (15 минут)


def _check_brute_force_generic(
    ip: str, scope: str,
    max_attempts: int = 5, window: int = 60, block: int = 900
) -> None:
    """Общий rate limiter по IP+scope. Thread-safe."""
    now = time.time()
    key = f"{scope}:{ip}"
    with _login_lock:
        entry = _login_attempts.get(key, {"count": 0, "window_start": now, "blocked_until": 0})
        if entry["blocked_until"] > now:
            secs = int(entry["blocked_until"] - now)
            raise HTTPException(status_code=429, detail=f"Слишком много запросов. Попробуйте через {secs} сек.")
        if now - entry["window_start"] > window:
            entry = {"count": 0, "window_start": now, "blocked_until": 0}
        entry["count"] += 1
        if entry["count"] > max_attempts:
            entry["blocked_until"] = now + block
            _login_attempts[key] = entry
            raise HTTPException(status_code=429, detail=f"Слишком много запросов. Попробуйте через {block // 60} мин.")
        _login_attempts[key] = entry


def _check_brute_force(ip: str) -> None:
    """Raises 429 if IP exceeded login attempts. Thread-safe."""
    now = time.time()
    with _login_lock:
        entry = _login_attempts.get(ip, {"count": 0, "window_start": now, "blocked_until": 0})

        # Если IP заблокирован
        if entry["blocked_until"] > now:
            secs = int(entry["blocked_until"] - now)
            raise HTTPException(
                status_code=429,
                detail=f"Слишком много попыток. Попробуйте через {secs} секунд."
            )

        # Если окно истекло — сброс
        if now - entry["window_start"] > _RATE_LIMIT_WINDOW:
            entry = {"count": 0, "window_start": now, "blocked_until": 0}

        entry["count"] += 1
        if entry["count"] > _RATE_LIMIT_MAX:
            entry["blocked_until"] = now + _RATE_LIMIT_BLOCK
            _login_attempts[ip] = entry
            raise HTTPException(
                status_code=429,
                detail=f"Слишком много попыток. Попробуйте через {_RATE_LIMIT_BLOCK // 60} минут."
            )

        _login_attempts[ip] = entry


def _reset_brute_force(ip: str) -> None:
    """Сбросить счётчик при успешном логине."""
    with _login_lock:
        _login_attempts.pop(ip, None)

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

# Топ-50 популярных паролей (Фикс 4)
_WEAK_PASSWORDS = {
    "password","password1","123456","12345678","qwerty","abc123","monkey","1234567",
    "letmein","trustno1","dragon","baseball","iloveyou","master","sunshine","ashley",
    "bailey","passw0rd","shadow","123123","654321","superman","qazwsx","michael",
    "football","Password","login","welcome","solo","princess","starwars","whatever",
    "qwerty123","12345","1234","111111","1111","password2","iloveyou1","000000",
    "pass","1q2w3e","1q2w3e4r","zxcvbnm","123qwe","qwertyuiop","qwerty1","pass123",
    "admin","root","user","test","guest","demo","hello","hello123","summer","winter",
}

def validate_password(password: str) -> None:
    """Фикс 4: Проверяет пароль на минимальную длину и слабые значения."""
    if not password or len(password) < 8:
        raise HTTPException(
            status_code=422,
            detail="Пароль слишком короткий — минимум 8 символов"
        )
    if password.lower() in _WEAK_PASSWORDS:
        raise HTTPException(
            status_code=422,
            detail="Пароль слишком простой — выберите более надёжный"
        )

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
    # ADR-010: удалённый пользователь — инвалидируем любую активную сессию
    if getattr(user, 'is_deleted', False):
        raise HTTPException(status_code=401, detail="Аккаунт удалён")
    # 2.4.2: заблокированный пользователь не может действовать
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован. Обратитесь в поддержку.")
    return user

@router.post("/register")
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # 5.5.4: Rate limit на регистрацию — 10 попыток/мин с одного IP
    client_ip = request.client.host if request.client else "unknown"
    _check_brute_force_generic(client_ip, "register", max_attempts=10, window=60, block=300)
    # Фикс 4: Валидация пароля
    validate_password(data.password)
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    if data.phone:
        phone_check = await db.execute(select(User).where(User.phone == data.phone))
        if phone_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Phone already registered")

    from app.services.normalizers import normalize_user_fields, sanitize_text
    from app.services.dictionaries import normalize_org_type
    normalized = normalize_user_fields(
        email=data.email,
        phone=data.phone,
        company_name=data.company_name,
        inn=data.inn,
    )
    # XSS-санитизация company_name
    if normalized.get("company_name"):
        normalized["company_name"] = sanitize_text(normalized["company_name"], max_length=200)
    user = User(
        email=normalized.get("email", data.email),
        hashed_password=hash_password(data.password),
        company_name=normalized.get("company_name", data.company_name),
        phone=normalized.get("phone", data.phone),
        role=UserRole(data.role),
        lang=data.lang,
        inn=normalized.get("inn", data.inn),
        org_type=normalize_org_type(data.org_type or ""),
        city=data.city,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    # Инвалидируем кеш счётчиков (новый пользователь — Трек 11.2)
    from app.routers.stats import invalidate_counters_cache
    invalidate_counters_cache()
    return {"token": create_token(user.id), "user_id": user.id}

@router.post("/login")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # 4.2.5: Brute-force protection — 5 попыток / минуту, блок 15 мин
    client_ip = request.client.host if request.client else "unknown"
    _check_brute_force(client_ip)

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    # ADR-010: удалённый аккаунт — 401 без подсказки о пароле
    if user and getattr(user, 'is_deleted', False):
        raise HTTPException(status_code=401, detail="Аккаунт не найден или удалён")
    if not user or not user.hashed_password or not pwd_context.verify(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Успешный логин — сбрасываем счётчик
    _reset_brute_force(client_ip)
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
async def forgot_password(data: ForgotRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # 5.5.4: Rate limit — 3 запроса кода в 10 минут с одного IP
    client_ip = request.client.host if request.client else "unknown"
    _check_brute_force_generic(client_ip, "forgot", max_attempts=3, window=600, block=600)
    import secrets
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
        
        html = f"""<div style="font-family:Arial;padding:20px;max-width:480px;margin:0 auto">
            <div style="background:#1a1a2e;padding:20px;text-align:center;border-radius:12px 12px 0 0">
              <span style="color:#fff;font-weight:900;font-size:22px">Caucas<span style="color:#f7b731">Hub</span></span>
            </div>
            <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #eee">
              <p style="margin:0 0 16px;font-size:16px;color:#333">Сброс пароля на <strong>CaucasHub.ge</strong></p>
              <p style="margin:0 0 12px;font-size:14px;color:#666">Ваш код подтверждения:</p>
              <div style="background:#f8f9fa;border:2px solid #f7b731;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px">
                <div style="font-size:40px;font-weight:900;letter-spacing:12px;color:#1a1a2e">{code}</div>
              </div>
              <p style="margin:0;font-size:13px;color:#888">⏱ Код действует <strong>15 минут</strong></p>
            </div>
        </div>"""

                # Отправка через Resend API
        RESEND_API_KEY = "re_UesN9evJ_H9Me3arJbM74gL1d2quF2te1"
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                r = await client.post("https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "from": "CaucasHub <onboarding@resend.dev>",
                        "to": [data.email],
                        "subject": "CaucasHub — код сброса пароля",
                        "html": html,
                    },
                    timeout=15)
                if r.status_code not in (200, 201):
                    pass  # email не отправлен — продолжаем без ошибки
        except Exception:
            pass

    # 4.3.2: НЕ раскрываем существование email (anti info-leak)
    # Одинаковый ответ независимо от того, найден ли пользователь
    return {"message": "Если такой email зарегистрирован — мы отправили код подтверждения"}


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
    # Фикс 4: Валидация нового пароля при сбросе
    validate_password(data.new_password)
    # Меняем пароль
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.hashed_password = hash_password(data.new_password)
    await db.execute(sa_delete(ResetCode).where(ResetCode.email == data.email))
    await db.commit()
    return {"message": "Пароль успешно изменён"}

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

@router.post("/change-password")
async def change_password(data: ChangePasswordRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user)):
    if not pwd_context.verify(data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    validate_password(data.new_password)
    current_user.hashed_password = hash_password(data.new_password)
    await db.commit()
    return {"message": "Пароль успешно изменён"}
