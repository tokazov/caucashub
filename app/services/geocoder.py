"""
LocationIQ геокодер (ADR-015).
search_city(query, lang) → список городов с координатами.
Для русских запросов — транслит через словарь GEO_MAPPING_RU_EN.
Fallback: при пустом LOCATIONIQ_KEY — поиск по таблице cities (LIKE).
"""
import os
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.geo_mapping import GEO_MAPPING_RU_EN

LOCATIONIQ_KEY = os.getenv("LOCATIONIQ_KEY", "")
LOCATIONIQ_BASE = "https://api.locationiq.com/v1"


def _transliterate_ru(query: str) -> str:
    """Попытка найти город через маппинг, иначе возвращает original."""
    key = query.strip().lower()
    return GEO_MAPPING_RU_EN.get(key, query)


async def search_city(
    query: str,
    lang: str = "ru",
    limit: int = 5,
    db: AsyncSession | None = None,
) -> list[dict]:
    """
    Поиск города через LocationIQ.
    lang="ru" → транслит через словарь → запрос на английском
    lang="ka"/"en" → прямой запрос

    Fallback при пустом LOCATIONIQ_KEY: поиск в таблице cities через LIKE.
    Возвращает список: [{name_ru, name_local, lat, lon, display_name, type}]
    """
    key = LOCATIONIQ_KEY or os.getenv("LOCATIONIQ_KEY", "")

    if not key:
        # Fallback: поиск в локальной БД
        if db is not None:
            return await _search_city_db(query, lang=lang, limit=limit, db=db)
        return []

    search_query = query
    if lang == "ru":
        search_query = _transliterate_ru(query)

    params = {
        "key": key,
        "q": search_query,
        "countrycodes": "ge",
        "limit": limit,
        "format": "json",
        "accept-language": "ka,en",
        "addressdetails": 1,
        "dedupe": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{LOCATIONIQ_BASE}/search.php", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        # При ошибке API — fallback в БД
        if db is not None:
            return await _search_city_db(query, lang=lang, limit=limit, db=db)
        return []

    results = []
    for item in data:
        addr = item.get("address", {})
        name_local = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or item.get("display_name", "").split(",")[0]
        )
        results.append(
            {
                "name_ru": query if lang == "ru" else name_local,
                "name_local": name_local,
                "name_en": search_query if lang == "ru" else name_local,
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "display_name": item.get("display_name", ""),
                "type": item.get("type", ""),
                "osm_id": item.get("osm_id", ""),
                "source": "locationiq",
            }
        )
    return results


async def _search_city_db(
    query: str,
    lang: str = "ru",
    limit: int = 5,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Поиск в локальной таблице cities (fallback без API-ключа)."""
    from app.models.city import City

    if db is None:
        return []

    # Транслит для поиска по name_ru
    stmt = select(City).where(City.name_ru.ilike(f"%{query}%")).limit(limit)
    result = await db.execute(stmt)
    cities = result.scalars().all()

    return [
        {
            "name_ru": c.name_ru,
            "name_local": c.name_ge or c.name_ru,
            "name_en": c.name_ru,
            "lat": float(c.lat) if c.lat else None,
            "lon": float(c.lon) if c.lon else None,
            "display_name": f"{c.name_ru}, Georgia",
            "type": "city",
            "osm_id": "",
            "source": "db_fallback",
        }
        for c in cities
    ]
