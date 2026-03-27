from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.truck import Truck
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()

class TruckCreate(BaseModel):
    truck_type: str
    capacity_kg: float
    volume_m3: Optional[float] = None
    available_from: str
    available_to: Optional[str] = None
    available_date: Optional[datetime] = None

@router.get("/")
async def get_trucks(
    from_city: Optional[str] = Query(None),
    truck_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)
):
    q = select(Truck).where(Truck.is_available == True)
    if from_city:
        q = q.where(Truck.available_from.ilike(f"%{from_city}%"))
    if truck_type:
        q = q.where(Truck.truck_type == truck_type)
    q = q.limit(limit)
    result = await db.execute(q)
    return {"trucks": result.scalars().all()}

@router.post("/")
async def create_truck(data: TruckCreate, db: AsyncSession = Depends(get_db)):
    truck = Truck(**data.model_dump())
    db.add(truck)
    await db.commit()
    await db.refresh(truck)
    return truck
