"""
Тесты Категории 5 — Авторизация и права.
Проверяем IDOR, доступ к чужим ресурсам, информационные утечки.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_cat5.db")
os.environ.setdefault("SECRET_KEY", "test-cat5-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

import pytest
import pytest_asyncio
import datetime
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete as sql_delete
from unittest.mock import patch, AsyncMock

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User, UserRole, UserPlan
from app.models.load import Load, LoadStatus
from app.models.response import Response, ResponseStatus
from app.models.deal import Deal
from app.models.status_change import StatusChange
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
transport = ASGITransport(app=app)

from app.services import exchange_rate as er_module
from app.routers.auth import _login_attempts, create_token


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        await db.execute(sql_delete(StatusChange))
        await db.execute(sql_delete(Deal))
        await db.execute(sql_delete(Response))
        await db.execute(sql_delete(Load))
        await db.execute(sql_delete(User))
        await db.commit()
    er_module.invalidate_cache()
    # Сбрасываем rate limit store между тестами
    _login_attempts.clear()
    yield


async def _register_direct(email: str, phone: str, role: str = "carrier") -> str:
    """Создаёт пользователя напрямую в БД (минуя rate limit)."""
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            hashed_password=pwd_context.hash("StrongPass99!"),
            company_name=f"Co_{role}",
            phone=phone,
            role=UserRole(role),
            plan=UserPlan.standard,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return create_token(user.id)


async def _register(email: str, phone: str, role: str = "carrier") -> str:
    """Регистрирует через API (с rate limit — используем только где нужно тестить API)."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/register", json={
            "email": email, "password": "StrongPass99!",
            "company_name": f"Co_{role}", "phone": phone, "role": role,
        })
    assert r.status_code == 200, f"Register failed: {r.text}"
    return r.json()["token"]


async def _create_load(token: str) -> int:
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=2.73):
        er_module.invalidate_cache()
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/api/loads/", json={
                "from_city": "Тбилиси", "to_city": "Батуми",
                "weight_kg": 1000, "truck_type": "tent", "price_gel": 500.0,
            }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, f"Create load failed: {r.text}"
    return r.json()["id"]


# ── IDOR: Доступ к чужому грузу ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_idor_patch_other_load_returns_403():
    """Пользователь B не может PATCH груз пользователя A."""
    token_a = await _register_direct("idor_a@test.ge", "+995500001001", "shipper")
    token_b = await _register_direct("idor_b@test.ge", "+995500001002", "shipper")
    load_id = await _create_load(token_a)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put(
            f"/api/loads/{load_id}",
            json={"price_gel": 100.0},
            headers={"Authorization": f"Bearer {token_b}"}
        )
    assert r.status_code == 403, f"IDOR: ожидали 403, получили {r.status_code}"


@pytest.mark.asyncio
async def test_idor_delete_other_load_returns_403():
    """Пользователь B не может DELETE груз пользователя A."""
    token_a = await _register_direct("idor_c@test.ge", "+995500001003", "shipper")
    token_b = await _register_direct("idor_d@test.ge", "+995500001004", "shipper")
    load_id = await _create_load(token_a)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete(
            f"/api/loads/{load_id}",
            headers={"Authorization": f"Bearer {token_b}"}
        )
    assert r.status_code == 403, f"IDOR: ожидали 403, получили {r.status_code}"


@pytest.mark.asyncio
async def test_idor_cancel_other_response_returns_403():
    """Пользователь B не может отменить отклик пользователя A."""
    token_shipper = await _register_direct("idor_e@test.ge", "+995500001005", "shipper")
    token_carrier_a = await _register_direct("idor_f@test.ge", "+995500001006", "carrier")
    token_carrier_b = await _register_direct("idor_g@test.ge", "+995500001007", "carrier")

    load_id = await _create_load(token_shipper)

    # Carrier A откликается
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=2.73):
        er_module.invalidate_cache()
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post(
                f"/api/responses/load/{load_id}",
                json={"price": 300.0},
                headers={"Authorization": f"Bearer {token_carrier_a}"}
            )
    assert r.status_code == 200
    resp_id = r.json()["response_id"]

    # Carrier B пытается отменить отклик carrier A
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete(
            f"/api/responses/cancel/{resp_id}",
            headers={"Authorization": f"Bearer {token_carrier_b}"}
        )
    assert r.status_code == 403, f"IDOR: ожидали 403, получили {r.status_code}"


