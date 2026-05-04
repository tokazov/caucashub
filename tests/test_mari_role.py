"""
Тесты ADR-016 Этап 6 — Мари по роли пользователя.

Покрывает:
- carrier: фраза «Тент Тбилиси-Батуми 5т 800₾» → TransportOffer (НЕ Load)
- shipper: та же фраза → Load
- both: Мари задаёт уточняющий вопрос (requires_clarification=true)
- Мусорный ввод → graceful ответ (нет краша)
- Незалогиненный (user_role=None) → работает без ошибки
- DispatcherMessage содержит user_role поле
"""
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
import json

from app.main import app
from app.database import get_db, Base

TEST_DB = "sqlite+aiosqlite:///./test_mari_role.db"
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


CARRIER_TEXT = "Тент Тбилиси-Батуми завтра 5т 800₾"
SHIPPER_TEXT = "Тент Тбилиси-Батуми завтра 5т 800₾"  # та же фраза!
GARBAGE_TEXT = "хыыы ??? ##!@! непонятный текст 🤔"


# ── parse-load endpoint тесты ────────────────────────────────────────────────

def _mock_gemini_carrier_response():
    """Мок ответа Gemini для carrier — TransportOffer."""
    m = MagicMock()
    m.text = json.dumps({
        "object_type": "transport_offer",
        "from_city": "Тбилиси",
        "to_city": "Батуми",
        "truck_type": "tent",
        "capacity_kg": 5000,
        "available_from": "завтра",
        "price": 800,
        "notes": None,
    })
    return m


def _mock_gemini_shipper_response():
    """Мок ответа Gemini для shipper — Load."""
    m = MagicMock()
    m.text = json.dumps({
        "object_type": "load",
        "from_city": "Тбилиси",
        "to_city": "Батуми",
        "weight_kg": 5000,
        "truck_type": "tent",
        "load_date": "завтра",
        "price_gel": 800,
        "cargo_desc": None,
    })
    return m


def _mock_gemini_both_response():
    """Мок ответа Gemini для both — requires_clarification."""
    m = MagicMock()
    m.text = json.dumps({
        "requires_clarification": True,
        "question": "Вы хотите разместить груз или предложить транспорт?",
        "as_load": {"object_type": "load", "from_city": "Тбилиси", "to_city": "Батуми"},
        "as_transport_offer": {"object_type": "transport_offer", "from_city": "Тбилиси", "to_city": "Батуми"},
    })
    return m


def _mock_gemini_garbage():
    """Мок ответа на мусорный ввод."""
    m = MagicMock()
    m.text = json.dumps({
        "object_type": "load",
        "from_city": None,
        "to_city": None,
        "weight_kg": None,
        "truck_type": None,
        "load_date": None,
        "cargo_desc": "Непонятный текст",
    })
    return m


@pytest.mark.asyncio
async def test_carrier_parses_as_transport_offer(client):
    """carrier + фраза → object_type=transport_offer."""
    with patch("app.routers.ai.model") as mock_model:
        mock_model.generate_content.return_value = _mock_gemini_carrier_response()
        r = await client.post(
            "/api/ai/parse-load",
            params={"text": CARRIER_TEXT, "user_role": "carrier"}
        )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["user_role"] == "carrier"
    assert d["parsed"]["object_type"] == "transport_offer"
    assert d["parsed"]["from_city"] == "Тбилиси"
    assert d["parsed"]["capacity_kg"] == 5000


@pytest.mark.asyncio
async def test_shipper_parses_as_load(client):
    """shipper + та же фраза → object_type=load."""
    with patch("app.routers.ai.model") as mock_model:
        mock_model.generate_content.return_value = _mock_gemini_shipper_response()
        r = await client.post(
            "/api/ai/parse-load",
            params={"text": SHIPPER_TEXT, "user_role": "shipper"}
        )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["user_role"] == "shipper"
    assert d["parsed"]["object_type"] == "load"
    assert d["parsed"]["from_city"] == "Тбилиси"
    assert d["parsed"]["weight_kg"] == 5000


@pytest.mark.asyncio
async def test_both_returns_clarification(client):
    """both → requires_clarification=True, есть оба варианта."""
    with patch("app.routers.ai.model") as mock_model:
        mock_model.generate_content.return_value = _mock_gemini_both_response()
        r = await client.post(
            "/api/ai/parse-load",
            params={"text": CARRIER_TEXT, "user_role": "both"}
        )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["user_role"] == "both"
    assert d["parsed"]["requires_clarification"] is True
    assert "question" in d["parsed"]
    assert "as_load" in d["parsed"]
    assert "as_transport_offer" in d["parsed"]


@pytest.mark.asyncio
async def test_garbage_input_graceful(client):
    """Мусорный ввод — нет краша, ответ содержит parsed."""
    with patch("app.routers.ai.model") as mock_model:
        mock_model.generate_content.return_value = _mock_gemini_garbage()
        r = await client.post(
            "/api/ai/parse-load",
            params={"text": GARBAGE_TEXT, "user_role": "shipper"}
        )
    assert r.status_code == 200, r.text
    d = r.json()
    # Нет краша — ответ есть
    assert "parsed" in d
    # Мусорный ввод → поля null, но нет Exception
    assert d["parsed"]["from_city"] is None


@pytest.mark.asyncio
async def test_no_role_still_works(client):
    """Без роли (user_role=None/не передан) — работает без ошибки."""
    with patch("app.routers.ai.model") as mock_model:
        mock_model.generate_content.return_value = _mock_gemini_shipper_response()
        r = await client.post(
            "/api/ai/parse-load",
            params={"text": "Тбилиси Батуми 5т"}
        )
    assert r.status_code == 200, r.text
    assert "parsed" in r.json()


# ── DispatcherMessage schema тесты ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatcher_accepts_user_role(client):
    """DispatcherMessage принимает user_role поле."""
    with patch("app.routers.ai.model") as mock_model:
        m = MagicMock()
        m.text = json.dumps({
            "reply": "Привет, чем помочь?",
            "state": {"from": None, "to": None, "role": "carrier",
                      "ready_to_search": False, "ready_to_post": False,
                      "ready_to_post_transport": False, "awaiting_role_clarification": False},
            "search_filters": None,
            "action": None,
        })
        mock_model.generate_content.return_value = m
        r = await client.post("/api/ai/dispatcher", json={
            "message": "Привет",
            "user_role": "carrier",
            "state": {},
            "history": [],
        })
    assert r.status_code == 200, r.text
    d = r.json()
    assert "reply" in d


@pytest.mark.asyncio
async def test_dispatcher_both_role_asks_clarification(client):
    """dispatcher с role=both возвращает уточняющий вопрос."""
    with patch("app.routers.ai.model") as mock_model:
        m = MagicMock()
        m.text = json.dumps({
            "reply": "Вы хотите разместить груз или предложить транспорт?",
            "state": {"from": "Тбилиси", "to": "Батуми", "role": "both",
                      "ready_to_search": False, "ready_to_post": False,
                      "ready_to_post_transport": False, "awaiting_role_clarification": True},
            "search_filters": None,
            "action": None,
        })
        mock_model.generate_content.return_value = m
        r = await client.post("/api/ai/dispatcher", json={
            "message": "Тент Тбилиси-Батуми завтра 5т 800₾",
            "user_role": "both",
            "state": {},
            "history": [],
        })
    assert r.status_code == 200
    d = r.json()
    state = d.get("state", {})
    # Ожидаем уточняющий вопрос
    assert state.get("awaiting_role_clarification") is True or "?" in d.get("reply", "")
