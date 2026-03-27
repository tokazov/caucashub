from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User

router = APIRouter()

@router.get("/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"error": "Not found"}
    return {
        "id": user.id,
        "company_name": user.company_name,
        "role": user.role,
        "plan": user.plan,
        "rating": user.rating / 10,
        "trips_count": user.trips_count,
        "is_verified": user.is_verified,
    }
