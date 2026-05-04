"""
Тесты геокодера (ADR-015).
Проверяют маппинг, транслитерацию, fallback при пустом ключе.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.geo_mapping import GEO_MAPPING_RU_EN
from app.services.geocoder import _transliterate_ru, search_city


# ── Маппинг словаря ──────────────────────────────────────────────────────────

def test_mapping_natakhtari():
    """Натахтари (строчные) → Natakhtari"""
    assert GEO_MAPPING_RU_EN.get("натахтари") == "Natakhtari"


def test_mapping_batumi():
    """батуми (строчные) → Batumi"""
    assert GEO_MAPPING_RU_EN.get("батуми") == "Batumi"


def test_mapping_tbilisi():
    assert GEO_MAPPING_RU_EN.get("тбилиси") == "Tbilisi"


# ── Транслитерация ───────────────────────────────────────────────────────────

def test_transliterate_natakhtari():
    assert _transliterate_ru("натахтари") == "Natakhtari"


def test_transliterate_batumi_lower():
    """lowercase батуми должен находиться"""
    assert _transliterate_ru("батуми") == "Batumi"


def test_transliterate_batumi_mixed():
    """Батуми (первая заглавная) → тоже находит"""
    assert _transliterate_ru("Батуми") == "Batumi"


def test_transliterate_unknown():
    """Неизвестный город → возвращает исходный запрос"""
    assert _transliterate_ru("Неизвестный город") == "Неизвестный город"


# ── search_city: пустой LOCATIONIQ_KEY → [] без db ───────────────────────────

@pytest.mark.asyncio
async def test_search_city_no_key_no_db():
    """Пустой ключ + нет db → возвращает []"""
    with patch("app.services.geocoder.LOCATIONIQ_KEY", ""):
        result = await search_city("батуми", lang="ru", limit=5, db=None)
    assert result == []


# ── search_city: пустой ключ + db → fallback в БД ───────────────────────────

@pytest.mark.asyncio
async def test_search_city_no_key_with_db_fallback():
    """Пустой ключ + db → возвращает результаты из _search_city_db"""
    # Мок объекта города
    mock_city = MagicMock()
    mock_city.id = 1
    mock_city.name_ru = "Батуми"
    mock_city.name_ge = "ბათუმი"
    mock_city.lat = 41.6168
    mock_city.lon = 41.6367

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_city]

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    with patch("app.services.geocoder.LOCATIONIQ_KEY", ""):
        result = await search_city("батуми", lang="ru", limit=5, db=mock_db)

    assert len(result) >= 1
    assert result[0]["name_ru"] == "Батуми"
    assert result[0]["source"] == "db_fallback"


# ── search_city: с ключом → вызов LocationIQ API ─────────────────────────────

@pytest.mark.asyncio
async def test_search_city_with_key_batumi():
    """С ключом → транслит батуми→Batumi → запрос к LocationIQ"""
    fake_response = [
        {
            "lat": "41.6168",
            "lon": "41.6367",
            "display_name": "Batumi, Adjara, Georgia",
            "type": "city",
            "osm_id": "12345",
            "address": {"city": "Batumi"},
        }
    ]

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = fake_response

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.geocoder.LOCATIONIQ_KEY", "pk.testkey123"):
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await search_city("батуми", lang="ru", limit=5)

    assert len(result) == 1
    assert result[0]["name_ru"] == "батуми"
    assert result[0]["name_en"] == "Batumi"
    assert result[0]["lat"] == 41.6168
    assert result[0]["source"] == "locationiq"


@pytest.mark.asyncio
async def test_search_city_natakhtari_not_pub():
    """Натахтари → транслит к Natakhtari → не паб, а город"""
    fake_response = [
        {
            "lat": "41.8469",
            "lon": "44.6699",
            "display_name": "Natakhtari, Mtskheta-Mtianeti, Georgia",
            "type": "village",
            "osm_id": "67890",
            "address": {"village": "Natakhtari"},
        }
    ]

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = fake_response

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.geocoder.LOCATIONIQ_KEY", "pk.testkey123"):
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await search_city("натахтари", lang="ru", limit=5)

    assert len(result) == 1
    # Должен вернуть Natakhtari (village), не что-то другое
    assert result[0]["name_local"] == "Natakhtari"
    # Убедимся что это не паб (type != amenity)
    assert result[0]["type"] != "pub"
    assert result[0]["type"] in ("village", "city", "town", "suburb", "")
