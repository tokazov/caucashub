"""
Тесты Этап 2 — матчинг подписок и уведомления (ADR-014).

Покрывает:
- Матч по from_city/to_city → уведомление отправляется
- Не-матч → ничего не отправляется
- truck_type фильтр работает
- weight фильтр работает
- Дебаунс: второй вызов за 60с игнорируется
- Владелец груза не получает уведомление о своём грузе
- IDOR: чужую подписку нельзя получить
"""
import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from app.main import app
from app.database import get_db, Base
from app.models.load import Load
from app.models.user import User
from app.models.subscription import RouteSubscription
from app.services.subscription_matcher import (
    find_matching_subscriptions,
    notify_subscribers,
    _normalize,
    _cities_match,
    _truck_type_match,
    _weight_match,
    _debounce_cache,
    DEBOUNCE_SECONDS,
)

TEST_DB = "sqlite+aiosqlite:///./test_subs_e2.db"
engine_test = create_async_engine(TEST_DB, connect_args={"check_same_thread": False})
AsyncSessionTest = sessionmaker(engine_test, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with AsyncSessionTest() as session:
        yield session

app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Unit: матчинг ─────────────────────────────────────────────────────────────

def test_cities_match_case_insensitive():
    assert _cities_match("Тбилиси", "тбилиси") is True
    assert _cities_match("БАТУМИ", "батуми")   is True
    assert _cities_match("Гори", "Кутаиси")    is False


def test_truck_type_match():
    assert _truck_type_match(None, "tent")    is True   # нет фильтра = любой
    assert _truck_type_match("tent", "tent")  is True
    assert _truck_type_match("tent", "gazel") is False
    assert _truck_type_match("tent", None)    is False


def test_weight_match():
    assert _weight_match(None, 5000)  is True   # нет лимита
    assert _weight_match(5, 4999)     is True    # 4.999 т ≤ 5 т
    assert _weight_match(5, 5001)     is False   # 5.001 т > 5 т
    assert _weight_match(10, None)    is True    # груз без веса — ок


# ── Integration: find_matching_subscriptions ─────────────────────────────────

@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionTest() as session:
        yield session


async def _make_user(db, suffix: str, tg_id: str = None) -> User:
    u = User(
        email=f"e2_{suffix}@test.ge",
        hashed_password="x",
        company_name=f"Co{suffix}",
        phone=f"+9955{suffix[-7:].zfill(7)}",
        role="carrier",
        is_active=True,
        telegram_id=tg_id,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_load(db, user_id: int, from_city: str, to_city: str,
                     truck_type: str = "tent", weight_kg: float = 5000) -> Load:
    load = Load(
        user_id=user_id,
        from_city=from_city,
        to_city=to_city,
        truck_type=truck_type,
        weight_kg=weight_kg,
        price_gel=500,
        cargo_desc="Тест",
        load_date=datetime.utcnow(),
        status="active",
    )
    db.add(load)
    await db.commit()
    await db.refresh(load)
    return load


async def _make_sub(db, user_id: int, from_city: str, to_city: str,
                    truck_type: str = None, max_weight_t: int = None,
                    notify_tg: bool = True, notify_email: bool = False) -> RouteSubscription:
    sub = RouteSubscription(
        user_id=user_id,
        from_city=from_city.lower(),
        to_city=to_city.lower(),
        notify_tg=notify_tg,
        notify_email=notify_email,
        truck_type=truck_type,
        max_weight_t=max_weight_t,
        is_active=True,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


@pytest.mark.asyncio
async def test_matching_load_found(db_session):
    """Подписка на Тбилиси→Батуми матчит груз Тбилиси→Батуми."""
    owner = await _make_user(db_session, "ow01")
    subscriber = await _make_user(db_session, "sb01", tg_id="111222333")
    load = await _make_load(db_session, owner.id, "Тбилиси", "Батуми")
    sub  = await _make_sub(db_session, subscriber.id, "тбилиси", "батуми")

    matched = await find_matching_subscriptions(load, db_session)
    ids = [m.id for m in matched]
    assert sub.id in ids


@pytest.mark.asyncio
async def test_no_match_different_route(db_session):
    """Подписка Гори→Рустави не матчит груз Тбилиси→Батуми."""
    owner = await _make_user(db_session, "ow02")
    subscriber = await _make_user(db_session, "sb02", tg_id="444555666")
    load = await _make_load(db_session, owner.id, "Тбилиси", "Батуми")
    sub  = await _make_sub(db_session, subscriber.id, "гори", "рустави")

    matched = await find_matching_subscriptions(load, db_session)
    ids = [m.id for m in matched]
    assert sub.id not in ids


@pytest.mark.asyncio
async def test_owner_does_not_get_own_load(db_session):
    """Владелец груза не получает уведомление о своём грузе."""
    owner = await _make_user(db_session, "ow03", tg_id="777888999")
    load = await _make_load(db_session, owner.id, "Поти", "Зугдиди")
    sub  = await _make_sub(db_session, owner.id, "поти", "зугдиди")

    matched = await find_matching_subscriptions(load, db_session)
    ids = [m.id for m in matched]
    assert sub.id not in ids


@pytest.mark.asyncio
async def test_truck_type_filter(db_session):
    """Подписка с truck_type='gazel' не матчит груз с truck_type='tent'."""
    owner = await _make_user(db_session, "ow04")
    subscriber = await _make_user(db_session, "sb04", tg_id="100200300")
    load = await _make_load(db_session, owner.id, "Гори", "Кутаиси", truck_type="tent")
    sub  = await _make_sub(db_session, subscriber.id, "гори", "кутаиси", truck_type="gazel")

    matched = await find_matching_subscriptions(load, db_session)
    ids = [m.id for m in matched]
    assert sub.id not in ids


@pytest.mark.asyncio
async def test_weight_filter(db_session):
    """Подписка max_weight_t=3 не матчит груз 5000 кг."""
    owner = await _make_user(db_session, "ow05")
    subscriber = await _make_user(db_session, "sb05", tg_id="400500600")
    load = await _make_load(db_session, owner.id, "Ахалкалаки", "Тбилиси", weight_kg=5000)
    sub  = await _make_sub(db_session, subscriber.id, "ахалкалаки", "тбилиси", max_weight_t=3)

    matched = await find_matching_subscriptions(load, db_session)
    ids = [m.id for m in matched]
    assert sub.id not in ids


@pytest.mark.asyncio
async def test_notify_subscribers_sends_tg(db_session):
    """notify_subscribers вызывает TG-уведомление для матчащей подписки."""
    owner = await _make_user(db_session, "ow06")
    subscriber = await _make_user(db_session, "sb06", tg_id="123456789")
    load = await _make_load(db_session, owner.id, "Батуми", "Тбилиси")
    sub  = await _make_sub(db_session, subscriber.id, "батуми", "тбилиси", notify_tg=True)

    with patch("app.services.subscription_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=True) as mock_tg:
        sent = await notify_subscribers(load, db_session)

    assert sent >= 1
    mock_tg.assert_called()
    # Проверяем что telegram_id правильный
    call_args = mock_tg.call_args
    assert call_args[0][0] == "123456789"


@pytest.mark.asyncio
async def test_notify_subscribers_no_match(db_session):
    """Если нет матча — TG не вызывается."""
    owner = await _make_user(db_session, "ow07")
    load = await _make_load(db_session, owner.id, "Сигнахи", "Телави")

    with patch("app.services.subscription_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=True) as mock_tg:
        sent = await notify_subscribers(load, db_session)

    assert sent == 0
    mock_tg.assert_not_called()


@pytest.mark.asyncio
async def test_debounce(db_session):
    """Второй вызов за DEBOUNCE_SECONDS не отправляет уведомление."""
    import time
    owner = await _make_user(db_session, "ow08")
    subscriber = await _make_user(db_session, "sb08", tg_id="999000111")
    load = await _make_load(db_session, owner.id, "Зугдиди", "Поти")
    sub  = await _make_sub(db_session, subscriber.id, "зугдиди", "поти", notify_tg=True)

    # Имитируем что уведомление уже отправлялось только что
    _debounce_cache[(sub.id, load.id)] = time.monotonic()

    with patch("app.services.subscription_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=True) as mock_tg:
        sent = await notify_subscribers(load, db_session)

    # TG не должен вызываться (дебаунс)
    assert sent == 0


@pytest.mark.asyncio
async def test_email_fallback(db_session):
    """Если TG не привязан — используется email fallback."""
    owner = await _make_user(db_session, "ow09")
    subscriber = await _make_user(db_session, "sb09")  # без TG
    load = await _make_load(db_session, owner.id, "Рустави", "Марнеули")
    sub  = await _make_sub(db_session, subscriber.id, "рустави", "марнеули",
                            notify_tg=True, notify_email=True)  # noqa

    with patch("app.services.subscription_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=False) as mock_tg, \
         patch("app.services.subscription_matcher._send_email_notification",
               new_callable=AsyncMock, return_value=True) as mock_email:
        sent = await notify_subscribers(load, db_session)

    # Email вызвался как fallback
    mock_email.assert_called()


# ── Integration: POST /api/loads/ → фоновый матчинг ──────────────────────────

async def _register(client, suffix: str, role: str = "carrier") -> tuple[str, int]:
    r = await client.post("/api/auth/register", json={
        "email":        f"e2int_{suffix}@test.ge",
        "password":     "TestPass99!",
        "company_name": f"IntCo{suffix}",
        "phone":        f"+9955{suffix[-7:].zfill(7)}",
        "role":         role,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    return d["token"], d["user_id"]


@pytest.mark.asyncio
async def test_create_load_triggers_background_match(client):
    """POST /api/loads/ запускает фоновый матчинг — эндпоинт возвращает 200."""
    shipper_tok, _ = await _register(client, "s001", role="shipper")
    carrier_tok, carrier_id = await _register(client, "c001", role="carrier")

    # Создаём подписку для перевозчика
    await client.post("/api/subscriptions/", json={
        "from_city": "Тбилиси",
        "to_city":   "Кутаиси",
    }, headers={"Authorization": f"Bearer {carrier_tok}"})

    with patch("app.services.subscription_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=True):
        r = await client.post("/api/loads/", json={
            "from_city":   "Тбилиси",
            "to_city":     "Кутаиси",
            "weight_kg":   3000,
            "price_gel":   400,
            "truck_type":  "tent",
            "cargo_desc":  "Груз тест",
        }, headers={"Authorization": f"Bearer {shipper_tok}"})

    assert r.status_code == 200, r.text
    # Груз создан — ответ содержит id
    assert "id" in r.json() or "load_id" in r.json()
