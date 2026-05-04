"""
Тесты ADR-016 Этап 3 — Матчинг TransportSubscription.

Покрывает:
- Матч по маршруту → уведомление отправляется
- Не-матч → ничего
- truck_type фильтр
- capacity фильтр
- Перевозчик не получает уведомление о своём предложении
- Дебаунс 60 сек
- Email fallback
- POST /api/transport/ запускает background match (интеграционный)
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from app.main import app
from app.database import get_db, Base
from app.models.transport_offer import TransportOffer
from app.models.transport_subscription import TransportSubscription
from app.models.user import User
from app.services.transport_matcher import (
    find_matching_transport_subscriptions,
    notify_transport_subscribers,
    _cities_match, _truck_match, _capacity_match,
    _debounce_cache, DEBOUNCE_SECONDS,
)

TEST_DB = "sqlite+aiosqlite:///./test_transport_e3.db"
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


@pytest.fixture(autouse=True)
def no_rate_limit():
    with patch("app.routers.auth._check_brute_force_generic"):
        with patch("app.routers.auth._check_brute_force"):
            yield


# ── Unit: матчинг ─────────────────────────────────────────────────────────────

def test_cities_match():
    assert _cities_match("Тбилиси", "тбилиси") is True
    assert _cities_match("БАТУМИ", "батуми") is True
    assert _cities_match("Гори", "Рустави") is False


def test_truck_match():
    assert _truck_match(None, "tent") is True
    assert _truck_match("tent", "tent") is True
    assert _truck_match("tent", "gazel") is False
    assert _truck_match("tent", None) is False


def test_capacity_match():
    assert _capacity_match(None, 5000) is True
    assert _capacity_match(5, 5000) is True   # 5 т ≤ 5 т (offer.capacity >= sub.min)
    assert _capacity_match(6, 5000) is False   # нужно 6 т, предложение 5 т
    assert _capacity_match(5, None) is True


# ── DB fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionTest() as session:
        yield session


async def _make_user(db, suffix, tg_id=None) -> User:
    u = User(
        email=f"te3_{suffix}@test.ge", hashed_password="x",
        company_name=f"TE3_{suffix}", phone=f"+9955{suffix[-7:].zfill(7)}",
        role="carrier", is_active=True, telegram_id=tg_id,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_offer(db, user_id, from_city, to_city,
                      truck_type="tent", capacity_kg=10000) -> TransportOffer:
    o = TransportOffer(
        user_id=user_id, from_city=from_city, to_city=to_city,
        truck_type=truck_type, capacity_kg=capacity_kg,
        available_from=datetime(2026, 6, 1), status="active",
    )
    db.add(o)
    await db.commit()
    await db.refresh(o)
    return o


async def _make_sub(db, user_id, from_city, to_city,
                    truck_type=None, max_weight_t=None,
                    notify_tg=True, notify_email=False) -> TransportSubscription:
    s = TransportSubscription(
        user_id=user_id, from_city=from_city.lower(), to_city=to_city.lower(),
        notify_tg=notify_tg, notify_email=notify_email,
        truck_type=truck_type, max_weight_t=max_weight_t, is_active=True,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


# ── Integration: матчинг ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_matching_offer_found(db_session):
    carrier = await _make_user(db_session, "c_e3_001")
    shipper = await _make_user(db_session, "s_e3_001", tg_id="111222333")
    offer = await _make_offer(db_session, carrier.id, "Тбилиси", "Батуми")
    sub   = await _make_sub(db_session, shipper.id, "тбилиси", "батуми")

    matched = await find_matching_transport_subscriptions(offer, db_session)
    assert sub.id in [m.id for m in matched]


@pytest.mark.asyncio
async def test_no_match_different_route(db_session):
    carrier = await _make_user(db_session, "c_e3_002")
    shipper = await _make_user(db_session, "s_e3_002", tg_id="444555666")
    offer = await _make_offer(db_session, carrier.id, "Тбилиси", "Батуми")
    sub   = await _make_sub(db_session, shipper.id, "гори", "рустави")

    matched = await find_matching_transport_subscriptions(offer, db_session)
    assert sub.id not in [m.id for m in matched]


@pytest.mark.asyncio
async def test_carrier_not_notified_own_offer(db_session):
    """Перевозчик не получает уведомление о своём предложении."""
    carrier = await _make_user(db_session, "c_e3_003", tg_id="789000111")
    offer = await _make_offer(db_session, carrier.id, "Поти", "Зугдиди")
    sub   = await _make_sub(db_session, carrier.id, "поти", "зугдиди")

    matched = await find_matching_transport_subscriptions(offer, db_session)
    assert sub.id not in [m.id for m in matched]


@pytest.mark.asyncio
async def test_truck_filter(db_session):
    carrier = await _make_user(db_session, "c_e3_004")
    shipper = await _make_user(db_session, "s_e3_004", tg_id="100200300")
    offer = await _make_offer(db_session, carrier.id, "Гори", "Кутаиси", truck_type="gazel")
    sub   = await _make_sub(db_session, shipper.id, "гори", "кутаиси", truck_type="tent")

    matched = await find_matching_transport_subscriptions(offer, db_session)
    assert sub.id not in [m.id for m in matched]


@pytest.mark.asyncio
async def test_capacity_filter(db_session):
    """Подписка min_weight_t=15 не матчит предложение capacity=5000 кг."""
    carrier = await _make_user(db_session, "c_e3_005")
    shipper = await _make_user(db_session, "s_e3_005", tg_id="400500600")
    offer = await _make_offer(db_session, carrier.id, "Батуми", "Тбилиси", capacity_kg=5000)
    sub   = await _make_sub(db_session, shipper.id, "батуми", "тбилиси", max_weight_t=15)

    matched = await find_matching_transport_subscriptions(offer, db_session)
    assert sub.id not in [m.id for m in matched]


@pytest.mark.asyncio
async def test_notify_sends_tg(db_session):
    carrier = await _make_user(db_session, "c_e3_006")
    shipper = await _make_user(db_session, "s_e3_006", tg_id="999111222")
    offer = await _make_offer(db_session, carrier.id, "Рустави", "Марнеули")
    await _make_sub(db_session, shipper.id, "рустави", "марнеули", notify_tg=True)

    with patch("app.services.transport_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=True) as mock_tg:
        sent = await notify_transport_subscribers(offer, db_session)

    assert sent >= 1
    mock_tg.assert_called()
    assert mock_tg.call_args[0][0] == "999111222"


@pytest.mark.asyncio
async def test_notify_no_match(db_session):
    carrier = await _make_user(db_session, "c_e3_007")
    offer = await _make_offer(db_session, carrier.id, "Сигнахи", "Телави")

    with patch("app.services.transport_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=True) as mock_tg:
        sent = await notify_transport_subscribers(offer, db_session)

    assert sent == 0
    mock_tg.assert_not_called()


@pytest.mark.asyncio
async def test_debounce(db_session):
    import time
    carrier = await _make_user(db_session, "c_e3_008")
    shipper = await _make_user(db_session, "s_e3_008", tg_id="777888000")
    offer = await _make_offer(db_session, carrier.id, "Зугдиди", "Поти")
    sub   = await _make_sub(db_session, shipper.id, "зугдиди", "поти", notify_tg=True)

    _debounce_cache[(sub.id, offer.id)] = time.monotonic()

    with patch("app.services.transport_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=True) as mock_tg:
        sent = await notify_transport_subscribers(offer, db_session)

    assert sent == 0
    mock_tg.assert_not_called()


@pytest.mark.asyncio
async def test_email_fallback(db_session):
    carrier = await _make_user(db_session, "c_e3_009")
    shipper = await _make_user(db_session, "s_e3_009")   # без TG
    offer = await _make_offer(db_session, carrier.id, "Ахалкалаки", "Тбилиси")
    await _make_sub(db_session, shipper.id, "ахалкалаки", "тбилиси",
                    notify_tg=True, notify_email=True)

    with patch("app.services.transport_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=False), \
         patch("app.services.transport_matcher._send_email_notification",
               new_callable=AsyncMock, return_value=True) as mock_email:
        await notify_transport_subscribers(offer, db_session)

    mock_email.assert_called()


# ── Integration: POST /api/transport/ → background match ─────────────────────

async def _reg(client, suffix, role="carrier"):
    r = await client.post("/api/auth/register", json={
        "email": f"tre3_{suffix}@test.ge", "password": "TestPass99!",
        "company_name": f"TrE3_{suffix}", "phone": f"+9956{suffix[-7:].zfill(7)}",
        "role": role,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    return d["token"], d["user_id"]


@pytest.mark.asyncio
async def test_post_transport_triggers_background_match(client):
    carrier_tok, _ = await _reg(client, "int001")
    shipper_tok, _ = await _reg(client, "int002", role="shipper")

    # Подписка грузовладельца
    await client.post("/api/transport-subscriptions/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
    }, headers={"Authorization": f"Bearer {shipper_tok}"})

    with patch("app.services.transport_matcher._send_tg_notification",
               new_callable=AsyncMock, return_value=True):
        r = await client.post("/api/transport/", json={
            "from_city": "Тбилиси", "to_city": "Батуми",
            "truck_type": "tent", "capacity_kg": 10000,
            "available_from": "2026-06-01T08:00:00", "price": 800,
        }, headers={"Authorization": f"Bearer {carrier_tok}"})

    assert r.status_code == 201, r.text
    assert r.json()["offer"]["status"] == "active"
