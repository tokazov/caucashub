from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.database import get_db
from app.models.user import User, UserRole, ResetCode
from app.config import settings
from app.services.admin_auth import admin_secret_matches
from pydantic import BaseModel, Field
from typing import Optional
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
import time
import threading
import hashlib
import hmac
import logging
import math
import secrets

logger = logging.getLogger(__name__)

router = APIRouter()
# Фикс 2: bcrypt как основной алгоритм. sha256_crypt — deprecated (postlogin upgrade).
# При логине: если хеш sha256_crypt → перехешируем в bcrypt прозрачно для пользователя.
pwd_context = CryptContext(
    schemes=["bcrypt", "sha256_crypt"],
    deprecated=["sha256_crypt"],
)
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

from app.carrier_profile import CarrierProfileFields


class RegisterRequest(CarrierProfileFields):
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
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="Пароль должен занимать не больше 72 байт UTF-8")
    if password.lower() in _WEAK_PASSWORDS:
        raise HTTPException(
            status_code=422,
            detail="Пароль слишком простой — выберите более надёжный"
        )

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _password_version(value: datetime | None) -> str:
    return _as_utc(value).isoformat(timespec="microseconds") if value is not None else ""


def _verify_password(password: str, encoded: str | None) -> bool:
    try:
        return bool(encoded) and pwd_context.verify(password, encoded)
    except (ValueError, TypeError):
        return False


def create_token(user_id: int, password_changed_at: datetime | None = None, password_version: int = 0):
    now = _utcnow()
    return jwt.encode(
        {"sub": str(user_id), "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
         "iat": int(now.timestamp()), "pwdv": _password_version(password_changed_at),
         "ver": password_version},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )


async def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload.get("sub"))
        issued = payload.get("iat")
        if isinstance(issued, bool) or not isinstance(issued, (int, float)) or not math.isfinite(issued):
            raise ValueError("Missing issuance time")
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if user.is_deleted:
        raise HTTPException(status_code=401, detail="Аккаунт удалён")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован. Обратитесь в поддержку.")
    changed = user.password_changed_at
    if "pwdv" in payload:
        valid = (type(payload.get("ver")) is int and payload["ver"] == (user.password_version or 0)
                 and isinstance(payload["pwdv"], str) and hmac.compare_digest(
            payload["pwdv"].encode(), _password_version(changed).encode()))
    else:
        # Preserve existing legacy sessions until an actual new password change.
        # The additive counter then revokes every legacy token, even in the same second.
        changed_second = int(_as_utc(changed).timestamp()) if changed is not None else None
        valid = (user.password_version or 0) == 0 and (changed_second is None or issued >= changed_second)
    if not valid:
        raise HTTPException(status_code=401, detail="Сессия устарела — войдите заново")
    return user


async def _locked_password_user(db, *, user_id=None, email=None):
    criterion = (User.id == user_id if user_id is not None
                 else func.lower(func.trim(User.email)) == email.strip().lower())
    result = await db.execute(select(User).where(criterion).order_by(User.id).limit(2)
                              .with_for_update().execution_options(populate_existing=True))
    matches = list(result.scalars().all())
    # Ambiguous legacy case variants must never select an arbitrary account.
    return matches[0] if len(matches) == 1 else None


async def _revoke_password_state(db, user):
    now = _utcnow()
    previous = user.password_changed_at
    if previous is not None and now <= _as_utc(previous):
        now = _as_utc(previous) + timedelta(microseconds=1)
    user.password_changed_at = now
    user.password_version = (user.password_version or 0) + 1
    if user.telegram_id and user.telegram_id.startswith("pending:"):
        user.telegram_id = None
    await db.execute(delete(ResetCode).where(func.lower(func.trim(ResetCode.email)) == user.email.strip().lower()))
    from app.routers.users import _phone_change_codes
    _phone_change_codes.pop(user.id, None)


async def _send_password_email(to, subject, html, *, idempotency_key):
    from app.services import notification_channels
    try:
        result = await notification_channels.send_email(to, subject, html, idempotency_key=idempotency_key)
        if result.status != "sent":
            logger.warning("Password email delivery was not confirmed (status=%s)", result.status)
        return result.status == "sent"
    except Exception:
        logger.warning("Password email delivery raised an error")
        return False


def _password_text(lang, ge, ru):
    return ge if lang in ("ge", "ka") else ru


async def _notify_password_changed(user):
    title = _password_text(user.lang, "CaucasHub — პაროლი შეიცვალა", "CaucasHub — пароль изменён")
    body = _password_text(user.lang,
        "თქვენი ანგარიშის პაროლი შეიცვალა. წინა სესიები გაუქმებულია. თუ ეს თქვენ არ იყავით, აღადგინეთ წვდომა საიტზე.",
        "Пароль вашего аккаунта изменён. Предыдущие сессии завершены. Если это были не вы, восстановите доступ на сайте.")
    await _send_password_email(user.email.strip().lower(), title, f"<p>{body}</p>",
        idempotency_key=f"password-changed:{user.id}:{_password_version(user.password_changed_at)}")


