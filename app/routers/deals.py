"""
Роутер сделок: создание, смена статусов, генерация PDF акта.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.deal import Deal, DealStatus
from app.models.load import Load, LoadStatus
from app.models.response import Response as LoadResponse, ResponseStatus
from app.models.user import User
from app.routers.auth import require_user
from app.pdf_utils import generate_act_pdf
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

router = APIRouter()


def _act_number(deal_id: int) -> str:
    year = datetime.utcnow().year
    return f"CH-{year}-{deal_id:04d}"


def deal_to_dict(d: Deal) -> dict:
    return {
        "id":               d.id,
        "load_id":          d.load_id,
        "shipper_id":       d.shipper_id,
        "carrier_id":       d.carrier_id,
        "status":           d.status.value if hasattr(d.status, "value") else str(d.status),
        "agreed_price":     d.agreed_price,
        "currency":         d.currency,
        "created_at":       d.created_at.isoformat() if d.created_at else None,
        "loading_at":       d.loading_at.isoformat() if d.loading_at else None,
        "delivered_at":     d.delivered_at.isoformat() if d.delivered_at else None,
        "completed_at":     d.completed_at.isoformat() if d.completed_at else None,
        "shipper_confirmed": d.shipper_confirmed,
        "carrier_confirmed": d.carrier_confirmed,
        "act_number":       d.act_number,
        "notes":            d.notes,
    }


# ── Создать сделку (грузовладелец принимает отклик) ──────────────────
class CreateDealRequest(BaseModel):
    load_id:      int
    carrier_id:   int
    response_id:  Optional[int] = None
    agreed_price: Optional[float] = None
    currency:     str = "GEL"
    notes:        Optional[str] = None


@router.post("/")
async def create_deal(
    data: CreateDealRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    # Проверяем что груз принадлежит текущему пользователю
    result = await db.execute(select(Load).where(Load.id == data.load_id))
    load = result.scalar_one_or_none()
    if not load:
        raise HTTPException(404, "Груз не найден")
    if load.user_id != user_id:
        raise HTTPException(403, "Это не ваш груз")

    # Помечаем отклик как принятый
    if data.response_id:
        res = await db.execute(select(LoadResponse).where(LoadResponse.id == data.response_id))
        resp = res.scalar_one_or_none()
        if resp:
            resp.status = ResponseStatus.accepted
            # Отклоняем остальные отклики на этот груз
            other = await db.execute(
                select(LoadResponse).where(
                    LoadResponse.load_id == data.load_id,
                    LoadResponse.id != data.response_id,
                    LoadResponse.status == ResponseStatus.pending,
                )
            )
            for o in other.scalars().all():
                o.status = ResponseStatus.rejected

    # Переводим груз в статус taken
    load.status = LoadStatus.taken

    # Создаём сделку
    deal = Deal(
        load_id      = data.load_id,
        shipper_id   = user_id,
        carrier_id   = data.carrier_id,
        response_id  = data.response_id,
        agreed_price = data.agreed_price or (load.price_gel or load.price_usd),
        currency     = data.currency,
        notes        = data.notes,
        status       = DealStatus.confirmed,
    )
    db.add(deal)
    await db.flush()  # получаем id
    deal.act_number = _act_number(deal.id)
    await db.commit()
    await db.refresh(deal)
    return deal_to_dict(deal)


# ── Сменить статус сделки ────────────────────────────────────────────
class UpdateStatusRequest(BaseModel):
    status: str
    notes: Optional[str] = None


@router.put("/{deal_id}/status")
async def update_status(
    deal_id: int,
    data: UpdateStatusRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    if deal.shipper_id != user_id and deal.carrier_id != user_id:
        raise HTTPException(403, "Нет доступа к этой сделке")

    try:
        new_status = DealStatus(data.status)
    except ValueError:
        raise HTTPException(400, f"Неверный статус: {data.status}")

    deal.status = new_status
    now = datetime.now(timezone.utc)

    if new_status == DealStatus.loading:
        deal.loading_at = now
    elif new_status == DealStatus.delivered:
        deal.delivered_at = now
        # Фиксируем подтверждение от той стороны кто нажал
        if user_id == deal.carrier_id:
            deal.carrier_confirmed = True
        else:
            deal.shipper_confirmed = True
    elif new_status == DealStatus.completed:
        deal.completed_at = now
        deal.shipper_confirmed = True
        deal.carrier_confirmed = True

    if data.notes:
        deal.notes = data.notes

    await db.commit()
    await db.refresh(deal)
    return deal_to_dict(deal)


# ── Подтвердить доставку ─────────────────────────────────────────────
@router.post("/{deal_id}/confirm")
async def confirm_delivery(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(404, "Сделка не найдена")

    if user_id == deal.shipper_id:
        deal.shipper_confirmed = True
    elif user_id == deal.carrier_id:
        deal.carrier_confirmed = True
    else:
        raise HTTPException(403, "Нет доступа")

    # Если обе стороны подтвердили → завершаем
    if deal.shipper_confirmed and deal.carrier_confirmed:
        deal.status = DealStatus.completed
        deal.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(deal)
    return deal_to_dict(deal)


# ── Получить мои сделки ──────────────────────────────────────────────
@router.get("/my")
async def get_my_deals(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    result = await db.execute(
        select(Deal).where(
            (Deal.shipper_id == user_id) | (Deal.carrier_id == user_id)
        ).order_by(Deal.created_at.desc())
    )
    deals = result.scalars().all()
    return {"deals": [deal_to_dict(d) for d in deals]}


# ── Скачать PDF акт ──────────────────────────────────────────────────
@router.get("/{deal_id}/act.pdf")
async def download_act(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    if deal.shipper_id != user_id and deal.carrier_id != user_id:
        raise HTTPException(403, "Нет доступа")

    # Загружаем связанные данные
    load_res = await db.execute(select(Load).where(Load.id == deal.load_id))
    load = load_res.scalar_one_or_none()

    shipper_res = await db.execute(select(User).where(User.id == deal.shipper_id))
    shipper = shipper_res.scalar_one_or_none()

    carrier_res = await db.execute(select(User).where(User.id == deal.carrier_id))
    carrier = carrier_res.scalar_one_or_none()

    truck_labels = {
        "tent": "Тент", "ref": "Рефрижератор", "bort": "Борт",
        "termos": "Термос", "gazel": "Фургон", "container": "Контейнер",
        "auto": "Автовоз", "other": "Другой",
    }

    deal_data = {
        "act_number":      deal.act_number or _act_number(deal.id),
        "deal_id":         deal.id,
        "completed_at":    deal.completed_at or deal.delivered_at or deal.created_at,
        # Грузовладелец
        "shipper_name":    shipper.company_name or shipper.email if shipper else "—",
        "shipper_inn":     getattr(shipper, "inn", "—") or "—",
        "shipper_phone":   shipper.phone if shipper else "—",
        "shipper_email":   shipper.email if shipper else "—",
        # Перевозчик
        "carrier_name":    carrier.company_name or carrier.email if carrier else "—",
        "carrier_inn":     getattr(carrier, "inn", "—") or "—",
        "carrier_phone":   carrier.phone if carrier else "—",
        "carrier_email":   carrier.email if carrier else "—",
        # Груз
        "from_city":       load.from_city if load else "—",
        "to_city":         load.to_city if load else "—",
        "cargo_desc":      load.cargo_desc if load else "—",
        "weight_kg":       load.weight_kg if load else "—",
        "truck_type":      truck_labels.get(load.truck_type.value if load else "", "—"),
        # Финансы
        "agreed_price":    deal.agreed_price or 0,
        "currency":        deal.currency or "GEL",
        # Даты
        "loading_at":      deal.loading_at,
        "delivered_at":    deal.delivered_at,
    }

    try:
        pdf_bytes = generate_act_pdf(deal_data)
        filename = f"act_{deal.act_number or deal.id}.pdf"
        return FastAPIResponse(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(500, f"Ошибка генерации PDF: {e}")
