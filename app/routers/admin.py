"""
Admin API — CaucasHub.ge
Все эндпоинты защищены заголовком X-Admin-Secret.

GET  /api/admin/users              — список пользователей
PATCH /api/admin/users/{id}/plan   — сменить план
GET  /api/payments/admin/list      — все платежи (добавлено в payments.py)
"""
import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User, UserPlan
from app.models.payment import Payment

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "caucashub-admin-2026")


def _require_admin(x_admin_secret: str = Header(default="")):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


class PlanUpdate(BaseModel):
    plan: str  # free | pro | pro_plus | business


@router.get("/stats")
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """Общая статистика платформы."""
    from sqlalchemy import func as sqlfunc, text

    # Всего пользователей
    total_users_q = await db.execute(select(sqlfunc.count(User.id)).where(User.is_active == True))
    total_users = total_users_q.scalar() or 0

    # Новых за текущий месяц
    new_this_month_q = await db.execute(
        select(sqlfunc.count(User.id)).where(
            User.is_active == True,
            sqlfunc.date_trunc('month', User.created_at) == sqlfunc.date_trunc('month', sqlfunc.now())
        )
    )
    new_this_month = new_this_month_q.scalar() or 0

    # Pro/Business пользователей — через SQL cast
    paid_q = await db.execute(
        text("SELECT COUNT(*) FROM users WHERE is_active=true AND plan::text IN ('pro','pro_plus','business')")
    )
    paid_users = paid_q.scalar() or 0

    # Всего грузов активных
    total_loads_q = await db.execute(
        text("SELECT COUNT(*) FROM loads WHERE status='active'")
    )
    total_loads = total_loads_q.scalar() or 0

    # Грузов за месяц
    new_loads_q = await db.execute(
        text("SELECT COUNT(*) FROM loads WHERE date_trunc('month', created_at) = date_trunc('month', NOW())")
    )
    new_loads_month = new_loads_q.scalar() or 0

    return {
        "total_users": total_users,
        "new_this_month": new_this_month,
        "paid_users": paid_users,
        "total_loads": total_loads,
        "new_loads_month": new_loads_month,
    }


@router.get("/users")
async def admin_list_users(
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    q = select(User).order_by(User.id.desc()).limit(limit).offset(offset)
    if search:
        q = q.where(User.email.ilike(f"%{search}%"))
    result = await db.execute(q)
    users = result.scalars().all()
    return {"users": [
        {
            "id": u.id,
            "email": u.email,
            "company_name": getattr(u, "company_name", None),
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "plan": u.plan.value if hasattr(u.plan, "value") else str(u.plan),
            "is_active": u.is_active,
            "tg_chat_id": getattr(u, "telegram_id", None),
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "completed_deals": getattr(u, "completed_deals_count", 0),
        }
        for u in users
    ]}


@router.patch("/users/{user_id}/plan")
async def admin_update_plan(
    user_id: int,
    body: PlanUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    valid_plans = ["free", "pro", "pro_plus", "business"]
    if body.plan not in valid_plans:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Use: {valid_plans}")
    user.plan = body.plan
    await db.commit()
    return {"ok": True, "user_id": user_id, "plan": body.plan}