@router.post("/register")
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # 5.5.4: Rate limit на регистрацию — 10 попыток/мин с одного IP
    client_ip = request.client.host if request.client else "unknown"
    _check_brute_force_generic(client_ip, "register", max_attempts=10, window=60, block=300)
    # Фикс 4: Валидация пароля
    validate_password(data.password)
    data.email = data.email.strip().lower()
    existing = await db.execute(select(User.id).where(func.lower(func.trim(User.email)) == data.email))
    if existing.first():
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
    # Маппинг расширенных ролей с фронта → валидные значения enum
    _role_map = {
        "shipper_person": "shipper",
        "shipper_company": "shipper",
        "shipper": "shipper",
        "carrier": "carrier",
        "both": "both",
    }
    mapped_role = _role_map.get(data.role, "carrier")
    try:
        user_role = UserRole(mapped_role)
    except ValueError:
        user_role = UserRole.carrier

    user = User(
        email=normalized.get("email", data.email),
        hashed_password=hash_password(data.password),
        company_name=normalized.get("company_name", data.company_name),
        phone=normalized.get("phone", data.phone),
        role=user_role,
        lang=data.lang,
        inn=normalized.get("inn", data.inn),
        org_type=normalize_org_type(data.org_type or ""),
        city=data.city,
        truck_type=data.truck_type.value if data.truck_type is not None else None,
        tonnage=data.tonnage,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    # Инвалидируем кеш счётчиков (новый пользователь — Трек 11.2)
    from app.routers.stats import invalidate_counters_cache
    invalidate_counters_cache()
    # Уведомление владельцу о новом пользователе
    try:
        from app.services.telegram_notify import notify_owner_new_user
        import asyncio
        asyncio.create_task(notify_owner_new_user(
            user_id=user.id,
            company_name=user.company_name or user.email,
            role=str(user.role.value if hasattr(user.role, 'value') else user.role),
            city=user.city,
            lang=user.lang or 'ru',
        ))
    except Exception:
        pass  # не ломаем регистрацию если уведомление не отправилось
    return {"token": create_token(user.id, user.password_changed_at, user.password_version), "user_id": user.id,
            "truck_type": user.truck_type, "tonnage": user.tonnage}

@router.post("/login")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # 4.2.5: Brute-force protection — 5 попыток / минуту, блок 15 мин
    client_ip = request.client.host if request.client else "unknown"
    _check_brute_force(client_ip)

    user = await _locked_password_user(db, email=data.email.strip().lower())
    # ADR-010: удалённый аккаунт — 401 без подсказки о пароле
    if user and getattr(user, 'is_deleted', False):
        raise HTTPException(status_code=401, detail="Аккаунт не найден или удалён")
    if not user or not user.hashed_password or not _verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован. Обратитесь в поддержку.")

    # Фикс 2: Postlogin bcrypt upgrade — если хеш sha256_crypt, перехешируем в bcrypt
    if len(data.password.encode("utf-8")) <= 72 and pwd_context.needs_update(user.hashed_password):
        user.hashed_password = pwd_context.hash(data.password)
    await db.commit()

    # Успешный логин — сбрасываем счётчик
    _reset_brute_force(client_ip)
    return {"token": create_token(user.id, user.password_changed_at, user.password_version), "user_id": user.id, "role": user.role}

@router.get("/admin/users")
async def admin_list_users(secret: str, db: AsyncSession = Depends(get_db)):
    if not admin_secret_matches(secret):
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
    if not admin_secret_matches(secret):
        raise HTTPException(status_code=403, detail="Forbidden")
    validate_password(new_password)
    user = await _locked_password_user(db, email=email.strip().lower())
    if user is None or user.is_deleted:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(new_password)
    await _revoke_password_state(db, user)
    await db.commit()
    await _notify_password_changed(user)
    return {"ok": True, "email": user.email}



class ForgotRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetRequest(ForgotRequest):
    code: str = Field(pattern=r"^[0-9]{6}$")
    new_password: str


_RESET_WINDOW = timedelta(minutes=15)
_RESET_COOLDOWN = timedelta(seconds=60)
_RESET_MAX_ATTEMPTS = 5
_RESET_MAX_REQUESTS = 3
_FORGOT_MESSAGE = "Если адрес зарегистрирован, инструкция по восстановлению будет отправлена на почту"


def _reset_digest(email, code, salt):
    value = f"{email}:{salt}:{code}".encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), value, hashlib.sha256).hexdigest()
    return f"h1.{salt}.{digest}"


