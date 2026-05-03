from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.routers.loads import require_user
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class UpdateProfileRequest(BaseModel):
    company_name: Optional[str] = None
    phone:        Optional[str] = None
    inn:          Optional[str] = None
    org_type:     Optional[str] = None
    city:         Optional[str] = None
    lang:         Optional[str] = None
    telegram_id:  Optional[str] = None


@router.get("/me")
async def get_me(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    return {
        "id":           user.id,
        "email":        user.email,
        "company_name": user.company_name,
        "phone":        user.phone,
        "role":         user.role,
        "plan":         user.plan,
        "rating":       round((user.rating or 50) / 10, 1),
        "trips_count":  user.trips_count or 0,
        "is_verified":  user.is_verified,
        "inn":          user.inn,
        "org_type":     user.org_type,
        "city":         user.city,
        "lang":         user.lang,
        "telegram_id":  user.telegram_id,
    }


@router.put("/me")
async def update_me(
    data: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    if data.company_name is not None: user.company_name = data.company_name
    if data.phone        is not None: user.phone        = data.phone
    if data.inn          is not None: user.inn          = data.inn
    if data.org_type     is not None: user.org_type     = data.org_type
    if data.city         is not None: user.city         = data.city
    if data.lang         is not None: user.lang         = data.lang
    if data.telegram_id  is not None: user.telegram_id  = data.telegram_id

    await db.commit()
    await db.refresh(user)

    return {
        "ok": True,
        "id":           user.id,
        "company_name": user.company_name,
        "phone":        user.phone,
        "inn":          user.inn,
        "org_type":     user.org_type,
        "city":         user.city,
    }


@router.get("/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"error": "Not found"}
    return {
        "id":           user.id,
        "company_name": user.company_name,
        "role":         user.role,
        "plan":         user.plan,
        "rating":       round((user.rating or 50) / 10, 1),
        "trips_count":  user.trips_count or 0,
        "is_verified":  user.is_verified,
        "inn":          user.inn,
        "org_type":     user.org_type,
        "city":         user.city,
    }
