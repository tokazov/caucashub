"""Authenticated, account-scoped persistent inbox."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.notification import Notification
from app.models.user import User
from app.routers.auth import require_user
from app.services.notifications import utc_iso, clean_data
from app.services.user_display import display_name

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

async def unread_count(db, user_id):
    return (await db.execute(select(func.count()).select_from(Notification).where(
        Notification.recipient_id == user_id, Notification.read_at.is_(None)))).scalar_one()

@router.get("")
@router.get("/", include_in_schema=False)
async def inbox(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user)):
    condition = Notification.recipient_id == current_user.id
    rows = (await db.execute(select(Notification).where(condition).order_by(
        Notification.created_at.desc(), Notification.id.desc()).limit(limit).offset(offset))).scalars().all()
    actor_ids = {row.actor_id for row in rows if row.actor_id is not None}
    actors = {}
    if actor_ids:
        users = (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
        actors = {user.id: display_name(user) for user in users}
    serialized = []
    for row in rows:
        data = clean_data(row.data)
        if row.actor_id is not None:
            data["actor_name"] = actors.get(row.actor_id, "—")
        serialized.append({"id": row.id, "type": row.kind, "created_at": utc_iso(row.created_at),
                           "read_at": utc_iso(row.read_at), "data": data})
    total = (await db.execute(select(func.count()).select_from(Notification).where(condition))).scalar_one()
    return {"notifications": serialized, "unread_count": await unread_count(db, current_user.id),
            "total": total, "limit": limit, "offset": offset}

@router.post("/read-all")
async def read_all(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user)):
    now = datetime.now(timezone.utc)
    await db.execute(update(Notification).where(
        Notification.recipient_id == current_user.id, Notification.read_at.is_(None)).values(read_at=now))
    await db.commit()
    return {"ok": True, "read_at": utc_iso(now), "unread_count": await unread_count(db, current_user.id)}

@router.post("/{notification_id}/read")
async def read_one(notification_id: int, db: AsyncSession = Depends(get_db),
                   current_user: User = Depends(require_user)):
    row = (await db.execute(select(Notification).where(
        Notification.id == notification_id, Notification.recipient_id == current_user.id)
        .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Уведомление не найдено")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        await db.commit()
    return {"ok": True, "id": row.id, "read_at": utc_iso(row.read_at),
            "unread_count": await unread_count(db, current_user.id)}
