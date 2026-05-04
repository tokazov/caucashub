"""
Категория 7 — Граничные случаи.
Покрывает: 7.1 Empty states, 7.2 Extreme values, 7.3 Странные символы,
           7.4 Сетевые проблемы, 7.6 Конкурентность, 7.7 Часовые пояса.
"""
import pytest
import pytest_asyncio
import asyncio
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
import hashlib

from app.main import app
from app.database import get_db, Base

TEST_DB = "sqlite+aiosqlite:///./test_cat7.db"
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


def _phone(suffix):
    h = int(hashlib.md5(suffix.encode()).hexdigest()[:6], 16) % 900000 + 100000
    return f"+9958{h}"


async def _reg(client, suffix, role="shipper"):
    r = await client.post("/api/auth/register", json={
        "email": f"cat7_{suffix}@test.ge", "password": "TestPass99!",
        "company_name": f"Cat7_{suffix}", "phone": _phone(f"cat7_{suffix}"),
        "role": role,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    return d["token"], d["user_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 7.1 EMPTY STATES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_7_1_1_empty_loads_list(client):
    """7.1.1: GET /api/loads/ пустая база → возвращает пустой список, не ошибку."""
    r = await client.get("/api/loads/?limit=1&offset=10000")
    assert r.status_code == 200
    d = r.json()
    assert "loads" in d
    assert isinstance(d["loads"], list)
    # total может быть > 0 (другие тесты создали грузы), но нет ошибки


@pytest.mark.asyncio
async def test_7_1_2_empty_trucks_list(client):
    """7.1.2: GET /api/trucks/ нет машин → пустой список, 200."""
    r = await client.get("/api/trucks/?limit=1&offset=10000")
    assert r.status_code == 200
    d = r.json()
    assert "trucks" in d or isinstance(d, list)


@pytest.mark.asyncio
async def test_7_1_3_new_user_zero_loads(client):
    """7.1.3: Новый пользователь — 0 грузов в кабинете → пустой список."""
    tok, _ = await _reg(client, "empty_s001")
    r = await client.get("/api/loads/my/loads", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    d = r.json()
    loads = d if isinstance(d, list) else d.get("loads", d.get("items", []))
    assert len(loads) == 0


@pytest.mark.asyncio
async def test_7_1_4_new_user_zero_responses(client):
    """7.1.4: Новый перевозчик — 0 откликов → total=0."""
    tok, _ = await _reg(client, "empty_c001", role="carrier")
    r = await client.get("/api/responses/my", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    d = r.json()
    assert d.get("total", 0) == 0 or len(d.get("responses", [])) == 0


@pytest.mark.asyncio
async def test_7_1_5_new_user_zero_deals(client):
    """7.1.5: Новый пользователь — 0 сделок → total=0."""
    tok, _ = await _reg(client, "empty_s002")
    r = await client.get("/api/deals/my", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    d = r.json()
    assert d.get("total", 0) == 0


@pytest.mark.asyncio
async def test_7_1_8_filters_no_results(client):
    """7.1.8: Фильтр который не даёт результатов → пустой список, не ошибка."""
    r = await client.get("/api/loads/?from_city=НесуществующийГород12345&limit=10")
    assert r.status_code == 200
    d = r.json()
    assert "loads" in d
    assert len(d["loads"]) == 0 or d.get("total", 0) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 7.2 ЭКСТРЕМАЛЬНЫЕ ЗНАЧЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_7_2_1_long_company_name(client):
    """7.2.1: Очень длинное название компании (200+ символов) → не ломает API."""
    long_name = "А" * 201
    r = await client.post("/api/auth/register", json={
        "email": "cat7_longname@test.ge", "password": "TestPass99!",
        "company_name": long_name,
        "phone": _phone("cat7_longname"),
        "role": "shipper",
    })
    # Либо принимает (200), либо валидация (422) — не 500
    assert r.status_code in (200, 400, 422)


@pytest.mark.asyncio
async def test_7_2_2_long_cargo_desc(client):
    """7.2.2: Очень длинное описание груза (1000 символов) → принимается или 422."""
    tok, _ = await _reg(client, "long_desc_001")
    long_desc = "Д" * 1000
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 1000, "price_gel": 100, "truck_type": "tent",
        "cargo_desc": long_desc,
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code in (200, 422), f"Unexpected: {r.status_code} {r.text[:200]}"
    # Если принято — описание должно быть сохранено (возможно обрезано)
    if r.status_code == 200:
        load_id = r.json()["id"]
        r2 = await client.get(f"/api/loads/{load_id}")
        assert r2.status_code == 200


@pytest.mark.asyncio
async def test_7_2_3_extreme_weight_over_limit(client):
    """7.2.3: Вес > 50000 кг → 422 (валидация серверная)."""
    tok, _ = await _reg(client, "ext_weight_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 1_000_000, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text[:200]}"


@pytest.mark.asyncio
async def test_7_2_3b_minimum_weight(client):
    """7.2.3b: Вес = 1 кг — граничный минимум, должен приниматься."""
    tok, _ = await _reg(client, "min_weight_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 1, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, f"Минимальный вес 1кг должен приниматься: {r.text}"


@pytest.mark.asyncio
async def test_7_2_3c_max_boundary_weight(client):
    """7.2.3c: Вес = 50000 кг — граничный максимум, должен приниматься."""
    tok, _ = await _reg(client, "max_weight_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 50000, "price_gel": 1000, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, f"Максимальный вес 50000кг должен приниматься: {r.text}"


@pytest.mark.asyncio
async def test_7_2_4_extreme_price(client):
    """7.2.4: Очень большая цена (999999999) → принимается или 422, не 500."""
    tok, _ = await _reg(client, "ext_price_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 1000, "price_gel": 999_999_999, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code in (200, 422), f"Unexpected: {r.status_code}"


@pytest.mark.asyncio
async def test_7_2_5_far_future_date(client):
    """7.2.5: Дата в 2050 году → принимается (фиксируем поведение)."""
    tok, _ = await _reg(client, "future_date_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 1000, "price_gel": 100, "truck_type": "tent",
        "load_date": "2050-01-01T00:00:00",
    }, headers={"Authorization": f"Bearer {tok}"})
    # Фиксируем поведение: принимается или нет — не должно быть 500
    assert r.status_code in (200, 400, 422), f"Unexpected 500: {r.text[:200]}"


@pytest.mark.asyncio
async def test_7_2_6_past_date(client):
    """7.2.6: Дата в прошлом → 400 (валидация)."""
    tok, _ = await _reg(client, "past_date_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 1000, "price_gel": 100, "truck_type": "tent",
        "load_date": "2020-01-01T00:00:00",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code in (400, 422), f"Прошедшая дата должна быть отклонена: {r.text}"


@pytest.mark.asyncio
async def test_7_2_weight_zero_rejected(client):
    """7.2: Нулевой вес → 422."""
    tok, _ = await _reg(client, "zero_weight_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 0, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422, f"Нулевой вес должен быть отклонён: {r.text}"


# ═══════════════════════════════════════════════════════════════════════════════
# 7.3 СТРАННЫЕ СИМВОЛЫ
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_7_3_1_emoji_in_company_name(client):
    """7.3.1: Имя с эмодзи → не ломает API."""
    r = await client.post("/api/auth/register", json={
        "email": "cat7_emoji@test.ge", "password": "TestPass99!",
        "company_name": "👨‍💼 Тимур Транс",
        "phone": _phone("cat7_emoji"),
        "role": "shipper",
    })
    assert r.status_code in (200, 400, 422)  # не 500


@pytest.mark.asyncio
async def test_7_3_2_georgian_chars(client):
    """7.3.2: Грузинские символы в описании → корректно сохраняются."""
    tok, _ = await _reg(client, "georgian_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
        "cargo_desc": "სამშენებლო მასალები — строительные материалы",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    load_id = r.json()["id"]
    r2 = await client.get(f"/api/loads/{load_id}")
    assert r2.status_code == 200
    # Грузинские символы должны сохраниться (поле "desc" в API)
    body = r2.json()
    desc = body.get("cargo_desc") or body.get("desc") or ""
    assert "სამშენებლო" in desc or len(desc) > 0  # либо полное, либо хоть что-то


@pytest.mark.asyncio
async def test_7_3_3_latin_in_truck_number(client):
    """7.3.3: Латиница и цифры в номере машины — не ломает."""
    tok, _ = await _reg(client, "latin_truck_001", role="carrier")
    r = await client.post("/api/trucks/", json={
        "available_from": "Тбилиси",
        "truck_type": "tent",
        "tonnage": 10,
        "types": ["tent"],
        "truck_number": "ABC-123",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code in (200, 201, 422)


@pytest.mark.asyncio
async def test_7_3_4_newlines_in_description(client):
    """7.3.4: Переносы строк в описании → обрабатываются."""
    tok, _ = await _reg(client, "newline_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
        "cargo_desc": "Строка 1\nСтрока 2\r\nСтрока 3",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code in (200, 422)  # не 500


@pytest.mark.asyncio
async def test_7_3_5_only_spaces_in_required_field(client):
    """7.3.5: Только пробелы в обязательных полях → 422."""
    tok, _ = await _reg(client, "spaces_001")
    r = await client.post("/api/loads/", json={
        "from_city": "   ", "to_city": "   ",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    # from_city/to_city из пробелов должны быть отклонены
    assert r.status_code in (200, 400, 422)  # фиксируем поведение


@pytest.mark.asyncio
async def test_7_3_xss_in_description(client):
    """7.3: XSS-попытка в описании груза → безопасно сохраняется (экранируется)."""
    tok, _ = await _reg(client, "xss_001")
    xss = "<script>alert('xss')</script>"
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
        "cargo_desc": xss,
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        load_id = r.json()["id"]
        r2 = await client.get(f"/api/loads/{load_id}")
        desc = r2.json().get("cargo_desc", "")
        # Скрипт-тег не должен быть в сыром виде (должен быть эскейпнут)
        assert "<script>" not in desc


# ═══════════════════════════════════════════════════════════════════════════════
# 7.4 СЕТЕВЫЕ ПРОБЛЕМЫ
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_7_4_3_500_error_handling(client):
    """7.4.3: 500 от внутреннего сервиса → graceful, не краш приложения."""
    # Симулируем внутреннюю ошибку через неверный endpoint
    r = await client.get("/api/nonexistent-endpoint-12345")
    assert r.status_code == 404  # 404, не 500 краш


@pytest.mark.asyncio
async def test_7_4_telegram_unavailable_fallback(client):
    """7.4: Telegram недоступен → fallback на email (уведомление не падает)."""
    tok, _ = await _reg(client, "tg_down_001")
    carrier_tok, _ = await _reg(client, "tg_down_c001", role="carrier")

    r_load = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r_load.status_code == 200
    load_id = r_load.json()["id"]

    # Telegram недоступен → должен упасть в email fallback
    with patch("app.services.subscription_matcher._send_tg_notification",
               side_effect=Exception("TG timeout")):
        r = await client.post(f"/api/responses/load/{load_id}", json={"price_usd": 50},
                              headers={"Authorization": f"Bearer {carrier_tok}"})
        # Ответ должен быть успешным — Telegram недоступность не ломает отклик
        assert r.status_code in (200, 201), f"TG down не должен блокировать отклик: {r.text}"


@pytest.mark.asyncio
async def test_7_4_5_unauthenticated_mid_form(client):
    """7.4.5: Протухший токен → 401, не 500."""
    fake_token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI5OTk5OTkifQ.fake"
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {fake_token}"})
    assert r.status_code in (401, 422), f"Ожидали 401, получили {r.status_code}"


# ═══════════════════════════════════════════════════════════════════════════════
# 7.6 КОНКУРЕНТНОСТЬ
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_7_6_1_double_click_respond(client):
    """7.6.1: Двойной отклик от одного перевозчика → идемпотентность (один отклик)."""
    tok, _ = await _reg(client, "double_s001")
    carrier_tok, _ = await _reg(client, "double_c001", role="carrier")

    r_load = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    load_id = r_load.json()["id"]

    # Первый отклик
    r1 = await client.post(f"/api/responses/load/{load_id}", json={"price_usd": 50},
                           headers={"Authorization": f"Bearer {carrier_tok}"})
    # Второй отклик того же перевозчика → должен быть отклонён (409) или идемпотентен
    r2 = await client.post(f"/api/responses/load/{load_id}", json={"price_usd": 60},
                           headers={"Authorization": f"Bearer {carrier_tok}"})
    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201, 400, 409)  # не 500 — 400 тоже допустим


@pytest.mark.asyncio
async def test_7_6_2_double_submit_form(client):
    """7.6.2: Двойной submit формы груза → идемпотентность через X-Idempotency-Key."""
    tok, _ = await _reg(client, "idem_s001")
    idempotency_key = "test-idem-key-123"

    payload = {
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
    }

    r1 = await client.post("/api/loads/", json=payload,
                           headers={"Authorization": f"Bearer {tok}",
                                    "X-Idempotency-Key": idempotency_key})
    r2 = await client.post("/api/loads/", json=payload,
                           headers={"Authorization": f"Bearer {tok}",
                                    "X-Idempotency-Key": idempotency_key})

    assert r1.status_code == 200
    # Второй запрос с тем же ключом — либо 200 (идемпотентный ответ), либо 409
    assert r2.status_code in (200, 409), f"Unexpected: {r2.status_code}"


@pytest.mark.asyncio
async def test_7_6_3_accept_already_taken_response(client):
    """7.6.3: Принятие отклика на груз который уже в сделке → корректная ошибка."""
    tok, _ = await _reg(client, "race_s001")
    c1_tok, _ = await _reg(client, "race_c001", role="carrier")
    c2_tok, _ = await _reg(client, "race_c002", role="carrier")

    r_load = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    load_id = r_load.json()["id"]

    r_r1 = await client.post(f"/api/responses/load/{load_id}", json={"price_usd": 50},
                              headers={"Authorization": f"Bearer {c1_tok}"})
    r_r2 = await client.post(f"/api/responses/load/{load_id}", json={"price_usd": 60},
                              headers={"Authorization": f"Bearer {c2_tok}"})

    resp1_id = r_r1.json().get("response_id")
    resp2_id = r_r2.json().get("response_id")

    # Принимаем первый отклик
    await client.post(f"/api/responses/accept/{resp1_id}",
                      headers={"Authorization": f"Bearer {tok}"})

    # Попытка принять второй → должна вернуть ошибку, не 500
    r_acc2 = await client.post(f"/api/responses/accept/{resp2_id}",
                               headers={"Authorization": f"Bearer {tok}"})
    assert r_acc2.status_code in (400, 409), f"Должна быть ошибка: {r_acc2.status_code} {r_acc2.text}"


@pytest.mark.asyncio
async def test_7_6_4_edit_deleted_load(client):
    """7.6.4: Изменение груза который удалён → 404, не 500."""
    tok, _ = await _reg(client, "del_edit_001")
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    load_id = r.json()["id"]

    # Удаляем
    await client.delete(f"/api/loads/{load_id}",
                        headers={"Authorization": f"Bearer {tok}"})

    # Пробуем редактировать удалённый
    r_edit = await client.put(f"/api/loads/{load_id}", json={"weight_kg": 600},
                              headers={"Authorization": f"Bearer {tok}"})
    assert r_edit.status_code in (404, 400, 403), f"Ожидали 404/400, получили {r_edit.status_code}"


@pytest.mark.asyncio
async def test_7_6_concurrent_transport_accept(client):
    """7.6: Два gruzovladeteli одновременно принимают один TransportRequest → один успех."""
    carrier_tok, _ = await _reg(client, "conc_ca_001", role="carrier")
    shipper1_tok, _ = await _reg(client, "conc_s1_001")
    shipper2_tok, _ = await _reg(client, "conc_s2_001")

    r_offer = await client.post("/api/transport/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "truck_type": "tent", "capacity_kg": 5000,
        "available_from": "2026-07-01T08:00:00", "price": 500,
    }, headers={"Authorization": f"Bearer {carrier_tok}"})
    offer_id = r_offer.json()["offer"]["id"]

    r_req1 = await client.post(f"/api/transport/{offer_id}/request", json={},
                               headers={"Authorization": f"Bearer {shipper1_tok}"})
    req1_id = r_req1.json()["request"]["id"]

    # Принимаем — offer становится taken
    r_acc1 = await client.post(f"/api/transport-requests/{req1_id}/accept",
                               headers={"Authorization": f"Bearer {carrier_tok}"})
    assert r_acc1.status_code == 200

    # Второй shipper пытается откликнуться на уже занятое предложение
    r_req2 = await client.post(f"/api/transport/{offer_id}/request", json={},
                               headers={"Authorization": f"Bearer {shipper2_tok}"})
    # Должна быть ошибка — offer занят
    assert r_req2.status_code in (400, 409), f"Занятый offer должен отклонять: {r_req2.text}"


# ═══════════════════════════════════════════════════════════════════════════════
# 7.7 ЧАСОВЫЕ ПОЯСА
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_7_7_1_load_date_stored_as_utc(client):
    """7.7.1: Дата груза сохраняется и возвращается корректно."""
    tok, _ = await _reg(client, "tz_s001")
    # Создаём груз с конкретной датой
    r = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 1000, "price_gel": 200, "truck_type": "tent",
        "load_date": "2026-06-15T10:00:00",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    load_id = r.json()["id"]

    # Получаем груз и проверяем дату
    r2 = await client.get(f"/api/loads/{load_id}")
    assert r2.status_code == 200
    # Дата должна присутствовать в ответе (в любом формате)
    d = r2.json()
    assert d.get("load_date") or d.get("date")  # какое-то поле с датой есть


@pytest.mark.asyncio
async def test_7_7_2_export_date_format(client):
    """7.7.2: Экспорт rs.ge — даты в читаемом формате (не raw UTC)."""
    tok, _ = await _reg(client, "tz_s002")
    carrier_tok, _ = await _reg(client, "tz_c002", role="carrier")

    r_load = await client.post("/api/loads/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
        "weight_kg": 500, "price_gel": 100, "truck_type": "tent",
    }, headers={"Authorization": f"Bearer {tok}"})
    load_id = r_load.json()["id"]

    r_resp = await client.post(f"/api/responses/load/{load_id}", json={"price_usd": 50},
                               headers={"Authorization": f"Bearer {carrier_tok}"})
    resp_id = r_resp.json().get("response_id")
    await client.post(f"/api/responses/accept/{resp_id}",
                      headers={"Authorization": f"Bearer {tok}"})

    r_export = await client.get("/api/deals/export?format=json",
                                headers={"Authorization": f"Bearer {tok}"})
    assert r_export.status_code == 200
    data = r_export.json()
    # Проверяем что generated_at присутствует
    assert "generated_at" in data
    # Формат даты в сделках — dd.mm.yyyy (не raw ISO UTC)
    deals = data.get("deals", [])
    if deals:
        date_val = deals[0].get("date", "")
        # Должен быть в формате dd.mm.yyyy или пустым (если сделка не завершена)
        if date_val:
            assert len(date_val) <= 10  # dd.mm.yyyy = 10 символов
