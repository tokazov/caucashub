"""
Роутер сделок: создание, смена статусов, генерация PDF акта.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.deal import Deal
from app.models.user import User
from typing import Optional

STATUS_LABELS = {
    "loading": "Начата загрузка",
    "in_transit": "Груз в пути",
    "delivered": "Груз доставлен",
    "completed": "Сделка завершена",
}

async def notify_deal_status(deal, db, new_status: str):
    """Email уведомление при смене статуса сделки"""
    import httpx
    RESEND_KEY = "re_UesN9evJ_H9Me3arJbM74gL1d2quF2te1"
    label = STATUS_LABELS.get(new_status, new_status)
    
    # Получаем участников
    shipper = await db.get(User, deal.shipper_id)
    carrier = await db.get(User, deal.carrier_id)
    
    # Загружаем груз для маршрута
    from app.models.load import Load
    load = await db.get(Load, deal.load_id)
    route = f"{load.from_city} → {load.to_city}" if load else "—"
    
    recipients = []
    if shipper and shipper.email: recipients.append(shipper.email)
    if carrier and carrier.email: recipients.append(carrier.email)
    
    for email in recipients:
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          <div style="background:#1a1a2e;padding:20px;text-align:center">
            <h2 style="color:#f7b731;margin:0">CaucasHub.ge</h2>
          </div>
          <div style="padding:24px">
            <h3>🔔 Статус сделки изменён</h3>
            <div style="background:#f8f9fa;border-radius:8px;padding:16px;margin:16px 0">
              <b>Сделка:</b> {deal.act_number}<br>
              <b>Маршрут:</b> {route}<br>
              <b>Новый статус:</b> <span style="color:#f7b731;font-weight:700">{label}</span>
            </div>
            <p>Зайдите в <a href="https://caucashub.ge" style="color:#f7b731">личный кабинет</a> → Мои сделки для управления.</p>
          </div>
        </div>
        """
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_KEY}"},
                    json={"from": "CaucasHub <onboarding@resend.dev>", "to": [email],
                          "subject": f"🔔 {label} — {route} ({deal.act_number})", "html": html},
                    timeout=8
                )
        except:
            pass
, DealStatus
from app.models.load import Load, LoadStatus
from app.models.response import Response as LoadResponse, ResponseStatus
from app.models.user import User
from app.routers.loads import require_user
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
    await notify_deal_status(deal, db, data.status)
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
    await notify_deal_status(deal, db, data.status)
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
    await notify_deal_status(deal, db, data.status)
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
        "shipper_inn":     shipper.inn if shipper and shipper.inn else "—",
        "shipper_phone":   shipper.phone if shipper else "—",
        "shipper_email":   shipper.email if shipper else "—",
        # Перевозчик
        "carrier_name":    carrier.company_name or carrier.email if carrier else "—",
        "carrier_inn":     carrier.inn if carrier and carrier.inn else "—",
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


# ── Экспорт сделок для rs.ge ─────────────────────────────────────────
from fastapi.responses import StreamingResponse
import csv, io
from datetime import timezone

