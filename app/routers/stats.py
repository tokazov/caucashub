"""
Статистика и счётчики для шапки сайта (Трек 9).
GET /api/stats/counters — кеш 5 минут.
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

# ── In-memory кеш 5 минут ─────────────────────────────────────────────────────
_stats_cache: dict = {"data": None, "expires_at": None}
_stats_lock = asyncio.Lock()


@router.get("/counters")
async def get_counters(db: AsyncSession = Depends(get_db)):
    """
    Счётчики для шапки сайта. Кеш 5 минут.
    Если БД пустая — возвращает нули (не хардкод).
    """
    async with _stats_lock:
        now = datetime.now(timezone.utc)
        if (_stats_cache["data"] and _stats_cache["expires_at"]
                and now < _stats_cache["expires_at"]):
            return _stats_cache["data"]

        # Активные грузы
        loads_res = await db.execute(
            select(func.count(Load.id)).where(Load.status == LoadStatus.active)
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

        # Уникальные компании (по непустому company_name)
        companies_res = await db.execute(
            select(func.count(User.id)).where(User.company_name.isnot(None))
        )
        companies = companies_res.scalar() or 0

        data = {
            "active_loads":   active_loads,
            "online_trucks":  online_trucks,
            "companies":      companies,
            "cached_at":      now.isoformat(),
            "cache_ttl_min":  5,
        }
        _stats_cache["data"] = data
        _stats_cache["expires_at"] = now + timedelta(minutes=5)
        return data
