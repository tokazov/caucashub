"""
Роутер городов — автокомплит и справочник (ADR-007).
"""
import os
from app.services.admin_auth import admin_secret_matches
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.city import City
from app.services.city_identity import city_registry

router = APIRouter()


@router.get("/")
async def get_cities(
    q: str = Query("", min_length=0, description="Поисковый запрос (начало названия)"),
    country: str = Query("", description="Фильтр по стране ISO"),
    popular_only: bool = Query(False),
    limit: int = Query(15, le=50),
    db: AsyncSession = Depends(get_db),
):
    """RU/EN/KA autocomplete sharing canonical IDs with listing search."""
    registry = await city_registry(db)
    cities = registry.search(q, country=country, popular_only=popular_only or not q)[:limit]
    return {"cities": [c.public() for c in cities], "total": len(cities),
            "yandex_available": False}


@router.post("/seed")
async def seed_cities_endpoint(
    secret: str,
    db: AsyncSession = Depends(get_db),
):
    """Admin: заполнить таблицу городов начальными данными."""
    if not admin_secret_matches(secret):
        raise HTTPException(status_code=403, detail="Forbidden")

    from app.services.cities_seed import seed_cities
    count = await seed_cities(db)
    return {"seeded": count, "message": f"Added {count} cities" if count else "Already seeded"}


@router.get("/search")
async def search_cities(
    q: str = Query(..., min_length=2),
    lang: str = Query("ru"),
    limit: int = Query(5, le=10),
    db: AsyncSession = Depends(get_db),
):
    """Поиск города через LocationIQ геокодер (ADR-015). Fallback в локальную БД."""
    from app.services.geocoder import search_city

    results = await search_city(q, lang=lang, limit=limit, db=db)
    return {"results": results, "query": q, "lang": lang}


@router.get("/{city_id}")
async def get_city(city_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(City).where(City.id == city_id))
    city = result.scalar_one_or_none()
    if not city:
        raise HTTPException(404, "City not found")
    return {
        "id": city.id,
        "name_ru": city.name_ru,
        "name_ge": city.name_ge,
        "country_iso": city.country_iso,
        "lat": city.lat,
        "lon": city.lon,
    }
