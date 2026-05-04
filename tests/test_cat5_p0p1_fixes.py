"""
Тесты P0/P1-фиксов Категории 5.

Фикс 1: GET /api/auth/debug-register → 404
Фикс 2: bcrypt upgrade при логине (sha256_crypt → bcrypt после первого логина)
Фикс 3: JWT инвалидация после смены пароля (password_changed_at > iat → 401)
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_cat5_p0p1.db")
os.environ.setdefault("SECRET_KEY", "test-cat5-p0p1-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

import pytest
import pytest_asyncio
import json as _json
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete as sql_delete
from passlib.context import CryptContext

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User, UserRole, UserPlan
from app.routers.auth import _login_attempts, create_token

pwd_sha256 = CryptContext(schemes=["sha256_crypt"])
transport = ASGITransport(app=app)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    from app.models.response import Response
    from app.models.deal import Deal
    from app.models.status_change import StatusChange
    from app.models.load import Load

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await db.execute(sql_delete(StatusChange))
        await db.execute(sql_delete(Deal))
        await db.execute(sql_delete(Response))
        await db.execute(sql_delete(Load))
        await db.execute(sql_delete(User))
        await db.commit()

    _login_attempts.clear()
    yield


# ── Фикс 1: debug-register удалён ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_debug_register_removed():
    """GET /api/auth/debug-register должен возвращать 404."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/auth/debug-register")
    assert r.status_code == 404, f"debug-register должен быть удалён (404), получили {r.status_code}"


@pytest.mark.asyncio
async def test_ai_dispatcher_debug_removed():
    """POST /api/ai/dispatcher/debug должен возвращать 404 или 405."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/ai/dispatcher/debug", json={"message": "test"})
    assert r.status_code in (404, 405, 422), f"dispatcher/debug должен быть удалён, получили {r.status_code}"


# ── Фикс 2: bcrypt postlogin upgrade ──────────────────────────────────────
@pytest.mark.asyncio
async def test_bcrypt_upgrade_on_login():
    """
    Пользователь с sha256_crypt хешем → после логина хеш автоматически обновляется до bcrypt.
    """
    # Создаём пользователя напрямую с sha256_crypt хешем (имитация старого пользователя)
    sha256_hash = pwd_sha256.hash("OldPass99!")
    async with AsyncSessionLocal() as db:
        user = User(
            email="bcrypt_test@test.ge",
            hashed_password=sha256_hash,
            company_name="BCrypt Test",
            phone="+995500010001",
            role=UserRole.carrier,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    # Проверяем что хеш действительно sha256_crypt
    assert "$5$" in sha256_hash or "sha256_crypt" in pwd_sha256.identify(sha256_hash), \
        "Начальный хеш должен быть sha256_crypt"

    # Логинимся
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/login", json={
            "email": "bcrypt_test@test.ge",
            "password": "OldPass99!"
        })
    assert r.status_code == 200, f"Логин не удался: {r.text}"

    # Проверяем что хеш обновился до bcrypt
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.id == user_id))
        user_after = result.scalar_one_or_none()

    assert user_after.hashed_password != sha256_hash, "Хеш должен был обновиться после логина"
    assert "$2b$" in user_after.hashed_password or user_after.hashed_password.startswith("$2"), \
        f"После логина хеш должен быть bcrypt ($2b$...), получили: {user_after.hashed_password[:20]}"


@pytest.mark.asyncio
async def test_new_registration_uses_bcrypt():
    """Новая регистрация создаёт bcrypt хеш."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/register", json={
            "email": "newbcrypt@test.ge",
            "password": "StrongPass99!",
            "company_name": "BCrypt New",
            "phone": "+995500010002",
            "role": "carrier"
        })
    assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.email == "newbcrypt@test.ge"))
        user = result.scalar_one_or_none()

    assert "$2b$" in user.hashed_password or user.hashed_password.startswith("$2"), \
        f"Новый пользователь должен иметь bcrypt хеш, получили: {user.hashed_password[:20]}"


# ── Фикс 3: JWT инвалидация после смены пароля ────────────────────────────
@pytest.mark.asyncio
async def test_token_invalid_after_password_change():
    """
    Сценарий: два активных токена (два браузера).
    После смены пароля через первый токен — второй токен должен возвращать 401.
    """
    # Регистрация
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        reg = await c.post("/api/auth/register", json={
            "email": "two_sessions@test.ge",
            "password": "StrongPass99!",
            "company_name": "Two Sessions",
            "phone": "+995500011001",
            "role": "carrier"
        })
    assert reg.status_code == 200
    token_1 = reg.json()["token"]

    # Второй логин (имитация второго браузера) — создаём токен напрямую
    # (чтобы не триггерить rate limit)
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.email == "two_sessions@test.ge"))
        user = result.scalar_one_or_none()
    token_2 = create_token(user.id)

    # Оба токена работают
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token_1}"})
        r2 = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token_2}"})
    assert r1.status_code == 200, "Токен 1 должен работать до смены пароля"
    assert r2.status_code == 200, "Токен 2 должен работать до смены пароля"

    # Меняем пароль через первый токен
    import asyncio
    await asyncio.sleep(1)  # Гарантируем что password_changed_at > iat токена 2
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        change = await c.post(
            "/api/auth/change-password",
            json={"old_password": "StrongPass99!", "new_password": "NewPass2026!"},
            headers={"Authorization": f"Bearer {token_1}"}
        )
    assert change.status_code == 200, f"Смена пароля не удалась: {change.text}"

    # Второй токен должен вернуть 401
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r_old = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token_2}"})
    assert r_old.status_code == 401, \
        f"Старый токен должен быть невалиден после смены пароля, получили {r_old.status_code}"


@pytest.mark.asyncio
async def test_token_invalid_after_account_deletion():
    """
    Старый токен удалённого пользователя → 401 (через password_changed_at).
    """
    # Регистрация
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        reg = await c.post("/api/auth/register", json={
            "email": "del_pca@test.ge",
            "password": "StrongPass99!",
            "company_name": "Del PCA",
            "phone": "+995500012001",
            "role": "carrier"
        })
    token = reg.json()["token"]

    # Удаляем аккаунт
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.request(
            "DELETE", "/api/users/me",
            content=_json.dumps({"confirmation": "УДАЛИТЬ"}),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
    assert r.status_code == 200

    # Старый токен → 401
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r2 = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 401, \
        f"Токен удалённого пользователя должен возвращать 401, получили {r2.status_code}"


@pytest.mark.asyncio
async def test_current_token_still_works_after_password_change():
    """
    Токен полученный ПОСЛЕ смены пароля работает корректно.
    """
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        reg = await c.post("/api/auth/register", json={
            "email": "current_tok@test.ge",
            "password": "StrongPass99!",
            "company_name": "Current Token",
            "phone": "+995500013001",
            "role": "carrier"
        })
    old_token = reg.json()["token"]

    import asyncio
    await asyncio.sleep(1)

    # Меняем пароль
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post(
            "/api/auth/change-password",
            json={"old_password": "StrongPass99!", "new_password": "NewPass2026!"},
            headers={"Authorization": f"Bearer {old_token}"}
        )

    # Логинимся с новым паролем — получаем новый токен
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        login = await c.post("/api/auth/login", json={
            "email": "current_tok@test.ge",
            "password": "NewPass2026!"
        })
    assert login.status_code == 200
    new_token = login.json()["token"]

    # Новый токен работает
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/users/me", headers={"Authorization": f"Bearer {new_token}"})
    assert r.status_code == 200, f"Новый токен после смены пароля должен работать: {r.status_code}"
