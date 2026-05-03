"""
Обёртка над Yandex Geocoder API (ADR-007Б).

⚠️ ЗАГЛУШКА — Яндекс API-ключ ожидается от Тимура в течение 3-7 дней.
Все методы возвращают пустые результаты пока ключ не установлен.

Подключение:
    1. Тимур получает ключ Yandex Geocoder Advanced
    2. Добавить YANDEX_GEOCODER_KEY=... в .env на Railway
    3. Убрать флаг _KEY_MISSING и протестировать покрытие Грузии:
       Натахтари, Цероване, Гори, Зугдиди, Озургети, Ахалкалаки

Требования Advanced-лицензии:
    - Сохранять координаты полученные от Яндекса в БД (cities.yandex_geo_id + lat/lon)
    - НЕ кешировать адреса отдельно без привязки к показу карт Яндекса
"""
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

YANDEX_API_URL = "https://geocode-maps.yandex.ru/1.x/"
_API_KEY: Optional[str] = os.getenv("YANDEX_GEOCODER_KEY")
_KEY_MISSING = not _API_KEY


async def geocode(query: str, lang: str = "ru_RU") -> list[dict]:
    """
    Геокодирует строку через Яндекс. Возвращает список вариантов.
    
    Каждый вариант:
        {"name": str, "lat": float, "lon": float, "geo_id": str, "country": str}
    
    При отсутствии ключа или ошибке — возвращает [].
    """
    if _KEY_MISSING:
        logger.debug("[Yandex] API key not set — geocoder stub returns []")
        return []

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(YANDEX_API_URL, params={
                "apikey": _API_KEY,
                "geocode": query,
                "format": "json",
                "lang": lang,
                "results": 5,
            })
            r.raise_for_status()
            data = r.json()

        features = (
            data.get("response", {})
                .get("GeoObjectCollection", {})
                .get("featureMember", [])
        )
        results = []
        for f in features:
            geo = f.get("GeoObject", {})
            pos = geo.get("Point", {}).get("pos", "")
            if not pos:
                continue
            lon_str, lat_str = pos.split()
            meta = geo.get("metaDataProperty", {}).get("GeocoderMetaData", {})
            results.append({
                "name":    geo.get("name", ""),
                "full":    geo.get("description", ""),
                "lat":     float(lat_str),
                "lon":     float(lon_str),
                "geo_id":  meta.get("AddressDetails", {}).get("Country", {}).get("AdministrativeArea", {}).get("SubAdministrativeArea", {}).get("Locality", {}).get("LocalityName", ""),
                "country": meta.get("AddressDetails", {}).get("Country", {}).get("CountryNameCode", ""),
            })
        return results

    except Exception as exc:
        logger.warning(f"[Yandex] Geocoder error for '{query}': {exc}")
        return []


async def test_georgia_coverage() -> dict:
    """
    Тест покрытия Грузии — запустить перед активацией ключа.
    Проверяет: Натахтари, Цероване, Гори, Зугдиди, Озургети, Ахалкалаки.
    
    Вернуть Тимуру если покрытие < 80% — пересмотреть решение по ADR-007.
    """
    test_cities = ["Натахтари", "Цероване", "Гори", "Зугдиди", "Озургети", "Ахалкалаки"]
    results = {}
    for city in test_cities:
        found = await geocode(f"{city}, Грузия")
        results[city] = {
            "found": len(found) > 0,
            "top_result": found[0].get("name") if found else None,
        }

    total = len(test_cities)
    found_count = sum(1 for r in results.values() if r["found"])
    coverage_pct = round(found_count / total * 100)

    return {
        "coverage_pct": coverage_pct,
        "details": results,
        "verdict": "OK" if coverage_pct >= 80 else "POOR — пересмотреть ADR-007",
    }


def is_available() -> bool:
    """Возвращает True если Яндекс API ключ установлен."""
    return not _KEY_MISSING
