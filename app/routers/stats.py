"""
Статистика и счётчики для шапки сайта (Трек 9).
GET /api/stats/counters — кеш 10 минут (safety-fallback).
Event-based инвалидация через invalidate_counters_cache() (Трек 11.2).
"""
import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models.load import Load, LoadStatus
from app.models.truck import Truck
from app.models.user import User

router = APIRouter()

# ── In-memory кеш с safety-fallback TTL 10 минут ────────────────────────────
_stats_cache: dict = {"data": None, "expires_at": None}
_stats_lock = asyncio.Lock()


def invalidate_counters_cache() -> None:
    """
    Сбросить кеш счётчиков немедленно.
    Вызывается явно из эндпоинтов при создании/изменении грузов, машин, пользователей.
    Явный вызов проще дебажить, чем SQLAlchemy events.
    """
    _stats_cache["data"] = None
    _stats_cache["expires_at"] = None


@router.get("/counters")
async def get_counters(db: AsyncSession = Depends(get_db)):
    """
    Счётчики для шапки сайта.
    - Инвалидация event-based (invalidate_counters_cache).
    - Safety-fallback TTL 10 минут на случай пропущенного события.
    - is_demo=True грузы НЕ считаются (ADR-012).
    """
    async with _stats_lock:
        now = datetime.now(timezone.utc)
        if (_stats_cache["data"] and _stats_cache["expires_at"]
                and now < _stats_cache["expires_at"]):
            return _stats_cache["data"]

        # Активные грузы (только реальные, без демо)
        loads_res = await db.execute(
            select(func.count(Load.id)).where(
                Load.status == LoadStatus.active,
                Load.is_demo.is_(False)
            )
        )
        active_loads = loads_res.scalar() or 0

        # Машины "онлайн" — updated_at за последние 24ч (GLOSSARY.md)
        cutoff = now - timedelta(hours=24)
        trucks_res = await db.execute(
            select(func.count(Truck.id)).where(
                Truck.is_available.is_(True),
                Truck.created_at >= cutoff  # используем created_at пока нет updated_at
            )
        )
        online_trucks = trucks_res.scalar() or 0

        # Уникальные компании (по непустому company_name, не демо-юзеры)
        companies_res = await db.execute(
            select(func.count(User.id)).where(
                User.company_name.isnot(None),
                User.is_demo.is_(False),
                User.is_deleted.is_(False)
            )
        )
        companies = companies_res.scalar() or 0

        # Всего пользователей
        from app.models.user import User as UserModel
        total_users_res = await db.execute(
            select(func.count(UserModel.id)).where(
                UserModel.is_deleted.is_(False),
                UserModel.is_demo.is_(False)
            )
        )
        total_users = total_users_res.scalar() or 0

        # Онлайн — last_seen за последние 5 минут
        from datetime import datetime as _dt
        online_cutoff = _dt.utcnow() - timedelta(minutes=5)
        online_users_res = await db.execute(
            select(func.count(UserModel.id)).where(
                UserModel.is_deleted.is_(False),
                UserModel.last_seen.isnot(None),
                UserModel.last_seen >= online_cutoff
            )
        )
        online_users = online_users_res.scalar() or 0

        data = {
            "active_loads":   active_loads,
            "online_trucks":  online_trucks,
            "companies":      companies,
            "total_users":    total_users,
            "online_users":   online_users,
            "cached_at":      now.isoformat(),
            "cache_ttl_min":  10,
        }
        _stats_cache["data"] = data
        # Safety-fallback TTL: 10 минут (на случай пропущенного события)
        _stats_cache["expires_at"] = now + timedelta(minutes=10)
        return data
