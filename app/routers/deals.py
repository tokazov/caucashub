"""
Роутер сделок: создание, смена статусов, генерация PDF акта.
"""
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import Response as FastAPIResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import load_only
from app.database import get_db
from app.models.deal import Deal, DealStatus
from app.models.deal_review import DealReview
from app.models.deal_act_archive import DealActArchive
from app.models.load import Load, LoadStatus
from app.models.transport_offer import TransportOffer
from app.models.transport_request import TransportRequest
from app.models.response import Response as LoadResponse, ResponseStatus
from app.models.user import User, UserRole
from app.routers.loads import require_user
from app.routers.auth import require_user as require_authenticated_user
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import IntegrityError
from app.pdf_utils import generate_act_pdf
from app.services.notifications import enqueue_event
from app.services.document_names import document_readiness, require_document_names, raise_missing_names
from app.services.deal_act_archive import (
    create_bundle, metadata as archive_metadata, validate_bundle, validate_payload,
    unavailable as archive_unavailable,
)
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from typing import Optional
from datetime import datetime, timedelta, timezone

router = APIRouter()


def _act_number(deal_id: int) -> str:
    year = datetime.utcnow().year
    return f"CH-{year}-{deal_id:04d}"



def _iso_utc(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _export_timestamp(value):
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def deal_to_dict(d: Deal) -> dict:
    return {
        "id":                    d.id,
        "load_id":               d.load_id,
        "transport_offer_id":    d.transport_offer_id,
        "deal_source":           d.deal_source,          # 'cargo' | 'transport'
        "shipper_id":            d.shipper_id,
        "carrier_id":            d.carrier_id,
        "status":                d.status.value if hasattr(d.status, "value") else str(d.status),
        "agreed_price":          d.agreed_price,
        "currency":              d.currency,
        "created_at":            _iso_utc(d.created_at),
        "loading_at":            _iso_utc(d.loading_at),
        "delivered_at":          _iso_utc(d.delivered_at),
        "completed_at":          _iso_utc(d.completed_at),
        "shipper_confirmed":     d.shipper_confirmed,
        "carrier_confirmed":     d.carrier_confirmed,
        "act_number":            d.act_number,
        "notes":                 d.notes,
    }



def _status_value(deal: Deal) -> str:
    return deal.status.value if hasattr(deal.status, "value") else str(deal.status)


def _review_to_dict(review: DealReview | None) -> dict | None:
    if review is None:
        return None
    created = review.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {"score": review.score, "comment": review.comment,
            "public_comment": bool(review.public_comment),
            "created_at": created.isoformat() if created is not None else None}


def _review_fields(deal: Deal, viewer_id: int, reviews: list[DealReview]) -> dict:
    own = next((review for review in reviews if review.rater_id == viewer_id), None)
    peer = next((review for review in reviews if review.rater_id != viewer_id), None)
    # Old rated rows contain no attributable rater/score/comment. Do not guess.
    legacy = _status_value(deal) == "rated" and not reviews
    return {
        "viewer_has_rated": own is not None,
        "viewer_can_rate": (viewer_id in (deal.shipper_id, deal.carrier_id)
                            and _status_value(deal) in ("completed", "rated")
                            and own is None and not legacy),
        "legacy_rating": legacy,
        "my_review": _review_to_dict(own),
        "counterparty_review": _review_to_dict(peer),
    }


async def _deal_reviews(db: AsyncSession, deal_id: int) -> list[DealReview]:
    result = await db.execute(select(DealReview).where(DealReview.deal_id == deal_id)
                              .order_by(DealReview.id))
    return list(result.scalars().all())


async def _act_archives(db: AsyncSession, ids: list[int], *, payload=False):
    if not ids:
        return {}
    fields = [DealActArchive.deal_id, DealActArchive.schema_version, DealActArchive.issued_at]
    if payload:
        fields.extend([DealActArchive.payload, DealActArchive.payload_sha256])
    result = await db.execute(select(DealActArchive).where(DealActArchive.deal_id.in_(ids))
                              .options(load_only(*fields)))
    return {item.deal_id: item for item in result.scalars().all()}


def _document_state(archive, shipper, carrier, viewer_id):
    info = archive_metadata(archive)
    readiness = {'ready': True, 'missing_parties': []} if info['issued'] else document_readiness(shipper, carrier, viewer_id)
    return {'document_archive': info, 'document_readiness': readiness}


async def _locked_deal(db: AsyncSession, deal_id: int, user_id: int) -> Deal:
    result = await db.execute(select(Deal).where(Deal.id == deal_id)
                              .with_for_update().execution_options(populate_existing=True))
    deal = result.scalar_one_or_none()
    if deal is None:
        raise HTTPException(404, "Сделка не найдена")
    if user_id not in (deal.shipper_id, deal.carrier_id):
        raise HTTPException(403, "Нет доступа к этой сделке")
    return deal


async def _locked_users(db: AsyncSession, ids: list[int]) -> list[User]:
    # Refresh rows already loaded through Deal's selectin relationships after locking.
    result = await db.execute(select(User).where(User.id.in_(sorted(set(ids))))
                              .order_by(User.id).with_for_update()
                              .execution_options(populate_existing=True))
    return list(result.scalars().all())


async def _deal_notification_data(db: AsyncSession, deal: Deal) -> dict:
    source = (await db.get(TransportOffer, deal.transport_offer_id)
              if deal.transport_offer_id else await db.get(Load, deal.load_id))
    return {
        "source": deal.deal_source, "load_id": deal.load_id,
        "transport_offer_id": deal.transport_offer_id,
        "transport_request_id": deal.transport_request_id, "response_id": deal.response_id,
        "deal_id": deal.id, "deal_number": deal.act_number or _act_number(deal.id),
        "from_city": source.from_city if source else None,
        "to_city": source.to_city if source else None,
        "price": float(deal.agreed_price) if deal.agreed_price is not None else None,
        "currency": deal.currency or "GEL",
    }


async def _enqueue_deal_created(db: AsyncSession, deal: Deal, actor_id: int):
    await enqueue_event(
        db, event_key=f"deal:{deal.id}:created", kind="deal_created",
        recipient_ids=[deal.shipper_id, deal.carrier_id], actor_id=actor_id,
        data=await _deal_notification_data(db, deal),
    )


async def _confirm_deal(db: AsyncSession, deal: Deal, user_id: int) -> bool:
    from app.services.audit_log import log_status_change

    previous = _status_value(deal)
    if previous in ("completed", "rated"):
        return False
    if previous not in ("confirmed", "loading", "in_transit", "delivered"):
        raise HTTPException(400, "Нельзя подтвердить доставку из статуса " + previous)
    already_confirmed = deal.shipper_confirmed if user_id == deal.shipper_id else deal.carrier_confirmed
    if already_confirmed:
        return False
    now = datetime.now(timezone.utc)
    if user_id == deal.shipper_id:
        deal.shipper_confirmed = True
    else:
        deal.carrier_confirmed = True
    if deal.delivered_at is None:
        deal.delivered_at = now
    completed = bool(deal.shipper_confirmed and deal.carrier_confirmed)
    target = "completed" if completed else "delivered"
    deal.status = DealStatus(target)
    if completed:
        deal.completed_at = now
        if not deal.act_number:
            deal.act_number = _act_number(deal.id)
        for participant in await _locked_users(db, [deal.shipper_id, deal.carrier_id]):
            participant.completed_deals_count = (participant.completed_deals_count or 0) + 1
            participant.trips_count = (participant.trips_count or 0) + 1
    if target != previous:
        await log_status_change(db, "deal", deal.id, previous, target, user_id,
                                reason="delivery_confirmed")
    data = await _deal_notification_data(db, deal)
    if completed:
        await enqueue_event(
            db, event_key=f"deal:{deal.id}:completed", kind="deal_completed",
            recipient_ids=[deal.shipper_id, deal.carrier_id], actor_id=user_id, data=data,
        )
    else:
        event_key = f"deal:{deal.id}:confirmed:{user_id}"
        peer_id = deal.carrier_id if user_id == deal.shipper_id else deal.shipper_id
        await enqueue_event(db, event_key=event_key, kind="delivery_waiting",
                            recipient_ids=[user_id], actor_id=user_id, data=data)
        await enqueue_event(db, event_key=event_key, kind="delivery_confirmation_required",
                            recipient_ids=[peer_id], actor_id=user_id, data=data)
    return completed


async def _mutation_dict(db: AsyncSession, deal: Deal, user_id: int) -> dict:
    result = deal_to_dict(deal)
    result.update(_review_fields(deal, user_id, await _deal_reviews(db, deal.id)))
    return result


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
    current_user: User = Depends(require_user),
):
    user_id = current_user.id
    load = (await db.execute(select(Load).where(Load.id == data.load_id)
                             .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if load is None:
        raise HTTPException(404, "Груз не найден")
    if load.user_id != user_id:
        raise HTTPException(403, "Это не ваш груз")
    existing = (await db.execute(select(Deal.id).where(
        Deal.load_id == load.id, Deal.status != DealStatus.canceled))).first()
    if existing:
        raise HTTPException(409, "Сделка для этого груза уже существует")
    if load.status != LoadStatus.active or getattr(load, "is_demo", False):
        raise HTTPException(400, "Груз недоступен")
    carrier = await db.get(User, data.carrier_id)
    if (carrier is None or carrier.id == user_id or carrier.is_deleted or not carrier.is_active
            or carrier.role not in (UserRole.carrier, UserRole.both)):
        raise HTTPException(400, "Выберите существующего перевозчика")
    if data.response_id is not None:
        query = select(LoadResponse).where(LoadResponse.id == data.response_id)
    else:
        # Legacy callers may omit the identifier, but cannot invent carrier consent.
        query = select(LoadResponse).where(
            LoadResponse.load_id == load.id, LoadResponse.user_id == carrier.id,
            LoadResponse.status == ResponseStatus.pending,
        ).order_by(LoadResponse.id).limit(1)
    resp = (await db.execute(query.with_for_update()
                             .execution_options(populate_existing=True))).scalar_one_or_none()
    if resp is None or resp.load_id != load.id or resp.user_id != carrier.id:
        raise HTTPException(400, "Выберите существующий отклик этого перевозчика на ваш груз")
    if resp.status != ResponseStatus.pending:
        raise HTTPException(400, "Отклик уже обработан")
    resp.status = ResponseStatus.accepted
    others = (await db.execute(select(LoadResponse).where(
        LoadResponse.load_id == load.id, LoadResponse.status == ResponseStatus.pending)
        .order_by(LoadResponse.id).with_for_update()
        .execution_options(populate_existing=True))).scalars().all()
    from app.routers.responses import _enqueue_response_rejected
    for other in others:
        other.status = ResponseStatus.rejected
        await _enqueue_response_rejected(db, other, load, user_id)
    load.status = LoadStatus.taken
    deal = Deal(load_id=load.id, shipper_id=user_id, carrier_id=carrier.id,
                response_id=resp.id,
                agreed_price=data.agreed_price or (load.price_gel or load.price_usd),
                currency=data.currency, notes=data.notes, status=DealStatus.confirmed)
    db.add(deal)
    await db.flush()
    deal.act_number = _act_number(deal.id)
    await _enqueue_deal_created(db, deal, user_id)
    await db.commit()
    await db.refresh(deal)
    return deal_to_dict(deal)


# ── Сменить статус сделки ────────────────────────────────────────────
class UpdateStatusRequest(BaseModel):
    status: str
    notes: Optional[str] = None


@router.post("/{deal_id}/status")
async def update_status(
    deal_id: int,
    data: UpdateStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.services.state_machine import validate_transition
    from app.services.audit_log import log_status_change

    user_id = current_user.id
    deal = await _locked_deal(db, deal_id, user_id)
    previous, target = _status_value(deal), data.status
    if target in ("completed", "rated"):
        raise HTTPException(400, "Используйте подтверждение доставки или оценку сделки")
    if target in ("delivered", "delivered_shipper", "delivered_carrier"):
        if target == "delivered_shipper" and user_id != deal.shipper_id:
            raise HTTPException(403, "Только грузовладелец может подтвердить получение")
        if target == "delivered_carrier" and user_id != deal.carrier_id:
            raise HTTPException(403, "Только перевозчик может подтвердить доставку")
        await _confirm_deal(db, deal, user_id)
    else:
        validate_transition("deal", previous, target)
        if target in ("loading", "in_transit"):
            if user_id != deal.carrier_id:
                raise HTTPException(403, "Только перевозчик может изменить статус")
            deal.status = DealStatus(target)
            if target == "loading":
                deal.loading_at = datetime.now(timezone.utc)
        elif target == "canceled":
            deal.status = DealStatus.canceled
        else:
            raise HTTPException(400, "Неизвестный статус: " + target)
        await log_status_change(db, "deal", deal.id, previous, target, user_id)
    if data.notes:
        deal.notes = data.notes
    await db.flush()
    payload = await _mutation_dict(db, deal, user_id)
    await db.commit()
    return payload


def _send_completed_emails(shipper, carrier, deal_num: str):
    """Compatibility no-op: completion delivery is handled by the transactional outbox."""
    return None


# ── Подтвердить доставку ─────────────────────────────────────────────
@router.post("/{deal_id}/confirm")
async def confirm_delivery(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    deal = await _locked_deal(db, deal_id, current_user.id)
    await _confirm_deal(db, deal, current_user.id)
    await db.flush()
    payload = await _mutation_dict(db, deal, current_user.id)
    await db.commit()
    return payload


# ── Получить мои сделки ──────────────────────────────────────────────
@router.get("/my")
async def get_my_deals(
    limit:  int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    user_id = current_user.id
    # Общее кол-во
    count_res = await db.execute(
        select(func.count()).where(
            (Deal.shipper_id == user_id) | (Deal.carrier_id == user_id)
        )
    )
    total = count_res.scalar_one()

    result = await db.execute(
        select(Deal).where(
            (Deal.shipper_id == user_id) | (Deal.carrier_id == user_id)
        ).order_by(Deal.created_at.desc()).limit(limit).offset(offset)
    )
    deals = result.scalars().all()
    archives = await _act_archives(db, [d.id for d in deals])
    grouped_reviews = {}
    if deals:
        review_result = await db.execute(select(DealReview).where(DealReview.deal_id.in_([d.id for d in deals])))
        for review in review_result.scalars().all():
            grouped_reviews.setdefault(review.deal_id, []).append(review)
    enriched = []
    for d in deals:
        base = deal_to_dict(d)
        base.update(_review_fields(d, user_id, grouped_reviews.get(d.id, [])))
        # Загружаем груз
        load_r = await db.execute(select(Load).where(Load.id == d.load_id))
        load = load_r.scalar_one_or_none()
        # Загружаем пользователей
        sh_r = await db.execute(select(User).where(User.id == d.shipper_id))
        sh = sh_r.scalar_one_or_none()
        ca_r = await db.execute(select(User).where(User.id == d.carrier_id))
        ca = ca_r.scalar_one_or_none()
        base.update(_document_state(archives.get(d.id), sh, ca, user_id))
        base["deal_number"] = d.act_number or _act_number(d.id)
        offer = await db.get(TransportOffer, d.transport_offer_id) if not load and d.transport_offer_id else None
        transport_request = await db.get(TransportRequest, d.transport_request_id) if offer and d.transport_request_id else None
        route = load or offer
        base["load_from"]   = route.from_city if route else "—"
        base["load_to"]     = route.to_city if route else "—"
        base["load_desc"]   = load.cargo_desc if load else (transport_request.cargo_description if transport_request else "")
        base["load_kg"]     = load.weight_kg if load else ((transport_request.weight_kg or 0) if transport_request else 0)
        base["price"]       = d.agreed_price
        from app.services.user_display import display_name, display_phone
        # ADR-013 B: контакты видны участнику сделки (viewer = shipper или carrier)
        viewer_is_participant = (user_id == d.shipper_id or user_id == d.carrier_id)
        # 5.2.5: ИНН не раскрывается через deals API
        base["shipper"] = {
            "id":    sh.id if sh else None,
            "name":  display_name(sh) if sh else "—",
            "phone": display_phone(sh) if (sh and viewer_is_participant) else None,
            "email": sh.email if (sh and viewer_is_participant) else None,
        } if sh else {}
        base["carrier"] = {
            "id":    ca.id if ca else None,
            "name":  display_name(ca) if ca else "—",
            "phone": display_phone(ca) if (ca and viewer_is_participant) else None,
            "email": ca.email if (ca and viewer_is_participant) else None,
        } if ca else {}
        enriched.append(base)
    return {"deals": enriched, "total": total, "limit": limit, "offset": offset}


# ── Скачать PDF акт ──────────────────────────────────────────────────

async def _act_current_user(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    # The normal verifier also enforces account deletion/blocking/password revocation.
    raw = None
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            raw = credentials.strip()
    if not raw:
        raw = token
    if not raw:
        raise HTTPException(401, "Authorization required")
    return await require_authenticated_user(
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw), db=db)


def _act_truck_label(value, language: str) -> str:
    from app.services.dictionaries import TRUCK_TYPES

    code = str(getattr(value, "value", value) or "").lower()
    code = {"open": "bort", "autovoz": "auto", "tanker": "cistern"}.get(code, code)
    labels = {item["id"]: item["label_ge" if language == "ge" else "label_ru"]
              for item in TRUCK_TYPES}
    extra = {
        "reftent": ("Рефтент", "რეფტენტი"), "megatent": ("Мегатент", "მეგატენტი"),
        "evacuator": ("Эвакуатор", "ევაკუატორი"), "cistern": ("Цистерна", "ცისტერნა"),
        "grain": ("Зерновоз", "მარცვლეულის გადამზიდი"), "dump": ("Самосвал", "თვითმცლელი"),
    }
    if code in extra:
        return extra[code][1 if language == "ge" else 0]
    return labels.get(code, code or "—")


def _act_payload(deal, shipper, carrier, load, offer, request, names, issued_at):
    """Capture every rendered/accounting value once; do not archive email."""
    from app.services.user_display import display_phone
    route = load or offer
    document = {
        'act_number': deal.act_number or _act_number(deal.id), 'deal_id': deal.id,
        'created_at': deal.created_at, 'completed_at': deal.completed_at, 'shipper_name': names['shipper'],
        'shipper_inn': shipper.inn or '—', 'shipper_phone': display_phone(shipper) or '—',
        'carrier_name': names['carrier'], 'carrier_inn': carrier.inn or '—',
        'carrier_phone': display_phone(carrier) or '—',
        'from_city': route.from_city if route else '—', 'to_city': route.to_city if route else '—',
        'cargo_desc': load.cargo_desc if load else (request.cargo_description if request else '—'),
        'weight_kg': load.weight_kg if load else (request.weight_kg if request and request.weight_kg is not None else '—'),
        'agreed_price': deal.agreed_price if deal.agreed_price is not None else 0,
        'currency': deal.currency or 'GEL', 'loading_at': deal.loading_at,
        'delivered_at': deal.delivered_at, 'generated_at': issued_at,
    }
    def date(value):
        return value.strftime('%d.%m.%Y') if value else ''
    accounting = {
        'act_number': document['act_number'], 'date': date(deal.completed_at or deal.created_at),
        'shipper': names['shipper'], 'shipper_inn': document['shipper_inn'],
        'carrier': names['carrier'], 'carrier_inn': document['carrier_inn'],
        'from_city': document['from_city'], 'to_city': document['to_city'],
        'cargo_desc': document['cargo_desc'], 'weight_kg': document['weight_kg'],
        'amount': document['agreed_price'], 'currency': document['currency'],
        'payment_type': (load.payment_type or '') if load else '', 'deal_id': deal.id,
        'deal_source': deal.deal_source, 'load_id': deal.load_id,
        'transport_offer_id': deal.transport_offer_id,
        'loading_date': date(deal.loading_at), 'delivery_date': date(deal.delivered_at),
    }
    return {'document': document, 'accounting': accounting,
            'truck_labels': {language: _act_truck_label(route.truck_type if route else None, language)
                             for language in ('ru', 'ge')}}


async def _rollback_act(db):
    """Best-effort cleanup never exposes a failed private INSERT's parameters."""
    try:
        await db.rollback()
        return True
    except Exception:
        return False


@router.get("/{deal_id}/act.pdf")
async def download_act(
    deal_id: int,
    lang: Optional[str] = Query("ru"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_act_current_user),
):
    viewer_id = current_user.id
    # A deal lock serializes the first issue on PostgreSQL. The archive primary
    # key also prevents two SQLite requests from overwriting each other's bundle.
    deal = await _locked_deal(db, deal_id, viewer_id)
    archive = await db.get(DealActArchive, deal_id)
    if archive is None:
        if (_status_value(deal) not in ('completed', 'rated')
                or not deal.shipper_confirmed or not deal.carrier_confirmed):
            raise HTTPException(400, "Акт доступен после подтверждения доставки обеими сторонами")
        try:
            participants = {user.id: user for user in await _locked_users(db, [deal.shipper_id, deal.carrier_id])}
            shipper, carrier = participants.get(deal.shipper_id), participants.get(deal.carrier_id)
            viewer = participants.get(viewer_id)
            if viewer is None or viewer.is_deleted or not viewer.is_active:
                raise HTTPException(403, 'Нет доступа')
            names = require_document_names(shipper, carrier, viewer_id)
            load = await db.get(Load, deal.load_id, populate_existing=True) if deal.load_id else None
            offer = await db.get(TransportOffer, deal.transport_offer_id, populate_existing=True) if deal.transport_offer_id else None
            request = await db.get(TransportRequest, deal.transport_request_id, populate_existing=True) if deal.transport_request_id else None
            issued_at = datetime.now(timezone.utc)
            payload = _act_payload(deal, shipper, carrier, load, offer, request, names, issued_at)
            archive = create_bundle(deal_id, payload, issued_at, generate_act_pdf)
            db.add(archive)
            await db.commit()
        except IntegrityError:
            if not await _rollback_act(db):
                raise archive_unavailable() from None
            # Never rewrite a winner, even when its contents are corrupt.
            try:
                await _locked_deal(db, deal_id, viewer_id)
                archive = await db.get(DealActArchive, deal_id)
            except HTTPException as error:
                raise error from None
            except Exception:
                raise archive_unavailable() from None
            if archive is None:
                raise archive_unavailable() from None
        except HTTPException as error:
            await _rollback_act(db)
            raise error from None
        except Exception:
            # DBAPI errors can carry SQL bind parameters including the private
            # payload and PDFs. Never let them escape into an ASGI traceback.
            await _rollback_act(db)
            raise archive_unavailable() from None
        except BaseException as error:
            await _rollback_act(db)
            raise error from None
    payload = validate_bundle(archive, deal_id)
    language = lang if lang in ('ru', 'ge') else 'ru'
    pdf_bytes = getattr(archive, language + '_pdf')
    import re
    act_number = str(payload['document']['act_number'])
    safe_number = act_number if re.fullmatch(r'[A-Za-z0-9_.-]+', act_number) else str(deal_id)
    return FastAPIResponse(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="act_{safe_number}.pdf"',
                 'Cache-Control': 'private, no-store', 'Pragma': 'no-cache',
                 'X-Act-Issued-At': archive_metadata(archive)['issued_at']},
    )


# ── Экспорт сделок для rs.ge ─────────────────────────────────────────

@router.get("/export")
async def export_deals(
    format: str = "json",   # json | csv
    status: str = "all",
    date_from: Optional[str] = Query(None, alias="from"),   # 12.2.4: фильтр по периоду YYYY-MM-DD
    date_to:   Optional[str] = Query(None, alias="to"),     # 12.2.4: фильтр по периоду YYYY-MM-DD
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Экспорт сделок для бухгалтерии / rs.ge.
    format=json → JSON  |  format=csv → CSV файл
    Поддерживает фильтрацию: from=YYYY-MM-DD, to=YYYY-MM-DD"""
    user_id = current_user.id
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

    archives = await _act_archives(db, [d.id for d in all_deals], payload=format != 'json')
    archived_payloads = {identity: validate_payload(archive, identity)
                         for identity, archive in archives.items()} if format != 'json' else {}

    def period_stamp(deal):
        frozen = archived_payloads.get(deal.id)
        if frozen:
            value = frozen['document']['completed_at'] or frozen['document']['created_at']
            return _export_timestamp(datetime.fromisoformat(value)) if value else None
        return _export_timestamp(deal.completed_at or deal.created_at)

    # 12.2.4: Фильтрация по периоду дат
    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            all_deals = [d for d in all_deals if (stamp := period_stamp(d)) is not None and stamp >= df]
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            all_deals = [d for d in all_deals if (stamp := period_stamp(d)) is not None and stamp < dt]
        except (ValueError, OverflowError):
            pass

    # Загружаем данные о грузах батчем
    load_ids = [d.load_id for d in all_deals if d.load_id]
    load_map = {}
    if load_ids:
        lr = await db.execute(select(Load).where(Load.id.in_(load_ids)))
        for load_item in lr.scalars().all():
            load_map[load_item.id] = load_item

    # Загружаем TransportOffer для транспортных сделок (ADR-016.7)
    from app.models.transport_offer import TransportOffer
    offer_ids = [d.transport_offer_id for d in all_deals if d.transport_offer_id]
    offer_map = {}
    if offer_ids:
        or_ = await db.execute(select(TransportOffer).where(TransportOffer.id.in_(offer_ids)))
        for o in or_.scalars().all():
            offer_map[o.id] = o

    request_ids = [d.transport_request_id for d in all_deals if d.transport_offer_id and d.transport_request_id]
    request_map = {}
    if request_ids:
        requested = await db.execute(select(TransportRequest).where(TransportRequest.id.in_(request_ids)))
        request_map = {item.id: item for item in requested.scalars().all()}

    # Загружаем данные пользователей
    uids = list({d.shipper_id for d in all_deals} | {d.carrier_id for d in all_deals})
    user_map = {}
    if uids:
        ur = await db.execute(select(User).where(User.id.in_(uids)))
        for u in ur.scalars().all():
            user_map[u.id] = u

    if format != 'json':
        missing = []
        for deal in all_deals:
            if deal.id in archived_payloads:
                continue
            for item in document_readiness(user_map.get(deal.shipper_id), user_map.get(deal.carrier_id), user_id)['missing_parties']:
                if item not in missing:
                    missing.append(item)
        if missing:
            raise_missing_names(missing)

    def _fmt(dt):
        if not dt:
            return ""
        return dt.strftime("%d.%m.%Y") if hasattr(dt, 'strftime') else str(dt)[:10]

    def _company(uid):
        from app.services.user_display import display_name as _dn
        u = user_map.get(uid)
        return _dn(u) if u else "—"

    rows = []
    from decimal import Decimal as _D
    total_gel = _D("0")
    total_usd = _D("0")
    for d in all_deals:
        # ADR-016.7: route берётся из Load (cargo-путь) или TransportOffer (transport-путь)
        load  = load_map.get(d.load_id) if d.load_id else None
        offer = offer_map.get(d.transport_offer_id) if d.transport_offer_id else None
        accepted_request = request_map.get(d.transport_request_id)
        source = offer if offer else load   # transport_offer_id приоритетнее
        price = d.agreed_price or 0
        cur = d.currency or "GEL"
        document_state = _document_state(archives.get(d.id), user_map.get(d.shipper_id), user_map.get(d.carrier_id), user_id)
        names = require_document_names(user_map.get(d.shipper_id), user_map.get(d.carrier_id), user_id) if format != 'json' and d.id not in archived_payloads else None
        row = {
            "act_number":    d.act_number or _act_number(d.id),
            "date":          _fmt(d.completed_at or d.created_at),
            "shipper":       names['shipper'] if names else _company(d.shipper_id),
            "carrier":       names['carrier'] if names else _company(d.carrier_id),
            **document_state,
            "from_city":     source.from_city if source else "—",
            "to_city":       source.to_city   if source else "—",
            "cargo_desc":    (load.cargo_desc or "") if load else (accepted_request.cargo_description if accepted_request else "—"),
            "weight_kg":     load.weight_kg if load else (accepted_request.weight_kg if accepted_request and accepted_request.weight_kg is not None else "—"),
            "amount":        price,
            "currency":      cur,
            "payment_type":  (load.payment_type or "") if load else "",
            "shipper_inn":   (user_map.get(d.shipper_id).inn or "") if user_map.get(d.shipper_id) else "",
            "carrier_inn":   (user_map.get(d.carrier_id).inn or "") if user_map.get(d.carrier_id) else "",
            "status":        d.status.value if hasattr(d.status, 'value') else str(d.status),
            "deal_id":       d.id,
            "deal_source":   d.deal_source,   # ADR-016.7
            "load_id":       d.load_id,
            "transport_offer_id": d.transport_offer_id,
            "loading_date":  _fmt(d.loading_at),
            "delivery_date": _fmt(d.delivered_at),
        }
        if d.id in archived_payloads:
            row.update(archived_payloads[d.id]['accounting'])
        price, cur = _D(str(row['amount'])), row['currency']
        rows.append(row)
        if cur == "GEL":
            total_gel += price
        else:
            total_usd += price

    # ── JSON ──
    if format == "json":
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
    w = csv.DictWriter(buf, fieldnames=fields, delimiter=";", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)

    # Итоги
    buf.write("\n;;;;;;;;;;;\n")
    if total_gel:
        buf.write(f"ИТОГО GEL;;;;;;;;{total_gel:.2f};GEL;;;\n")
    if total_usd:
        buf.write(f"ИТОГО USD;;;;;;;;{total_usd:.2f};USD;;;\n")

    csv_bytes = buf.getvalue().encode("utf-8-sig")  # utf-8-sig для Excel/Windows
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="caucashub_export_{_fmt(None) or "all"}.csv"'},
    )


class RatingRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=2000)
    public_comment: StrictBool = False

    @field_validator("score", mode="before")
    @classmethod
    def reject_boolean_score(cls, value):
        if isinstance(value, bool):
            raise ValueError("Оценка должна быть целым числом от 1 до 5")
        return value

    @field_validator("comment", mode="before")
    @classmethod
    def trim_comment(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


@router.post("/{deal_id}/rate")
async def rate_deal(
    deal_id: int,
    data: RatingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from sqlalchemy import text
    from app.services.audit_log import log_status_change

    user_id = current_user.id
    deal = await _locked_deal(db, deal_id, user_id)
    previous = _status_value(deal)
    if previous not in ("completed", "rated"):
        raise HTTPException(400, "Оценить можно только завершённую сделку")
    reviews = await _deal_reviews(db, deal.id)
    fields = _review_fields(deal, user_id, reviews)
    if fields["legacy_rating"]:
        raise HTTPException(409, "По этой сделке уже есть историческая оценка без данных автора")
    if fields["viewer_has_rated"]:
        raise HTTPException(409, "Вы уже оценили эту сделку")
    recipient_id = deal.carrier_id if user_id == deal.shipper_id else deal.shipper_id
    if recipient_id == user_id:
        raise HTTPException(400, "Нельзя оценивать самого себя")
    people = await _locked_users(db, [recipient_id])
    if not people:
        raise HTTPException(404, "Участник сделки не найден")
    recipient = people[0]
    review = DealReview(deal_id=deal.id, rater_id=user_id, recipient_id=recipient_id,
                        score=data.score, comment=data.comment, public_comment=data.public_comment)
    db.add(review)
    try:
        # The DB unique key is a final guard, including on SQLite without row locks.
        await db.flush()
        await db.refresh(review)
        count = recipient.ratings_received_count or 0
        old_rating = recipient.rating if recipient.rating is not None else 50
        recipient.rating = min(50, max(0, round((old_rating * count + data.score * 10) / (count + 1))))
        recipient.ratings_received_count = count + 1
        if previous == "completed":
            deal.status = DealStatus.rated
            await log_status_change(db, "deal", deal.id, previous, "rated", user_id,
                                    reason="review_created")
            # Preserve the established source lifecycle: completion at first review.
            if deal.load_id:
                await db.execute(text("UPDATE loads SET status = 'completed' WHERE id = :id AND status = 'taken'"),
                                 {"id": deal.load_id})
            elif deal.transport_offer_id:
                await db.execute(text("UPDATE transport_offers SET status = 'completed' WHERE id = :id AND status = 'taken'"),
                                 {"id": deal.transport_offer_id})
        reviews.append(review)
        await db.flush()
        payload = deal_to_dict(deal)
        payload.update(_review_fields(deal, user_id, reviews))
        payload.update({"ok": True, "score": review.score, "deal_id": deal.id})
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "Вы уже оценили эту сделку") from error
    return payload


class ReviewVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    public_comment: StrictBool


@router.patch("/{deal_id}/review-visibility")
async def change_review_visibility(deal_id: int, data: ReviewVisibilityRequest,
                                   db: AsyncSession = Depends(get_db),
                                   current_user: User = Depends(require_user)):
    deal = await _locked_deal(db, deal_id, current_user.id)
    review = (await db.execute(select(DealReview).where(
        DealReview.deal_id == deal.id, DealReview.rater_id == current_user.id).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none()
    if review is None:
        raise HTTPException(404, "Ваш отзыв по этой сделке не найден")
    expected_recipient = deal.carrier_id if current_user.id == deal.shipper_id else deal.shipper_id
    if review.recipient_id != expected_recipient:
        raise HTTPException(409, "Автор и получатель отзыва не согласованы со сделкой")
    review.public_comment = data.public_comment
    await db.commit()
    return {"ok": True, "my_review": _review_to_dict(review)}