@router.get("/export")
async def export_deals(
    format: str = "json",   # json | csv
    status: str = "completed",
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    """Экспорт сделок для бухгалтерии / rs.ge.
    format=json → JSON  |  format=csv → CSV файл"""
    result = await db.execute(
        select(Deal).where(
            (Deal.shipper_id == user_id) | (Deal.carrier_id == user_id)
        ).order_by(Deal.completed_at.desc())
    )
    all_deals = result.scalars().all()

    # Фильтрация по статусу
    if status != "all":
        try:
            st = DealStatus(status)
            all_deals = [d for d in all_deals if d.status == st]
        except ValueError:
            pass

    # Загружаем данные о грузах батчем
    load_ids = list({d.load_id for d in all_deals})
    load_map = {}
    if load_ids:
        lr = await db.execute(select(Load).where(Load.id.in_(load_ids)))
        for l in lr.scalars().all():
            load_map[l.id] = l

    # Загружаем данные пользователей
    uids = list({d.shipper_id for d in all_deals} | {d.carrier_id for d in all_deals})
    user_map = {}
    if uids:
        ur = await db.execute(select(User).where(User.id.in_(uids)))
        for u in ur.scalars().all():
            user_map[u.id] = u

    def _fmt(dt):
        if not dt: return ""
        return dt.strftime("%d.%m.%Y") if hasattr(dt, 'strftime') else str(dt)[:10]

    def _company(uid):
        u = user_map.get(uid)
        return (u.company_name or u.email) if u else "—"

    rows = []
    total_gel = 0.0
    total_usd = 0.0
    for d in all_deals:
        load = load_map.get(d.load_id)
        price = d.agreed_price or 0
        cur = d.currency or "GEL"
        row = {
            "act_number":    d.act_number or f"CH-{d.id}",
            "date":          _fmt(d.completed_at or d.created_at),
            "shipper":       _company(d.shipper_id),
            "carrier":       _company(d.carrier_id),
            "from_city":     load.from_city if load else "—",
            "to_city":       load.to_city   if load else "—",
            "cargo_desc":    (load.cargo_desc or "") if load else "",
            "weight_kg":     load.weight_kg if load else 0,
            "amount":        price,
            "currency":      cur,
            "payment_type":  (load.payment_type or "") if load else "",
            "shipper_inn":   (user_map.get(d.shipper_id).inn or "") if user_map.get(d.shipper_id) else "",
            "carrier_inn":   (user_map.get(d.carrier_id).inn or "") if user_map.get(d.carrier_id) else "",
            "status":        d.status.value if hasattr(d.status, 'value') else str(d.status),
            "deal_id":       d.id,
            "load_id":       d.load_id,
            "loading_date":  _fmt(d.loading_at),
            "delivery_date": _fmt(d.delivered_at),
        }
        rows.append(row)
        if cur == "GEL": total_gel += price
        else:            total_usd += price

    # ── JSON ──
    if format == "json":
        from datetime import datetime
        return {
            "company":      _company(user_id),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "platform":     "CaucasHub.ge",
            "status_filter": status,
            "total_gel":    total_gel,
            "total_usd":    total_usd,
            "count":        len(rows),
            "deals":        rows,
        }

    # ── CSV ──
    buf = io.StringIO()
    fields = ["act_number","date","shipper","shipper_inn","carrier","carrier_inn",
              "from_city","to_city","cargo_desc","weight_kg","amount","currency",
              "payment_type","status","deal_id","load_id","loading_date","delivery_date"]
    w = csv.DictWriter(buf, fieldnames=fields, delimiter=";")
    w.writeheader()
    w.writerows(rows)

    # Итоги
    buf.write(f"\n;;;;;;;;;;;\n")
    if total_gel: buf.write(f"ИТОГО GEL;;;;;;;;{total_gel:.2f};GEL;;;\n")
    if total_usd: buf.write(f"ИТОГО USD;;;;;;;;{total_usd:.2f};USD;;;\n")

    csv_bytes = buf.getvalue().encode("utf-8-sig")  # utf-8-sig для Excel/Windows
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="caucashub_export_{_fmt(None) or "all"}.csv"'},
    )


class RatingRequest(BaseModel):
    score: int  # 1-5
    comment: Optional[str] = None

@router.post("/{deal_id}/rate")
async def rate_deal(
    deal_id: int,
    data: RatingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Оценить сделку после завершения"""
    if data.score < 1 or data.score > 5:
        raise HTTPException(400, "Score must be 1-5")
    
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal or deal.status != "completed":
        raise HTTPException(400, "Deal not found or not completed")
    if current_user.id not in [deal.shipper_id, deal.carrier_id]:
        raise HTTPException(403, "Not your deal")
    
    # Определяем кого оцениваем
    rated_id = deal.carrier_id if current_user.id == deal.shipper_id else deal.shipper_id
    rated_user = await db.get(User, rated_id)
    if rated_user:
        # Обновляем рейтинг (скользящее среднее)
        old_rating = rated_user.rating or 50
        old_trips = rated_user.trips_count or 0
        # rating хранится как 0-50 (5.0 * 10)
        new_rating = round((old_rating * old_trips + data.score * 10) / (old_trips + 1))
        rated_user.rating = min(50, max(0, new_rating))
        rated_user.trips_count = old_trips + 1
        await db.commit()
    
    return {"ok": True, "rated_user_id": rated_id, "score": data.score}
