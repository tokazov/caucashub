"""Read-only own-place suggestions and server country resolution for map pins."""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator
from app.database import get_db
from app.services.city_identity import city_registry
from app.services.route_locations import suggest_locations, resolve_map_location

router = APIRouter(prefix='/api/locations', tags=['locations'])

class MapPointRequest(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    label: str = Field(default='Точка на карте', min_length=1, max_length=200)
    label_mode: Literal['auto', 'custom'] | None = None
    address: str | None = Field(None, max_length=500)
    country_iso: str | None = Field(None, pattern=r'^[A-Za-z]{2}$')
    settlement_id: int | None = Field(None, ge=1, strict=True)
    settlement_key: str | None = Field(None, max_length=150)

    @field_validator('lat', 'lon', mode='before')
    @classmethod
    def numeric_coordinates(cls, value):
        if isinstance(value, bool):
            raise ValueError('Координаты должны быть числами')
        return value

@router.get('/suggest')
async def suggestions(q: str = Query('', max_length=200), lang: str = Query('ru'),
                      scope: str | None = Query(None, pattern='^(local|intl)$'),
                      limit: int = Query(250, ge=1, le=300), db: AsyncSession = Depends(get_db)):
    registry = await city_registry(db)
    rows = suggest_locations(registry, q, lang, scope, limit)
    return {'results': rows, 'query': q, 'source': 'own_catalog', 'total': len(rows)}

@router.post('/resolve')
async def resolve(data: MapPointRequest, db: AsyncSession = Depends(get_db)):
    try:
        location = await resolve_map_location(data.model_dump(), await city_registry(db))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'location': location}
