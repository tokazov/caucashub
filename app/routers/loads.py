from fastapi import APIRouter, Depends, Query, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.load import Load, LoadStatus
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

def load_to_dict(load: Load, company_name: str = None, user: object = None, show_contacts: bool = False) -> dict:  # noqa: E741
    """Конвертируем Load в dict для фронтенда."""
    # Берём company_name: явный параметр → user объект → fallback
    from app.services.user_display import display_name
    co = company_name
    if not co and user:
        co = display_name(user)
    if not co:
        co = "CaucasHub"

    # Рейтинг и рейсы из профиля
    rat = "5.0"
    trips = 0
    completed_deals = 0
    ratings_received = 0
    if user:
        rat   = f"{user.rating / 10:.1f}" if user.rating else "5.0"
        trips = user.trips_count or 0
        completed_deals = getattr(user, 'completed_deals_count', 0) or 0
        ratings_received = getattr(user, 'ratings_received_count', 0) or 0

    return {
        "id": load.id,
        "from": load.from_city,
        "from2": load.from_address or load.from_city,
        "to": load.to_city,
        "to2": load.to_address or load.to_city,
        "scope": load.scope.value if hasattr(load.scope, 'value') else str(load.scope),
        "kg": load.weight_kg,
        "type": load.truck_type.value if hasattr(load.truck_type, 'value') else str(load.truck_type),
        "typeLabel": {"tent":"Тент","ref":"Рефриж.","bort":"Борт","termos":"Термос","gazel":"Фургон","container":"Контейнер","auto":"Автовоз","other":"Другой"}.get(
            load.truck_type.value if hasattr(load.truck_type,'value') else str(load.truck_type), "Тент"),
        "price": load.price_gel or load.price_usd or 0,
        "cur": "₾" if load.price_gel else "$",
        "desc": load.cargo_desc or "",
        "pay": load.payment_type or "Нал",
        "urgent": load.is_urgent,
        "status": load.status.value if hasattr(load.status, 'value') else str(load.status),
        "badge": "urgent" if load.is_urgent else None,
        "date": load.load_date.strftime("%d.%m.%y") if load.load_date else None,
        "co": co,
        "rat": rat,
        "trips": trips,
        "completed_deals": completed_deals,   # 3.1
        "ratings_received": ratings_received,  # 3.1
        "user_id": load.user_id,
        "views": load.views or 0,
        "is_demo": getattr(load, 'is_demo', False),  # ADR-012
        "owner_verified": bool(user.is_verified) if user else False,  # 2.4.4
        "created_at": load.created_at.isoformat() if load.created_at else None,
        # Контакты владельца — только для платных планов
        "owner_phone": (user.phone if user else None) if show_contacts else None,
        "owner_email": (user.email if user else None) if show_contacts else None,
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
    user_ids = list({lo.user_id for lo in loads if lo.user_id})
    users_map: dict = {}
    if user_ids:
        uq = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in uq.scalars().all():
            users_map[u.id] = u

    return {"loads": [load_to_dict(lo, user=users_map.get(lo.user_id)) for lo in loads], "total": len(loads)}

@router.post("/")
async def create_load(data: LoadCreate, request: Request, db: AsyncSession = Depends(get_db),
                      authorization: Optional[str] = Header(None)):
    from app.services.exchange_rate import get_usd_gel_rate, convert_gel_to_usd, convert_usd_to_gel
    from app.services.idempotency import check_idempotency
    user_id = require_user(authorization)
    await check_idempotency(request, scope="create_load", user_id=user_id)
    load_data = data.model_dump(exclude={"company_name", "load_date_end"})

    # Фикс 1: Серверная валидация веса и цены (P1 Cat4)
    w = load_data.get("weight_kg")
    if w is None or w <= 0 or w > 50000:
        raise HTTPException(status_code=422, detail="weight_kg должен быть от 1 до 50000 кг")
    p_gel = load_data.get("price_gel") or 0
    p_usd = load_data.get("price_usd") or 0
    if p_gel <= 0 and p_usd <= 0:
        raise HTTPException(status_code=422, detail="Укажите цену груза (price_gel или price_usd > 0)")

    if not load_data.get("load_date"):
        load_data["load_date"] = datetime.utcnow()
    else:
        # Трек 9: дата загрузки не может быть в прошлом (> 1 день назад)
        ld = load_data["load_date"]
        if hasattr(ld, 'replace'):
            ld_naive = ld.replace(tzinfo=None) if ld.tzinfo else ld
            if ld_naive < datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0):
                raise HTTPException(status_code=400, detail="load_date cannot be in the past")

    # Трек 9: нормализуем payment_type
    if load_data.get("payment_type"):
        from app.services.dictionaries import normalize_payment_type
        load_data["payment_type"] = normalize_payment_type(load_data["payment_type"])

    # Категория 4 Part A: XSS-санитизация текстовых полей
    from app.services.normalizers import sanitize_text
    if load_data.get("cargo_desc"):
        load_data["cargo_desc"] = sanitize_text(load_data["cargo_desc"], max_length=1000)
    if load_data.get("from_city"):
        load_data["from_city"] = sanitize_text(load_data["from_city"], max_length=100)
    if load_data.get("to_city"):
        load_data["to_city"] = sanitize_text(load_data["to_city"], max_length=100)
    if load_data.get("from_address"):
        load_data["from_address"] = sanitize_text(load_data["from_address"], max_length=200)
    if load_data.get("to_address"):
        load_data["to_address"] = sanitize_text(load_data["to_address"], max_length=200)

    # Фикс 2: Валидация date_end >= date_start (P1 Cat4)
    if data.load_date_end:
        try:
            # Парсим dd.mm.yy или dd.mm.yyyy
            parts = data.load_date_end.split(".")
            if len(parts) == 3:
                y = int(parts[2]) + 2000 if len(parts[2]) == 2 else int(parts[2])
                from datetime import date as _date
                date_end = _date(y, int(parts[1]), int(parts[0]))
                date_start = load_data["load_date"]
                if hasattr(date_start, 'date'):
                    date_start = date_start.date()
                elif hasattr(date_start, 'replace'):
                    date_start = date_start.date() if hasattr(date_start, 'date') else date_start
                if date_end < date_start:
                    raise HTTPException(status_code=422, detail="Дата окончания не может быть раньше даты начала")
        except HTTPException:
            raise
        except Exception:
            pass  # невалидный формат — пропускаем

    # ADR-006: получаем курс NBG и заполняем обе валюты
    rate = await get_usd_gel_rate()
    load_data["exchange_rate_at_creation"] = rate
    if load_data.get("price_gel") and not load_data.get("price_usd"):
        load_data["price_usd"] = convert_gel_to_usd(load_data["price_gel"], rate)
    elif load_data.get("price_usd") and not load_data.get("price_gel"):
        load_data["price_gel"] = convert_usd_to_gel(load_data["price_usd"], rate)

    load = Load(**load_data, user_id=user_id)
    db.add(load)
    await db.commit()
    await db.refresh(load)
    # Инвалидируем кеш счётчиков (Трек 11.2)
    from app.routers.stats import invalidate_counters_cache
    invalidate_counters_cache()
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
    updates = data.model_dump(exclude_none=True)
    # Фикс 1: Валидация при обновлении
    if "weight_kg" in updates:
        w = updates["weight_kg"]
        if w <= 0 or w > 50000:
            raise HTTPException(status_code=422, detail="weight_kg должен быть от 1 до 50000 кг")
    if "price_gel" in updates or "price_usd" in updates:
        new_gel = updates.get("price_gel", load.price_gel or 0)
        new_usd = updates.get("price_usd", load.price_usd or 0)
        if (new_gel or 0) <= 0 and (new_usd or 0) <= 0:
            raise HTTPException(status_code=422, detail="Укажите цену груза > 0")
    for k, v in updates.items():
        if hasattr(load, k) and k != "load_date_end":
            setattr(load, k, v)
    await db.commit()
    await db.refresh(load)
    # Инвалидируем кеш (статус мог измениться — Трек 11.2)
    from app.routers.stats import invalidate_counters_cache
    invalidate_counters_cache()
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
    # Нельзя отменить груз с активной сделкой
    if load.status == LoadStatus.taken:
        from app.models.deal import Deal, DealStatus
        active_deal = await db.execute(
            select(Deal).where(
                Deal.load_id == load_id,
                Deal.status.notin_([DealStatus.canceled, DealStatus.completed, DealStatus.rated])
            )
        )
        if active_deal.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="Cannot cancel load with active deal. Cancel the deal first."
            )
    load.status = LoadStatus.canceled
    await db.commit()
    # Инвалидируем кеш (груз снят — Трек 11.2)
    from app.routers.stats import invalidate_counters_cache
    invalidate_counters_cache()
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
    return {"loads": [load_to_dict(lo, user=owner) for lo in loads]}

@router.get("/{load_id}")
async def get_load(
    load_id: int,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    result = await db.execute(select(Load).where(Load.id == load_id))
    load = result.scalar_one_or_none()
    if not load:
        return {"error": "Not found"}
    load.views += 1
    await db.commit()
    # Загружаем профиль владельца
    ur = await db.execute(select(User).where(User.id == load.user_id))
    owner = ur.scalar_one_or_none()

    # Определяем показывать ли контакты (если PRICING_ENABLED=false — показываем всем авторизованным)
    from app.services.plan_check import PRICING_ENABLED, is_paid_plan
    show_contacts = False
    viewer_id = get_user_id(authorization)
    if viewer_id:
        if not PRICING_ENABLED:
            show_contacts = True  # Тарификация выключена — контакты всем
        else:
            viewer_res = await db.execute(select(User).where(User.id == viewer_id))
            viewer = viewer_res.scalar_one_or_none()
            if viewer:
                show_contacts = is_paid_plan(viewer)

    return load_to_dict(load, user=owner, show_contacts=show_contacts)


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
