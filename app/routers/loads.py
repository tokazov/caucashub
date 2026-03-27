from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from app.database import get_db
from app.models.load import Load, LoadScope, LoadStatus
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()

class LoadCreate(BaseModel):
    from_city: str
    from_address: Optional[str] = None
    to_city: str
    to_address: Optional[str] = None
    scope: str = "local"
    weight_kg: float
    volume_m3: Optional[float] = None
    truck_type: str
    cargo_desc: Optional[str] = None
    price_usd: Optional[float] = None
    payment_type: Optional[str] = None
    load_date: datetime
    is_urgent: bool = False

@router.get("/")
async def get_loads(
    scope: Optional[str] = Query(None),
    from_city: Optional[str] = Query(None),
    to_city: Optional[str] = Query(None),
    truck_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db)
):
    q = select(Load).where(Load.status == LoadStatus.active)

    if scope:
        q = q.where(Load.scope == scope)
    if from_city:
        q = q.where(Load.from_city.ilike(f"%{from_city}%"))
    if to_city:
        q = q.where(Load.to_city.ilike(f"%{to_city}%"))
    if truck_type:
        q = q.where(Load.truck_type == truck_type)

    # Сначала срочные и продвинутые
    q = q.order_by(Load.is_urgent.desc(), Load.is_boosted.desc(), Load.created_at.desc())
    q = q.limit(limit).offset(offset)

    result = await db.execute(q)
    loads = result.scalars().all()
    return {"loads": loads, "total": len(loads)}

@router.post("/")
async def create_load(data: LoadCreate, db: AsyncSession = Depends(get_db)):
    # TODO: добавить авторизацию
    load = Load(**data.model_dump())
    db.add(load)
    await db.commit()
    await db.refresh(load)
    return load

@router.get("/{load_id}")
async def get_load(load_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Load).where(Load.id == load_id))
    load = result.scalar_one_or_none()
    if not load:
        return {"error": "Not found"}
    # Инкремент просмотров
    load.views += 1
    await db.commit()
    return load
