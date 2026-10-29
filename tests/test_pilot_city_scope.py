"""Pilot city/scope regressions. Every record lives in disposable local SQLite."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import app
from app.database import Base, get_db
from app.models.city import City
from app.models.user import User, UserPlan
from app.models.load import Load, LoadScope
from app.models.transport_offer import TransportOffer
from app.routers.auth import require_user
from app.services.cities_seed import seed_cities
from app.services.city_identity import (CityRegistry, normalized_city, public_route_metadata,
    resolve_publication_city, apply_publication_cities, UI_CITY_REVIEW_REQUIRED)

test_engine = create_async_engine("sqlite+aiosqlite:///./test_pilot_city_scope.db")
Session = async_sessionmaker(test_engine, expire_on_commit=False)

async def override_get_db():
    async with Session() as db:
        yield db

@pytest_asyncio.fixture(autouse=True)
async def fixture_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as db:
        await seed_cities(db)
        user = User(id=901, email="city-pilot@example.test", hashed_password="not-used",
                    company_name="City pilot fixture", plan=UserPlan.pro_plus)
        db.add(user)
        await db.flush()
        tbilisi = (await db.execute(select(City).where(City.name_ru == "Тбилиси"))).scalar_one()
        routes = [
            (1, "Тбилиси", "Батуми", None),
            (2, "Tbilisi", "Batumi", None),
            (3, "თბილისი", "ბათუმი", None),
            (4, "Тбилиси", "Владикавказ", None),
            (5, "Tbilisi", "Vladikavkaz", None),
            (6, "Unverified village", "Батуми", None),
            (7, "Москва", "Сочи", None),
            (8, "Москва", "Батуми", tbilisi.id),  # mismatched legacy ID
            (9, "Гори", "Рустави", None),
            (10, "Gori", "Rustavi", None),
            (11, "გორი", "რუსთავი", None),
        ]
        future = datetime.now(timezone.utc) + timedelta(days=3)
        for number, origin, destination, origin_id in routes:
            common = dict(id=number, user_id=901, from_city=origin, to_city=destination,
                          from_city_id=origin_id, truck_type="tent",
                          created_at=future + timedelta(minutes=number), is_demo=False)
            db.add(TransportOffer(**common, capacity_kg=1000,
                                  available_from=future, status="active"))
            # Deliberately incorrect declared local scope proves country-derived separation.
            db.add(Load(**common, scope=LoadScope.local, weight_kg=1000,
                        load_date=future, status="active", price_gel=100))
        await db.commit()
    async def local_user():
        async with Session() as db:
            return await db.get(User, 901)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_user] = local_user
    with patch("app.services.transport_matcher.notify_transport_subscribers", new=AsyncMock()):
        yield
    app.dependency_overrides.pop(require_user, None)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,collection", [("transport", "offers"), ("loads", "loads")])
@pytest.mark.parametrize("name", ["Тбилиси", "Tbilisi", "თბილისი", "  ТВИЛИСИ_NOT_A_CITY  "])
async def test_tbilisi_aliases_same_local_results(client, endpoint, collection, name):
    response = await client.get(f"/api/{endpoint}/", params={"scope": "local", "from_city": name})
    assert response.status_code == 200, response.text
    expected = set() if name.endswith("  ") else {1, 2, 3}
    assert {row["id"] for row in response.json()[collection]} == expected

@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,collection", [("transport", "offers"), ("loads", "loads")])
@pytest.mark.parametrize("name", ["Гори", "Gori", "გორი"])
async def test_other_city_aliases_same_results(client, endpoint, collection, name):
    response = await client.get(f"/api/{endpoint}/", params={"scope": "local", "from_city": name})
    assert {row["id"] for row in response.json()[collection]} == {9, 10, 11}

@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,collection", [("transport", "offers"), ("loads", "loads")])
async def test_scope_is_country_based_before_pagination(client, endpoint, collection):
    local = (await client.get(f"/api/{endpoint}/", params={"scope": "local", "limit": 2})).json()
    assert local["total"] == 6
    assert len(local[collection]) == 2
    international = (await client.get(f"/api/{endpoint}/", params={"scope": "intl"})).json()
    assert {row["id"] for row in international[collection]} == {4, 5}
    assert all(row["route_scope"] == "intl" for row in international[collection])
    assert all(row.get("scope", "intl") == "intl" for row in international[collection])

@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Тбилиси", "Tbilisi", "თბილისი", "Тби", "Tbi", "თბი"])
async def test_autocomplete_has_one_canonical_identity(client, name):
    response = await client.get("/api/cities/", params={"q": name})
    rows = response.json()["cities"]
    assert len(rows) == 1
    assert rows[0]["canonical_key"] == "ge:tbilisi"
    assert rows[0]["id"] == 1
    assert rows[0]["name_en"] == "Tbilisi"

@pytest.mark.asyncio
async def test_id_key_and_text_search_are_equivalent(client):
    variants = [{"from_city_id": 1}, {"from_city_key": "ge:tbilisi"},
                {"from_city": "თბილისი"}]
    results = [(await client.get("/api/transport/", params={**query, "scope": "local"})).json()
               for query in variants]
    assert all({row["id"] for row in response["offers"]} == {1, 2, 3} for response in results)
    bad = await client.get("/api/transport/", params={"from_city_id": 1, "from_city": "Батуми"})
    assert bad.status_code == 422
    assert (await client.get("/api/loads/", params={"from_city_id": 999999})).status_code == 422

@pytest.mark.asyncio
async def test_public_reads_do_not_backfill_or_guess_countries(client):
    async with Session() as db:
        before = (await db.execute(select(func.count()).select_from(City))).scalar_one()
    for url in ["/api/transport/?scope=local", "/api/transport/?scope=intl",
                "/api/cities/?q=Marneuli", "/api/loads/?scope=local"]:
        assert (await client.get(url)).status_code == 200
    unscoped = (await client.get("/api/transport/")).json()["offers"]
    assert next(row for row in unscoped if row["id"] == 6)["route_scope"] == "unverified"
    assert next(row for row in unscoped if row["id"] == 8)["route_scope"] == "unverified"
    assert next(row for row in unscoped if row["id"] == 7)["route_scope"] == "other"
    async with Session() as db:
        assert (await db.execute(select(func.count()).select_from(City))).scalar_one() == before

@pytest.mark.asyncio
async def test_publication_persists_ids_and_update_clears_stale_identity(client):
    future = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    created = await client.post("/api/transport/", json={
        "from_city": "თბილისი", "from_city_key": "ge:tbilisi",
        "to_city": "Batumi", "truck_type": "tent", "capacity_kg": 1000,
        "available_from": future,
    })
    assert created.status_code == 201, created.text
    offer = created.json()["offer"]
    assert offer["from_city"] == "Тбилиси" and offer["from_city_id"] == 1
    assert offer["to_city_key"] == "ge:batumi" and offer["to_country_iso"] == "GE"
    assert {"Тбилиси", "Tbilisi", "თბილისი"} <= set(offer["from_city_aliases"])
    assert {"Батуми", "Batumi", "ბათუმი"} <= set(offer["to_city_aliases"])
    updated = await client.patch(f"/api/transport/{offer['id']}", json={"to_city": "Vladikavkaz"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["offer"]["to_city_key"] == "ru:vladikavkaz"
    assert updated.json()["offer"]["route_scope"] == "intl"
    async with Session() as db:
        saved = await db.get(TransportOffer, offer["id"])
        assert saved.from_city_id == 1 and saved.to_city_id is not None

@pytest.mark.asyncio
async def test_known_missing_dictionary_city_gets_id_only_during_publication(client):
    future = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    rows = (await client.get("/api/cities/", params={"q": "მარნეული"})).json()["cities"]
    assert rows[0]["canonical_key"] == "ge:marneuli" and rows[0]["id"] is None
    response = await client.post("/api/transport/", json={
        "from_city": "Marneuli", "from_city_key": "ge:marneuli", "to_city": "თბილისი",
        "truck_type": "tent", "capacity_kg": 1000, "available_from": future,
    })
    assert response.status_code == 201, response.text
    assert response.json()["offer"]["from_city_id"] is not None
    rows = (await client.get("/api/cities/", params={"q": "Марнеули"})).json()["cities"]
    assert rows[0]["id"] == response.json()["offer"]["from_city_id"]

def test_unsafe_prefix_country_guess_is_not_used():
    assert normalized_city("г. ТБИЛИСИ, Грузия") == "тбилиси"
    assert public_route_metadata(type("Listing", (), {
        "from_city": "Тбили", "to_city": "Батуми",
        "from_city_id": None, "to_city_id": None})())["route_scope"] == "unverified"


@pytest.mark.asyncio
@pytest.mark.parametrize("key,names", [
    ("ge:batumi", ["Батуми", "Batumi", "ბათუმი"]),
    ("ge:kutaisi", ["Кутаиси", "Kutaisi", "ქუთაისი"]),
    ("ge:rustavi", ["Рустави", "Rustavi", "რუსთავი"]),
    ("ge:poti", ["Поти", "Poti", "ფოთი"]),
])
async def test_other_autocomplete_cities_share_identity(client, key, names):
    results = [(await client.get("/api/cities/", params={"q": name})).json()["cities"]
               for name in names]
    assert all(len(rows) == 1 and rows[0]["canonical_key"] == key for rows in results)
    assert len({rows[0]["id"] for rows in results}) == 1

@pytest.mark.parametrize("country", ["RU", "", "Georgia", None])
def test_conflicting_dictionary_country_is_not_trusted(country):
    record = City(id=101, name_ru="Тбилиси", name_ge="თბილისი", country_iso=country)
    registry = CityRegistry([record])
    assert registry.endpoint("Тбилиси", 101) is None
    assert registry.resolve("Tbilisi").country_iso == "GE"

@pytest.mark.parametrize("module", [
    "app.services.subscription_matcher", "app.services.transport_matcher", "app.services.mari",
])
@pytest.mark.parametrize("left,right", [
    ("თბილისი", "Tbilisi"), ("ბოლნისი", "Bolnisi"), ("Гори", "გორი"),
    ("Батуми", "Batumi"),
])
def test_notifications_and_mari_share_city_identity(module, left, right):
    import importlib
    service = importlib.import_module(module)
    match = getattr(service, "same_city", None) or service._cities_match
    assert match(left, right)
    assert not match("Ахалцихе", "Ахалкалаки")


@pytest.mark.parametrize("key,names,country", [
    ("ge:dmanisi", ("Дманиси", "Dmanisi", "დმანისი"), "GE"),
    ("ge:chakvi", ("Чакви", "Chakvi", "ჩაქვი"), "GE"),
    ("ge:keda", ("Кеда", "Keda", "კედა"), "GE"),
    ("ge:stepantsminda", ("Степанцминда", "Stepantsminda", "სტეფანწმინდა"), "GE"),
    ("tr:bursa", ("Бурса", "Bursa", "ბურსა"), "TR"),
    ("ru:nalchik", ("Нальчик", "Nalchik", "ნალჩიკი"), "RU"),
    ("ua:kyiv", ("Киев", "Kyiv", "კიევი"), "UA"),
])
def test_catalog_covers_previously_missing_real_ui_cities(key, names, country):
    registry = CityRegistry()
    assert all(registry.resolve(name).key == key for name in names)
    assert registry.resolve(names[0]).country_iso == country


def test_every_valid_frontend_city_has_consistent_explicit_identity():
    """Guard against independently maintained UI options disappearing on publish."""
    import re
    from pathlib import Path
    source = (Path(__file__).parents[1] / "frontend/main.js").read_text(encoding="utf-8")
    rows = re.findall(r"\{name:'([^']+)', nameGe:'([^']+)', lat:[\d.]+, lng:[\d.]+, region:'([^']+)'\}",
                      source.split("const CITIES = [", 1)[1].split("\n];", 1)[0])
    registry = CityRegistry()
    assert len(rows) >= 200
    for ru, ge, region in rows:
        if ru.startswith("край ") or ru in UI_CITY_REVIEW_REQUIRED:
            assert registry.resolve(ru) is None
            continue
        identity = registry.resolve(ru)
        assert identity is not None, ru
        assert normalized_city(ge) in identity.aliases, (ru, ge)
        # An explicit key is required when different countries share an alias.
        assert registry.resolve(ge, city_key=identity.key) is identity
        assert registry.resolve(identity.name_en).key == identity.key


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["An unknown village", "Тбили", "ვანი", "край Кахетия"])
async def test_unknown_or_ambiguous_new_publication_is_rejected_without_write(name):
    db = AsyncMock()
    registry = CityRegistry()
    with pytest.raises(ValueError, match="Выберите город из списка"):
        await resolve_publication_city(db, registry, name)
    db.add.assert_not_called()
    db.flush.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Unverified village", "ვანი"])
async def test_unknown_post_returns_422_and_does_not_create_hidden_offer(client, name):
    async with Session() as db:
        before = (await db.execute(select(func.count()).select_from(TransportOffer))).scalar_one()
    future = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    response = await client.post("/api/transport/", json={
        "from_city": name, "to_city": "Тбилиси", "truck_type": "tent",
        "capacity_kg": 1000, "available_from": future,
    })
    assert response.status_code == 422, response.text
    assert "Выберите город из списка" in response.json()["detail"]
    async with Session() as db:
        assert (await db.execute(select(func.count()).select_from(TransportOffer))).scalar_one() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("name,key", [("Dmanisi", "ge:dmanisi"), ("ჩაქვი", "ge:chakvi"), ("კედა", "ge:keda")])
async def test_published_ui_city_has_id_and_is_visible_in_local_catalog(client, name, key):
    future = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    response = await client.post("/api/transport/", json={
        "from_city": name, "from_city_key": key, "to_city": "Tbilisi",
        "truck_type": "tent", "capacity_kg": 1000, "available_from": future,
    })
    assert response.status_code == 201, response.text
    offer = response.json()["offer"]
    assert offer["from_city_id"] is not None and offer["route_scope"] == "local"
    rows = (await client.get("/api/transport/", params={"scope": "local", "from_city_key": key})).json()["offers"]
    assert any(row["id"] == offer["id"] for row in rows)


@pytest.mark.asyncio
async def test_ambiguous_georgian_name_requires_matching_selected_city(client):
    future = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    body = {"from_city": "ვანი", "to_city": "Tbilisi", "truck_type": "tent",
            "capacity_kg": 1000, "available_from": future}
    local = await client.post("/api/transport/", json={**body, "from_city_key": "ge:vani"})
    foreign = await client.post("/api/transport/", json={**body, "from_city_key": "tr:van"})
    assert local.status_code == foreign.status_code == 201
    assert local.json()["offer"]["route_scope"] == "local"
    assert foreign.json()["offer"]["route_scope"] == "intl"
    conflict = await client.post("/api/transport/", json={**body,
        "from_city_key": "tr:van", "from_city_id": local.json()["offer"]["from_city_id"]})
    assert conflict.status_code == 422


@pytest.mark.asyncio
async def test_legacy_unknown_endpoint_can_be_retained_but_not_newly_chosen():
    from types import SimpleNamespace
    record = SimpleNamespace(from_city="Old unknown village", from_city_id=None,
                             to_city="Тбилиси", to_city_id=1)
    async with Session() as db:
        data = {"from_city": "Old unknown village"}
        await apply_publication_cities(db, data, existing=record)
        assert data == {"from_city": "Old unknown village", "from_city_id": None}
        with pytest.raises(ValueError, match="Выберите город из списка"):
            await apply_publication_cities(db, {"from_city": "New unknown village"}, existing=record)


@pytest.mark.asyncio
async def test_new_foreign_domestic_route_is_rejected_instead_of_hidden(client):
    future = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    response = await client.post("/api/transport/", json={
        "from_city": "Moscow", "to_city": "Sochi", "truck_type": "tent",
        "capacity_kg": 1000, "available_from": future,
    })
    assert response.status_code == 422, response.text
    assert "другой страны пока не поддерживается" in response.json()["detail"]
    async with Session() as db:
        assert (await db.execute(select(func.count()).select_from(TransportOffer))).scalar_one() == 11