def _reset_matches(email, supplied, stored):
    if not isinstance(stored, str):
        return False
    if stored.startswith("h1."):
        parts = stored.split(".")
        return len(parts) == 3 and hmac.compare_digest(_reset_digest(email, supplied, parts[1]), stored)
    # Codes issued before this additive release retain their original short TTL.
    return len(stored) == 6 and stored.isascii() and stored.isdigit() and hmac.compare_digest(supplied, stored)


async def _latest_reset(db, email):
    return (await db.execute(select(ResetCode).where(func.lower(func.trim(ResetCode.email)) == email)
        .order_by(ResetCode.id.desc()).limit(1).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none()


@router.post("/forgot-password")
async def forgot_password(data: ForgotRequest, request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    _check_brute_force_generic(client_ip, "forgot", max_attempts=3, window=600, block=600)
    email = data.email.strip().lower()
    user = await _locked_password_user(db, email=email)
    if user is None or user.is_deleted or not user.is_active:
        return {"message": _FORGOT_MESSAGE}
    now = _utcnow()
    previous = await _latest_reset(db, email)
    active = previous is not None and previous.expires_at is not None and _as_utc(previous.expires_at) > now
    if active and (
        (previous.attempts or 0) >= _RESET_MAX_ATTEMPTS
        or (previous.request_count or 0) >= _RESET_MAX_REQUESTS
        or (previous.created_at is not None and _as_utc(previous.created_at) + _RESET_COOLDOWN > now)
    ):
        return {"message": _FORGOT_MESSAGE}
    expires = _as_utc(previous.expires_at) if active else now + _RESET_WINDOW
    attempts = (previous.attempts or 0) if active else 0
    requests = (previous.request_count or 0) + 1 if active else 1
    code = f"{secrets.randbelow(1000000):06d}"
    salt = secrets.token_urlsafe(16)
    await db.execute(delete(ResetCode).where(func.lower(func.trim(ResetCode.email)) == email))
    db.add(ResetCode(email=email, code=_reset_digest(email, code, salt),
                     expires_at=expires.replace(tzinfo=None), created_at=now,
                     attempts=attempts, request_count=requests))
    await db.commit()
    title = _password_text(user.lang, "CaucasHub — პაროლის აღდგენა", "CaucasHub — восстановление пароля")
    intro = _password_text(user.lang, "პაროლის აღდგენის კოდი", "Код восстановления пароля")
    expiry = _password_text(user.lang,
        "კოდი მოქმედებს 15 წუთამდე. თუ აღდგენა არ მოგითხოვიათ, უგულებელყავით წერილი.",
        "Код действует до 15 минут. Если вы не запрашивали восстановление, проигнорируйте письмо.")
    await _send_password_email(email, title,
        f"<p>{intro}:</p><p style='font-size:32px;font-weight:bold;letter-spacing:8px'>{code}</p><p>{expiry}</p>",
        idempotency_key=f"password-reset:{user.id}:{salt}")
    return {"message": _FORGOT_MESSAGE}


@router.post("/reset-password")
async def reset_password(data: ResetRequest, request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    _check_brute_force_generic(client_ip, "reset", max_attempts=10, window=600, block=600)
    email = data.email.strip().lower()
    user = await _locked_password_user(db, email=email)
    invalid = HTTPException(status_code=400, detail="Неверный или просроченный код")
    if user is None or user.is_deleted or not user.is_active:
        raise invalid
    code = await _latest_reset(db, email)
    if code is None or code.expires_at is None or _as_utc(code.expires_at) <= _utcnow():
        raise invalid
    if (code.attempts or 0) >= _RESET_MAX_ATTEMPTS:
        raise invalid
    if not _reset_matches(email, data.code, code.code):
        code.attempts = (code.attempts or 0) + 1
        await db.commit()
        raise invalid
    validate_password(data.new_password)
    user.hashed_password = hash_password(data.new_password)
    await _revoke_password_state(db, user)
    await db.commit()
    await _notify_password_changed(user)
    return {"message": "Пароль успешно изменён"}


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest, request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    client_ip = request.client.host if request.client else "unknown"
    _check_brute_force_generic(client_ip, "change_password", max_attempts=10, window=600, block=600)
    user = await _locked_password_user(db, user_id=current_user.id)
    # The token may have been revoked while this request waited for the row.
    await require_user(credentials=credentials, db=db)
    if not _verify_password(data.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    validate_password(data.new_password)
    user.hashed_password = hash_password(data.new_password)
    await _revoke_password_state(db, user)
    await db.commit()
    await _notify_password_changed(user)
    return {"message": "Пароль успешно изменён"}
