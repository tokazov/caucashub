"""P2 тесты: normalizers + matchers"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_p2_norm.db")
os.environ.setdefault("SECRET_KEY", "test-p2")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

import pytest
from app.services.normalizers import normalize_phone, normalize_tax_id


# Task 7 — Georgian phone format
def test_normalize_phone_georgian_local():
    assert normalize_phone('0551234567') == '+995551234567'

def test_normalize_phone_georgian_with_995():
    assert normalize_phone('995551234567') == '+995551234567'

def test_normalize_phone_georgian_with_plus():
    assert normalize_phone('+995551234567') == '+995551234567'

def test_normalize_phone_russian():
    assert normalize_phone('89991234567') == '+79991234567'


# Task 12 — normalize_tax_id
def test_normalize_tax_id_valid():
    assert normalize_tax_id('123456789') == '123456789'

def test_normalize_tax_id_with_dashes():
    assert normalize_tax_id('12-345-6789') == '123456789'

def test_normalize_tax_id_invalid_returns_input():
    """Невалидный ИНН должен вернуть исходную строку, не None."""
    result = normalize_tax_id('12345')
    assert result == '12345'
    assert result is not None

def test_normalize_tax_id_none():
    assert normalize_tax_id(None) is None


# Task 11 — city normalization
def test_city_normalize_hyphens():
    from app.services.subscription_matcher import _normalize
    assert _normalize('Ростов-на-Дону') == 'ростов на дону'

def test_city_normalize_whitespace():
    from app.services.subscription_matcher import _normalize
    assert _normalize('Нижний  Новгород') == 'нижний новгород'

def test_city_normalize_strips():
    from app.services.subscription_matcher import _normalize
    assert _normalize('  Тбилиси  ') == 'тбилиси'

def test_city_normalize_empty():
    from app.services.subscription_matcher import _normalize
    assert _normalize('') == ''


# Task 8 — Decimal conversion
def test_convert_returns_decimal():
    from decimal import Decimal
    from app.services.exchange_rate import convert_gel_to_usd
    result = convert_gel_to_usd(100, 2.7)
    assert isinstance(result, Decimal)

def test_convert_rounds_half_up():
    from decimal import Decimal
    from app.services.exchange_rate import convert_gel_to_usd
    result = convert_gel_to_usd(Decimal('100'), Decimal('3'))
    assert result == Decimal('33.33')

def test_convert_usd_to_gel_decimal():
    from decimal import Decimal
    from app.services.exchange_rate import convert_usd_to_gel
    result = convert_usd_to_gel(Decimal('10'), Decimal('2.73'))
    assert isinstance(result, Decimal)
    assert result == Decimal('27.30')


# ── N+1 тесты (Task 9 & 10) ──────────────────────────────────────────────────

import os as _os
_os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_p2_n1.db")

@pytest.mark.asyncio
async def test_subscription_matcher_no_n_plus_one():
    """
    batch SELECT users вместо N+1 — проверяем через счётчик SQL запросов.
    При 3 подписчиках должно быть <= 3 SELECT запросов к users (один batch).
    """
    import asyncio
    from unittest.mock import patch, AsyncMock
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select, event, delete
    from app.database import Base
    from app.models.user import User, UserRole, UserPlan
    from app.models.load import Load, LoadStatus, TruckType
    from app.models.subscription import RouteSubscription
    from app.services.subscription_matcher import notify_subscribers
    from passlib.context import CryptContext
    from datetime import datetime, timezone

    pwd = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
    engine = create_async_engine("sqlite+aiosqlite:///./test_n1_sub.db")
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Счётчик SQL запросов к таблице users
    user_select_count = {"n": 0}

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_queries(conn, cursor, statement, params, context, executemany):
        if "FROM users" in statement and "WHERE" in statement and "IN" in statement.upper():
            user_select_count["n"] += 1

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Создаём load owner + 3 перевозчика с подписками
    async with Session() as db:
        owner = User(email="owner@n1.ge", phone="+99511100001",
                     hashed_password=pwd.hash("pass"), role=UserRole.shipper,
                     plan=UserPlan.free, is_active=True, is_deleted=False)
        db.add(owner)
        await db.flush()

        carriers = []
        for i in range(3):
            u = User(email=f"carrier{i}@n1.ge", phone=f"+9955{i}000001",
                     hashed_password=pwd.hash("pass"), role=UserRole.carrier,
                     plan=UserPlan.free, is_active=True, is_deleted=False,
                     telegram_id=f"tg_{i}")
            db.add(u)
            await db.flush()
            sub = RouteSubscription(user_id=u.id, from_city="Tbilisi", to_city="Moscow",
                                    is_active=True, notify_tg=True)
            db.add(sub)
            carriers.append(u)

        load = Load(user_id=owner.id, from_city="Tbilisi", to_city="Moscow",
                    weight_kg=5, cargo_desc="test", status=LoadStatus.active,
                    price_gel=100, truck_type=TruckType.tent,
                    load_date=datetime.now(timezone.utc))
        db.add(load)
        await db.commit()
        await db.refresh(load)

    user_select_count["n"] = 0  # сбрасываем после setup

    with patch("app.services.subscription_matcher._send_tg_notification", new_callable=AsyncMock, return_value=True):
        async with Session() as db:
            await notify_subscribers(load, db)

    # Должен быть ОДИН batch запрос к users (IN), не 3 отдельных
    assert user_select_count["n"] <= 1, \
        f"Ожидался 1 batch SELECT users, получили {user_select_count['n']} запросов (N+1!)"

    await engine.dispose()


@pytest.mark.asyncio
async def test_subscription_matcher_skips_missing_users():
    """Если пользователь удалён между SELECT-ами — graceful skip, не падение."""
    from unittest.mock import patch, AsyncMock
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import delete
    from app.database import Base
    from app.models.user import User, UserRole, UserPlan
    from app.models.load import Load, LoadStatus, TruckType
    from app.models.subscription import RouteSubscription
    from app.services.subscription_matcher import notify_subscribers
    from passlib.context import CryptContext
    from datetime import datetime, timezone

    pwd = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
    engine = create_async_engine("sqlite+aiosqlite:///./test_n1_skip.db")
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as db:
        owner = User(email="owner@skip.ge", phone="+99511200001",
                     hashed_password=pwd.hash("pass"), role=UserRole.shipper,
                     plan=UserPlan.free, is_active=True, is_deleted=False)
        db.add(owner)
        await db.flush()

        ghost = User(email="ghost@skip.ge", phone="+99511200002",
                     hashed_password=pwd.hash("pass"), role=UserRole.carrier,
                     plan=UserPlan.free, is_active=True, is_deleted=False)
        db.add(ghost)
        await db.flush()

        sub = RouteSubscription(user_id=ghost.id, from_city="Tbilisi", to_city="Moscow",
                                is_active=True, notify_tg=True)
        db.add(sub)

        load = Load(user_id=owner.id, from_city="Tbilisi", to_city="Moscow",
                    weight_kg=5, cargo_desc="test", status=LoadStatus.active,
                    price_gel=100, truck_type=TruckType.tent,
                    load_date=datetime.now(timezone.utc))
        db.add(load)
        await db.commit()
        ghost_id = ghost.id
        load_obj = load

    # "Удаляем" пользователя между запросами
    async with Session() as db:
        u = await db.get(User, ghost_id)
        u.is_deleted = True
        await db.commit()

    # Не должно падать — graceful skip
    with patch("app.services.subscription_matcher._send_tg_notification", new_callable=AsyncMock, return_value=True) as mock_tg:
        async with Session() as db:
            result = await notify_subscribers(load_obj, db)

    assert mock_tg.call_count == 0, "Удалённый пользователь не должен получать уведомления"

    await engine.dispose()