# ── Публичный профиль: минимум данных ──────────────────────────────────────
@pytest.mark.asyncio
async def test_public_profile_no_inn_email_phone():
    """GET /api/users/{id} не раскрывает ИНН, email, телефон."""
    token_a = await _register_direct("pub_a@test.ge", "+995500002001", "carrier")
    # Получаем user_id
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        me = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token_a}"})
    user_id = me.json()["id"]

    # Другой пользователь смотрит публичный профиль
    token_b = await _register_direct("pub_b@test.ge", "+995500002002", "shipper")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/api/users/{user_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 200
    data = r.json()
    assert "inn" not in data, "ИНН не должен быть в публичном профиле"
    assert "email" not in data, "Email не должен быть в публичном профиле"
    assert "phone" not in data, "Телефон не должен быть в публичном профиле"
    assert "hashed_password" not in data, "Хэш пароля не должен раскрываться"
    # Базовые поля должны быть
    assert "company_name" in data
    assert "rating" in data


# ── Контакты: только в сделке ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_contacts_visible_only_to_authorized():
    """
    Незалогиненный пользователь не видит контакты (owner_phone=None).
    Авторизованный: зависит от PRICING_ENABLED (при выключенном — видит все авторизованные).
    Тест проверяет что незалогиненный НИКОГДА не видит контакты.
    """
    token_shipper = await _register_direct("cont_s@test.ge", "+995500003001", "shipper")
    load_id = await _create_load(token_shipper)

    # Незалогиненный смотрит груз
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/api/loads/{load_id}")
    assert r.status_code == 200
    data = r.json()
    # Незалогиненный НИКОГДА не видит контакты
    assert data.get("owner_phone") is None, "Незалогиненный не должен видеть телефон"
    assert data.get("owner_email") is None, "Незалогиненный не должен видеть email"


# ── Soft-deleted пользователь ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_soft_deleted_user_cannot_login():
    """После удаления аккаунта — логин возвращает 401."""
    token = await _register_direct("del_test@test.ge", "+995500004001", "carrier")

    import json as _json
    # Удаляем аккаунт
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.request(
            "DELETE", "/api/users/me",
            content=_json.dumps({"confirmation": "УДАЛИТЬ"}),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
    assert r.status_code == 200

    # Попытка логина со старыми данными
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/login", json={
            "email": "del_test@test.ge",
            "password": "StrongPass99!"
        })
    assert r.status_code == 401, f"Удалённый аккаунт не должен логиниться: {r.status_code}"


@pytest.mark.asyncio
async def test_soft_deleted_token_returns_401():
    """Старый токен удалённого пользователя → 401 на защищённых эндпоинтах."""
    token = await _register_direct("del_tok@test.ge", "+995500004002", "carrier")

    import json as _json
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.request(
            "DELETE", "/api/users/me",
            content=_json.dumps({"confirmation": "УДАЛИТЬ"}),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
    assert r.status_code == 200

    # Старый токен не должен работать
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, f"Старый токен удалённого пользователя должен возвращать 401: {r.status_code}"


# ── Заблокированный пользователь ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_blocked_user_returns_403():
    """Заблокированный пользователь (is_active=False) → 403 на защищённых эндпоинтах."""
    token = await _register_direct("block_cat5@test.ge", "+995500005001", "carrier")

    # Блокируем через admin API
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        me = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    user_id = me.json()["id"]

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(f"/api/users/admin/{user_id}/block?secret=caucashub-admin-2026&reason=test")
    assert r.status_code == 200

    # Запрос от заблокированного
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, f"Заблокированный должен получить 403: {r.status_code}"


# ── SQL-injection ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sql_injection_in_city_filter():
    """Попытка SQL-инъекции в фильтре города не вызывает ошибку (ORM параметризирует)."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/loads/?from_city='; DROP TABLE loads; --")
    # ORM параметризирует — запрос корректно обрабатывается, ничего не ломается
    assert r.status_code == 200, f"SQLi должен обрабатываться корректно: {r.status_code}"
    data = r.json()
    assert "loads" in data


# ── Анонимный пользователь ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unauthenticated_cannot_create_load():
    """Без токена нельзя создать груз → 401 или 403."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=2.73):
        er_module.invalidate_cache()
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/api/loads/", json={
                "from_city": "Тбилиси", "to_city": "Батуми",
                "weight_kg": 500, "truck_type": "tent", "price_gel": 300.0,
            })
    assert r.status_code in (401, 403, 422), f"Без токена: {r.status_code}"


@pytest.mark.asyncio
async def test_unauthenticated_cannot_respond():
    """Без токена нельзя откликнуться → 403."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/responses/load/999", json={"price": 200})
    assert r.status_code in (401, 403, 422), f"Без токена: {r.status_code}"


# ── API не возвращает hashed_password ────────────────────────────────────
@pytest.mark.asyncio
async def test_no_hashed_password_in_me_response():
    """GET /api/users/me не возвращает hashed_password."""
    token = await _register_direct("nohash@test.ge", "+995500006001", "carrier")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert "hashed_password" not in data
    assert "password" not in data


# ── Нельзя принять чужой отклик ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_idor_accept_other_response_returns_403():
    """Пользователь не может принять отклик на чужой груз."""
    token_shipper_a = await _register_direct("acc_s_a@test.ge", "+995500007001", "shipper")
    token_shipper_b = await _register_direct("acc_s_b@test.ge", "+995500007002", "shipper")
    token_carrier = await _register_direct("acc_c@test.ge", "+995500007003", "carrier")

    load_id = await _create_load(token_shipper_a)

    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=2.73):
        er_module.invalidate_cache()
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post(
                f"/api/responses/load/{load_id}",
                json={"price": 300.0},
                headers={"Authorization": f"Bearer {token_carrier}"}
            )
    resp_id = r.json()["response_id"]

    # Shipper B пытается принять отклик на груз Shipper A
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            f"/api/responses/accept/{resp_id}",
            json={},
            headers={"Authorization": f"Bearer {token_shipper_b}"}
        )
    assert r.status_code == 403, f"IDOR: ожидали 403, получили {r.status_code}"
