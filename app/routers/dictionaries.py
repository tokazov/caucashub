"""
Роутер справочников — /api/dictionaries/* (Трек 9).
Фронт загружает один раз при старте, не хардкодит.
"""
from fastapi import APIRouter
from app.services.dictionaries import TRUCK_TYPES, PAYMENT_TYPES, ORG_TYPES, COUNTRIES

router = APIRouter()


@router.get("/truck-types")
async def get_truck_types():
    """Типы кузовов с локализацией RU/GE."""
    return {"truck_types": TRUCK_TYPES}


@router.get("/payment-types")
async def get_payment_types():
    """Типы оплаты с локализацией RU/GE."""
    return {"payment_types": PAYMENT_TYPES}


@router.get("/org-types")
async def get_org_types():
    """Юридические формы с локализацией RU/GE."""
    return {"org_types": ORG_TYPES}


@router.get("/countries")
async def get_countries():
    """Страны с ISO-кодами, флагами и локализацией RU/GE."""
    return {"countries": COUNTRIES}


@router.get("/all")
async def get_all_dictionaries():
    """Все справочники одним запросом (для инициализации фронта)."""
    return {
        "truck_types":   TRUCK_TYPES,
        "payment_types": PAYMENT_TYPES,
        "org_types":     ORG_TYPES,
        "countries":     COUNTRIES,
    }
