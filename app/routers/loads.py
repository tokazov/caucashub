from fastapi import APIRouter, Depends, Query, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from app.database import get_db
from app.models.load import Load, LoadScope, LoadStatus, TruckType
from app.models.user import User
from app.config import settings
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from jose import jwt, JWTError

router = APIRouter()

def get_user_id(authorization: Optional[str] = Header(None)) -> Optional[int]:
    """Извлекаем user_id из JWT токена. Возвращает None если нет токена."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        token = authorization.split(" ")[1]
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return int(payload.get("sub"))
    except (JWTError, ValueError):
        return None

def require_user(authorization: Optional[str] = Header(None)) -> int:
    uid = get_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Authorization required")
    return uid

class LoadCreate(BaseModel):
    from_city: str
    from_address: Optional[str] = None
    to_city: str
    to_address: Optional[str] = None
    scope: str = "local"
    weight_kg: float
    volume_m3: Optional[float] = None
    truck_type: str = "tent"
    cargo_desc: Optional[str] = None
    price_usd: Optional[float] = None
    price_gel: Optional[float] = None
    payment_type: Optional[str] = None
    load_date: Optional[datetime] = None
    load_date_end: Optional[str] = None   # дата конца интервала (строка dd.mm.yy)
    is_urgent: bool = False
    company_name: Optional[str] = None   # название компании для отображения

class LoadUpdate(BaseModel):
    from_city: Optional[str] = None
    from_address: Optional[str] = None
    to_city: Optional[str] = None
    to_address: Optional[str] = None
    weight_kg: Optional[float] = None
    truck_type: Optional[str] = None
    cargo_desc: Optional[str] = None
    price_usd: Optional[float] = None
    price_gel: Optional[float] = None
    payment_type: Optional[str] = None
    load_date: Optional[datetime] = None
    load_date_end: Optional[str] = None
    is_urgent: Optional[bool] = None

def load_to_dict(l: Load, company_name: str = None, user: object = None) -> dict:
    """Конвертируем Load в dict для фронтенда."""
    # Берём company_name: явный параметр → user объект → fallback
    co = company_name
    if not co and user:
        co = user.company_name or user.email.split('@')[0]
    if not co:
        co = "CaucasHub"

    # Рейтинг и рейсы из профиля
    rat = "5.0"
    trips = 0
    if user:
        rat   = f"{user.rating / 10:.1f}" if user.rating else "5.0"
        trips = user.trips_count or 0

    return {
        "id": l.id,
        "from": l.from_city,
        "from2": l.from_address or l.from_city,
        "to": l.to_city,
        "to2": l.to_address or l.to_city,
        "scope": l.scope.value if hasattr(l.scope, 'value') else str(l.scope),
        "kg": l.weight_kg,
        "type": l.truck_type.value if hasattr(l.truck_type, 'value') else str(l.truck_type),
        "typeLabel": {"tent":"Тент","ref":"Рефриж.","bort":"Борт","termos":"Термос","gazel":"Фургон","container":"Контейнер","auto":"Автовоз","other":"Другой"}.get(
            l.truck_type.value if hasattr(l.truck_type,'value') else str(l.truck_type), "Тент"),
        "price": l.price_gel or l.price_usd or 0,
        "cur": "₾" if l.price_gel else "$",
        "desc": l.cargo_desc or "",
        "pay": l.payment_type or "Нал",
        "urgent": l.is_urgent,
        "status": l.status.value if hasattr(l.status,'value') else str(l.status),
        "badge": "urgent" if l.is_urgent else None,
        "date": l.load_date.strftime("%d.%m.%y") if l.load_date else None,
        "co": co,
        "rat": rat,
        "trips": trips,
        "user_id": l.user_id,
        "views": l.views or 0,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }

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

    # Подгружаем пользователей одним запросом
    user_ids = list({l.user_id for l in loads if l.user_id})
    users_map: dict = {}
    if user_ids:
        uq = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in uq.scalars().all():
            users_map[u.id] = u

    return {"loads": [load_to_dict(l, user=users_map.get(l.user_id)) for l in loads], "total": len(loads)}

@router.post("/")
async def create_load(data: LoadCreate, db: AsyncSession = Depends(get_db),
                      authorization: Optional[str] = Header(None)):
    user_id = require_user(authorization)
    load_data = data.model_dump(exclude={"company_name", "load_date_end"})
    if not load_data.get("load_date"):
        load_data["load_date"] = datetime.utcnow()
    load = Load(**load_data, user_id=user_id)
    db.add(load)
    await db.commit()
    await db.refresh(load)
    return load_to_dict(load, data.company_name)

@router.put("/{load_id}")
async def update_load(load_id: int, data: LoadUpdate, db: AsyncSession = Depends(get_db),
                      authorization: Optional[str] = Header(None)):
    user_id = require_user(authorization)
    result = await db.execute(select(Load).where(Load.id == load_id))
    load = result.scalar_one_or_none()
    if not load:
        raise HTTPException(status_code=404, detail="Not found")
    if load.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your load")
    for k, v in data.model_dump(exclude_none=True).items():
        if hasattr(load, k) and k != "load_date_end":
            setattr(load, k, v)
    await db.commit()
    await db.refresh(load)
    return load_to_dict(load)

@router.delete("/{load_id}")
async def delete_load(load_id: int, db: AsyncSession = Depends(get_db),
                      authorization: Optional[str] = Header(None)):
    user_id = require_user(authorization)
    result = await db.execute(select(Load).where(Load.id == load_id))
    load = result.scalar_one_or_none()
    if not load:
        raise HTTPException(status_code=404, detail="Not found")
    if load.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your load")
    load.status = LoadStatus.canceled
    await db.commit()
    return {"ok": True}

@router.get("/my/loads")
async def get_my_loads(db: AsyncSession = Depends(get_db),
                       authorization: Optional[str] = Header(None)):
    user_id = require_user(authorization)
    result = await db.execute(
        select(Load).where(Load.user_id == user_id, Load.status != LoadStatus.canceled)
        .order_by(Load.created_at.desc())
    )
    loads = result.scalars().all()
    # Загружаем профиль текущего пользователя
    ur = await db.execute(select(User).where(User.id == user_id))
    owner = ur.scalar_one_or_none()
    return {"loads": [load_to_dict(l, user=owner) for l in loads]}

@router.get("/{load_id}")
async def get_load(load_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Load).where(Load.id == load_id))
    load = result.scalar_one_or_none()
    if not load:
        return {"error": "Not found"}
    load.views += 1
    await db.commit()
    # Загружаем профиль владельца
    ur = await db.execute(select(User).where(User.id == load.user_id))
    owner = ur.scalar_one_or_none()
    return load_to_dict(load, user=owner)


@router.delete("/admin/bulk-delete")
async def admin_bulk_delete(
    ids: list[int],
    secret: str,
    db: AsyncSession = Depends(get_db)
):
    """Admin: удалить несколько грузов"""
    import os
    if secret != os.getenv("ADMIN_SECRET", "caucashub-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    from sqlalchemy import delete as sql_delete
    await db.execute(sql_delete(Load).where(Load.id.in_(ids)))
    await db.commit()
    return {"deleted": ids}


@router.post("/admin/set-status")
async def admin_set_status(
    ids: list[int],
    status: str,
    secret: str,
    db: AsyncSession = Depends(get_db)
):
    """Admin: изменить статус грузов. status: active|taken|expired|canceled"""
    import os
    if secret != os.getenv("ADMIN_SECRET", "caucashub-admin-2026"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        new_status = LoadStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown status: {status}")
    from sqlalchemy import update as sql_update
    await db.execute(
        sql_update(Load).where(Load.id.in_(ids)).values(status=new_status)
    )
    await db.commit()
    return {"updated": ids, "status": status}
