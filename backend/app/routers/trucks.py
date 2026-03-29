from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.truck import Truck
from app.models.user import User
from app.routers.auth import require_user
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()

class TruckCreate(BaseModel):
    truck_type: str
    capacity_kg: float
    volume_m3: Optional[float] = None
    plate: Optional[str] = None
    phone: Optional[str] = None
    available_from: str
    available_to: Optional[str] = None
    available_date: Optional[str] = None

@router.get("/")
async def get_trucks(
    from_city: Optional[str] = Query(None),
    truck_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)
):
    q = select(Truck, User).join(User, Truck.user_id == User.id).where(Truck.is_available == True)
    if from_city:
        q = q.where(Truck.available_from.ilike(f"%{from_city}%"))
    if truck_type:
        q = q.where(Truck.truck_type == truck_type)
    q = q.order_by(Truck.created_at.desc()).limit(limit)
    result = await db.execute(q)
    trucks = []
    for truck, user in result.all():
        trucks.append({
            "id": truck.id,
            "user_id": truck.user_id,
            "company": user.company_name or user.email,
            "phone": user.phone,
            "rating": round(user.rating / 10, 1) if user.rating else 5.0,
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
        except:
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
    return {"ok": True}
