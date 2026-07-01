"""
Рекламные блоки CaucasHub
GET  /api/ads/{placement}        — случайный активный баннер (публичный)
POST /api/ads/{id}/click         — трекинг клика (публичный)
POST /api/ads/{id}/impression    — трекинг показа (публичный)
GET  /api/ads/admin/list         — список всех баннеров (admin)
POST /api/ads/admin/create       — создать баннер (admin)
PATCH /api/ads/admin/{id}        — обновить баннер (admin)
DELETE /api/ads/admin/{id}       — удалить баннер (admin)
"""
import os
import random
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.ad import Ad

router = APIRouter(prefix="/api/ads", tags=["ads"])

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "caucashub-admin-2026")

# ── Auth helper ──────────────────────────────────────────────────────────────

def _require_admin(x_admin_secret: str = Header(default="")):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Schemas ───────────────────────────────────────────────────────────────────

class AdCreate(BaseModel):
    advertiser: str
    image_url: Optional[str] = None
    link_url: str
    title: Optional[str] = None
    description: Optional[str] = None
    cta_text: Optional[str] = None
    placement: str          # feed | rates | modal | footer | banner
    active: bool = True
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class AdUpdate(BaseModel):
    advertiser: Optional[str] = None
    image_url: Optional[str] = None
    link_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    cta_text: Optional[str] = None
    placement: Optional[str] = None
    active: Optional[bool] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


# ── Public endpoints ──────────────────────────────────────────────────────────

@router.get("/{placement}")
async def get_ad(placement: str, db: AsyncSession = Depends(get_db)):
    """Вернуть случайный активный баннер для размещения."""
    now = datetime.now(timezone.utc)
    q = select(Ad).where(
        Ad.placement == placement,
        Ad.active == True,
    ).where(
        (Ad.start_date == None) | (Ad.start_date <= now)
    ).where(
        (Ad.end_date == None) | (Ad.end_date >= now)
    )
    result = await db.execute(q)
    ads = result.scalars().all()
    if not ads:
        return {"ad": None}
    ad = random.choice(ads)
    # Трекинг показа
    ad.impressions = (ad.impressions or 0) + 1
    await db.commit()
    return {"ad": {
        "id": ad.id,
        "advertiser": ad.advertiser,
        "image_url": ad.image_url,
        "link_url": ad.link_url,
        "title": ad.title,
        "description": ad.description,
        "cta_text": ad.cta_text or "Подробнее →",
        "placement": ad.placement,
    }}


@router.post("/{ad_id}/click")
async def track_click(ad_id: int, db: AsyncSession = Depends(get_db)):
    """Трекинг клика по баннеру."""
    ad = await db.get(Ad, ad_id)
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.clicks = (ad.clicks or 0) + 1
    await db.commit()
    return {"ok": True, "link_url": ad.link_url}


# ── Admin endpoints ───────────────────────────────────────────────────────────

@router.get("/admin/list")
async def admin_list(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    result = await db.execute(select(Ad).order_by(Ad.id.desc()))
    ads = result.scalars().all()
    return {"ads": [
        {
            "id": a.id,
            "advertiser": a.advertiser,
            "placement": a.placement,
            "active": a.active,
            "clicks": a.clicks,
            "impressions": a.impressions,
            "title": a.title,
            "image_url": a.image_url,
            "link_url": a.link_url,
            "cta_text": a.cta_text,
            "start_date": a.start_date,
            "end_date": a.end_date,
        }
        for a in ads
    ]}


@router.post("/admin/create")
async def admin_create(
    body: AdCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    ad = Ad(**body.model_dump())
    db.add(ad)
    await db.commit()
    await db.refresh(ad)
    return {"ok": True, "id": ad.id}


@router.patch("/admin/{ad_id}")
async def admin_update(
    ad_id: int,
    body: AdUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    ad = await db.get(Ad, ad_id)
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(ad, field, value)
    await db.commit()
    return {"ok": True}


@router.delete("/admin/{ad_id}")
async def admin_delete(
    ad_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    ad = await db.get(Ad, ad_id)
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    await db.delete(ad)
    await db.commit()
    return {"ok": True}
