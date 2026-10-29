from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.truck import Truck
from app.models.user import User
from app.routers.auth import require_user
from app.services.user_display import display_name
from app.services.public_ratings import public_ratings, public_rating_fields
from app.services.transport_capacity import (TRUCK_TYPES, canonical_truck_type,
    validate_transport_capacity, capacity_metadata)
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional

router = APIRouter()

class TruckCreate(BaseModel):
    truck_type: str
    capacity_kg: float = Field(gt=0, le=100000, allow_inf_nan=False)
    volume_m3: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    plate: Optional[str] = None
    phone: Optional[str] = None
    available_from: str
    available_to: Optional[str] = None
    available_date: Optional[str] = None

    @field_validator("capacity_kg", mode="before")
    @classmethod
    def capacity_is_number(cls, value):
        if isinstance(value, bool):
            raise ValueError("Грузоподъёмность должна быть числом")
        return value

    @field_validator("truck_type")
    @classmethod
    def body_type(cls, value):
        value = canonical_truck_type(value)
        if value not in TRUCK_TYPES:
            raise ValueError("Выберите допустимый тип кузова")
        return value

    @model_validator(mode="after")
    def body_capacity(self):
        validate_transport_capacity(self.truck_type, self.capacity_kg)
        return self

@router.get("/")
async def get_trucks(
    from_city: Optional[str] = Query(None),
    truck_type: Optional[str] = Query(None),
    limit:  int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    q = select(Truck, User).join(User, Truck.user_id == User.id).where(Truck.is_available)
    if from_city:
        q = q.where(Truck.available_from.ilike(f"%{from_city}%"))
    if truck_type:
        q = q.where(Truck.truck_type == truck_type)
    q = q.order_by(Truck.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.all()
    ratings = await public_ratings(db, [user.id for _, user in rows])
    trucks = []
    for truck, user in rows:
        trucks.append({
            "id": truck.id,
            "user_id": truck.user_id,
            "company": display_name(user),
            # Public catalogue contacts follow the accepted-deal policy (ADR-013).
            "phone": None,
            **public_rating_fields(ratings.get(user.id)),
            **capacity_metadata(truck.truck_type, truck.capacity_kg),
            "trips": user.trips_count or 0,
            "truck_type": truck.truck_type,
            "capacity_kg": truck.capacity_kg,
            "volume_m3": truck.volume_m3,
            "plate": truck.plate,
            "available_from": truck.available_from,
            "available_to": truck.available_to or "Любое направление",
            "available_date": truck.available_date.strftime("%d.%m.%y") if truck.available_date else None,
            "created_at": truck.created_at.isoformat() if truck.created_at else None,
        })
    return {"trucks": trucks, "total": len(trucks)}

@router.post("/")
async def create_truck(
    data: TruckCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    from datetime import datetime as dt
    avail_date = None
    if data.available_date:
        try:
            avail_date = dt.strptime(data.available_date, "%Y-%m-%d")
        except ValueError:
            pass
    truck = Truck(
        user_id=current_user.id,
        truck_type=data.truck_type,
        capacity_kg=data.capacity_kg,
        volume_m3=data.volume_m3,
        plate=data.plate,
        available_from=data.available_from,
        available_to=data.available_to,
        available_date=avail_date,
        is_available=True,
    )
    db.add(truck)
    await db.commit()
    await db.refresh(truck)
    # Инвалидируем кеш счётчиков (новая машина — Трек 11.2)
    from app.routers.stats import invalidate_counters_cache
    invalidate_counters_cache()
    return {"ok": True, "id": truck.id}

@router.delete("/{truck_id}")
async def delete_truck(
    truck_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    result = await db.execute(select(Truck).where(Truck.id == truck_id, Truck.user_id == current_user.id))
    truck = result.scalar_one_or_none()
    if not truck:
        from fastapi import HTTPException
        raise HTTPException(404, "Not found")
    await db.delete(truck)
    await db.commit()
    # Инвалидируем кеш счётчиков (машина удалена — Трек 11.2)
    from app.routers.stats import invalidate_counters_cache
    invalidate_counters_cache()
    return {"ok": True}
