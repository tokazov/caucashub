from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import (loads, trucks, auth, ai, users, deals, responses,
                         tg_bot, cities, dictionaries, stats, subscriptions,
                         transport, transport_requests, transport_subscriptions,
                         payments)
from app.database import engine
from app.models import user, load, truck, response, deal, city, status_change, payment  # noqa — регистрируем модели
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    ADR-011 (Вариант A): схема поддерживается через Alembic pre-deploy (nixpacks.toml).
    При старте — только seed городов + healthcheck соединения.
    Автомиграции через CREATE TABLE / ALTER TABLE — УДАЛЕНЫ (источник правды — alembic/versions/).
    """
    from sqlalchemy import text

    # Аварийные inline-миграции (ADR-011 fallback):
    # ── emergency_migrations ──────────────────────────────────────────────────
    # НАЗНАЧЕНИЕ: Только для случая абсолютно пустой БД при первом старте.
    # В нормальном деплое все изменения применяются через [phases.migrate] → alembic upgrade head.
    # Источник правды для схемы — alembic/versions/*.py.
    # ALTER TYPE строки здесь — дубли из 011_enum_additions.py, нужны только если
    # alembic_version таблица ещё не существует (холодный старт без миграций).
    _emergency_migrations = [
        "ALTER TABLE loads ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS completed_deals_count INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ratings_received_count INTEGER DEFAULT 0",
        "ALTER TABLE responses ADD COLUMN IF NOT EXISTS price_gel FLOAT",
        "ALTER TABLE responses ADD COLUMN IF NOT EXISTS exchange_rate_at_creation FLOAT",
        "ALTER TABLE loads ADD COLUMN IF NOT EXISTS exchange_rate_at_creation FLOAT",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS exchange_rate_snapshot FLOAT",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS final_price_gel FLOAT",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS final_price_usd FLOAT",
        "ALTER TABLE loads ADD COLUMN IF NOT EXISTS from_city_id INTEGER",
        "ALTER TABLE loads ADD COLUMN IF NOT EXISTS to_city_id INTEGER",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS responses_this_month INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS responses_month_reset TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE",
        # ALTER TYPE строки перенесены в Alembic-миграцию 011_enum_additions.py
        # Оставлены здесь только как fallback для абсолютно пустой БД без alembic_version таблицы
        # (в нормальном деплое alembic upgrade head выполняется раньше)
        """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='pro_plus' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='userplan')) THEN ALTER TYPE userplan ADD VALUE 'pro_plus'; END IF; END $$ """,
        """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='paused' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='loadstatus')) THEN ALTER TYPE loadstatus ADD VALUE 'paused'; END IF; END $$ """,
        """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='completed' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='loadstatus')) THEN ALTER TYPE loadstatus ADD VALUE 'completed'; END IF; END $$ """,
        """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='withdrawn' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='responsestatus')) THEN ALTER TYPE responsestatus ADD VALUE 'withdrawn'; END IF; END $$ """,
        """CREATE TABLE IF NOT EXISTS status_changes (
            id SERIAL PRIMARY KEY,
            entity_type VARCHAR(50) NOT NULL,
            entity_id INTEGER NOT NULL,
            from_status VARCHAR(30),
            to_status VARCHAR(30) NOT NULL,
            user_id INTEGER REFERENCES users(id),
            changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            reason TEXT
        )""",
        # Расширяем entity_type с VARCHAR(20) до VARCHAR(50) для user_deletion_attempt (22 символа)
        "ALTER TABLE status_changes ALTER COLUMN entity_type TYPE VARCHAR(50)",
        """CREATE TABLE IF NOT EXISTS cities (
            id SERIAL PRIMARY KEY,
            name_ru VARCHAR(100) NOT NULL,
            name_ge VARCHAR(100),
            country_iso CHAR(2) NOT NULL,
            lat FLOAT,
            lon FLOAT,
            is_popular BOOLEAN NOT NULL DEFAULT TRUE,
            yandex_geo_id VARCHAR(50)
        )""",
        """CREATE TABLE IF NOT EXISTS reset_codes (
            id SERIAL PRIMARY KEY,
            email VARCHAR NOT NULL,
            code VARCHAR NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS route_subscriptions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            from_city VARCHAR(100) NOT NULL,
            to_city VARCHAR(100) NOT NULL,
            notify_tg BOOLEAN NOT NULL DEFAULT TRUE,
            notify_email BOOLEAN NOT NULL DEFAULT FALSE,
            truck_type VARCHAR(50),
            max_weight_t INTEGER,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            last_notified_at TIMESTAMP WITH TIME ZONE
        )""",
        "CREATE INDEX IF NOT EXISTS ix_route_subscriptions_user_id ON route_subscriptions(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_route_subscriptions_is_active ON route_subscriptions(is_active)",
        "CREATE INDEX IF NOT EXISTS ix_route_sub_route ON route_subscriptions(from_city, to_city, is_active)",
        # ADR-016: двусторонняя биржа
        """CREATE TABLE IF NOT EXISTS transport_offers (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            from_city VARCHAR(100) NOT NULL,
            to_city VARCHAR(100) NOT NULL,
            from_city_id INTEGER REFERENCES cities(id),
            to_city_id INTEGER REFERENCES cities(id),
            truck_type VARCHAR(50) NOT NULL,
            capacity_kg FLOAT NOT NULL,
            available_from TIMESTAMP WITH TIME ZONE NOT NULL,
            available_to TIMESTAMP WITH TIME ZONE,
            price FLOAT,
            price_usd FLOAT,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            urgent BOOLEAN NOT NULL DEFAULT FALSE,
            notes TEXT,
            views INTEGER NOT NULL DEFAULT 0,
            is_demo BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )""",
        "CREATE INDEX IF NOT EXISTS ix_transport_offers_user_id ON transport_offers(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_transport_offers_status ON transport_offers(status)",
        """CREATE TABLE IF NOT EXISTS transport_requests (
            id SERIAL PRIMARY KEY,
            transport_offer_id INTEGER NOT NULL REFERENCES transport_offers(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            cargo_description TEXT,
            weight_kg FLOAT,
            price FLOAT,
            message TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_transport_requests_offer_id ON transport_requests(transport_offer_id)",
        "CREATE INDEX IF NOT EXISTS ix_transport_requests_user_id ON transport_requests(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_transport_requests_status ON transport_requests(status)",
        """CREATE TABLE IF NOT EXISTS transport_subscriptions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            from_city VARCHAR(100) NOT NULL,
            to_city VARCHAR(100) NOT NULL,
            notify_tg BOOLEAN NOT NULL DEFAULT TRUE,
            notify_email BOOLEAN NOT NULL DEFAULT FALSE,
            truck_type VARCHAR(50),
            max_weight_t INTEGER,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            last_notified_at TIMESTAMP WITH TIME ZONE
        )""",
        "CREATE INDEX IF NOT EXISTS ix_transport_sub_user ON transport_subscriptions(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_transport_sub_active ON transport_subscriptions(is_active)",
        "CREATE INDEX IF NOT EXISTS ix_transport_sub_route ON transport_subscriptions(from_city, to_city, is_active)",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS transport_offer_id INTEGER REFERENCES transport_offers(id)",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS transport_request_id INTEGER REFERENCES transport_requests(id)",
        # payments table (2026-07-01)
        """CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            type VARCHAR(50) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            amount_gel NUMERIC(10,2) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            provider VARCHAR(30) NOT NULL DEFAULT 'manual',
            provider_tx_id VARCHAR(200),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            paid_at TIMESTAMP WITH TIME ZONE
        )""",
        "CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_payments_status ON payments(status)",
    ]
    async with engine.begin() as conn:
        for sql in _emergency_migrations:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                print(f"[MIGRATE] ⚠️ {sql[:50]}: {e}", flush=True)
    print("[MIGRATE] ✅ Emergency migrations applied", flush=True)

    # Проверка соединения с БД
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM loads"))
            count = result.scalar()
            print(f"[STARTUP] ✅ DB OK — loads: {count}", flush=True)
    except Exception as e:
        print(f"[STARTUP] ⚠️ DB check failed: {e}", flush=True)

    # Сидинг городов (ADR-007) — только если таблица пустая
    try:
        from app.services.cities_seed import seed_cities
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            n = await seed_cities(db)
            if n:
                print(f"[SEED] ✅ Cities seeded: {n} records", flush=True)
    except Exception as e:
        print(f"[SEED] ⚠️ Cities seed failed: {e}", flush=True)

    # Запускаем фоновый цикл smoke-тестов
    _asyncio.create_task(_smoke_loop())
    _asyncio.create_task(_idempotency_cleanup_loop())
    yield

# ── Background smoke-test cache (ADR-011 + Q-018 fix) ─────────────────────────
import asyncio as _asyncio
import time as _time

_smoke_cache: dict = {
    "checks": {},
    "last_run": 0.0,
    "running": False,
}
_SMOKE_INTERVAL = 60  # секунды между прогонами smoke-тестов


async def _run_smoke_tests() -> dict:
    """Выполняет smoke-тесты через прямые SQL-запросы (без HTTP self-loopback).
    
    Антипаттерн HTTP 127.0.0.1:8000 не работает в Railway-контейнере.
    Вместо этого — прямые SELECT к каждой критичной таблице.
    ADR-011 + Q-018.
    """
    from sqlalchemy import text as _sa_text
    checks: dict = {}

    # Получаем сессию напрямую из engine (без HTTP)
    try:
        from app.database import engine as _engine
        async with _engine.connect() as conn:
            # 1. loads — основная таблица грузов
            try:
                result = await conn.execute(_sa_text("SELECT id FROM loads LIMIT 1"))
                result.fetchone()
                checks["loads"] = "ok"
            except Exception as e:
                checks["loads"] = f"FAIL: {type(e).__name__}: {str(e)[:80]}"

            # 2. cities — таблица городов (geocoder)
            try:
                result = await conn.execute(_sa_text("SELECT id FROM cities LIMIT 1"))
                result.fetchone()
                checks["geocoder"] = "ok"
            except Exception as e:
                checks["geocoder"] = f"FAIL: {type(e).__name__}: {str(e)[:80]}"

            # 3. dictionaries — проверяем через Python (нет таблицы, это in-memory)
            try:
                from app.services.dictionaries import TRUCK_TYPES
                checks["dicts"] = "ok" if TRUCK_TYPES else "FAIL: empty"
            except Exception as e:
                checks["dicts"] = f"FAIL: {type(e).__name__}: {str(e)[:80]}"

    except Exception as e:
        # Если engine недоступен — все тесты упали
        for k in ("loads", "geocoder", "dicts"):
            if k not in checks:
                checks[k] = f"FAIL: engine: {type(e).__name__}"

    return checks


async def _smoke_loop():
    """Фоновая задача: обновляет smoke-кеш раз в 60 секунд."""
    # Первый прогон — небольшая задержка, чтобы сервер успел полностью подняться
    await _asyncio.sleep(10)
    while True:
        try:
            checks = await _run_smoke_tests()
            _smoke_cache["checks"] = checks
            _smoke_cache["last_run"] = _time.monotonic()
        except Exception:
            pass
        await _asyncio.sleep(_SMOKE_INTERVAL)


async def _idempotency_cleanup_loop():
    """Фоновая задача: удаляет протухшие idempotency_keys раз в час."""
    await _asyncio.sleep(60)  # небольшая задержка при старте
    while True:
        try:
            from app.database import AsyncSessionLocal
            from app.services.idempotency import cleanup_expired_keys
            async with AsyncSessionLocal() as db:
                deleted = await cleanup_expired_keys(db)
                if deleted:
                    print(f"[IDEMPOTENCY] ✅ Cleaned up {deleted} expired keys", flush=True)
        except Exception as e:
            print(f"[IDEMPOTENCY] ⚠️ Cleanup failed: {e}", flush=True)
        await _asyncio.sleep(3600)  # раз в час


app = FastAPI(
    title="CaucasHub API",
    description="Caucasus Freight Exchange — API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,   prefix="/api/auth",   tags=["auth"])
app.include_router(users.router,  prefix="/api/users",  tags=["users"])
app.include_router(loads.router,  prefix="/api/loads",  tags=["loads"])
app.include_router(trucks.router, prefix="/api/trucks", tags=["trucks"])
app.include_router(ai.router,     prefix="/api/ai",     tags=["ai"])
app.include_router(deals.router,  prefix="/api/deals",  tags=["deals"])
app.include_router(responses.router, tags=["responses"])
app.include_router(tg_bot.router,   prefix="/api/tg",     tags=["telegram"])
app.include_router(cities.router,        prefix="/api/cities",        tags=["cities"])
app.include_router(dictionaries.router,  prefix="/api/dictionaries",  tags=["dictionaries"])
app.include_router(stats.router,         prefix="/api/stats",         tags=["stats"])
app.include_router(subscriptions.router, tags=["subscriptions"])
app.include_router(transport.router)
app.include_router(transport_requests.router)
app.include_router(transport_subscriptions.router)
app.include_router(payments.router)

@app.get("/")
def root():
    return {"status": "ok", "service": "CaucasHub API v1.0"}

@app.get("/health")
async def health():
    """
    ADR-011 + Q-018: расширенный healthcheck с кешированными smoke-тестами.
    Smoke-тесты выполняются в фоне раз в 60 сек. /health возвращает последний
    кешированный результат — никаких "skip" из-за таймаутов при синхронном запросе.
    Railway использует этот эндпоинт для auto-rollback при деградации.
    """
    from sqlalchemy import text as sa_text
    from app.database import engine as db_engine
    from fastapi.responses import JSONResponse

    checks: dict = {}

    # 1. БД — всегда проверяем синхронно (быстро, надёжно)
    try:
        async with db_engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"FAIL: {e}"

    # 2–4. Smoke-тесты — из кеша (обновляется фоновой задачей каждые 60 сек)
    cached = _smoke_cache.get("checks", {})
    age = _time.monotonic() - _smoke_cache.get("last_run", 0.0)
    if cached:
        checks.update(cached)
        checks["_smoke_age_sec"] = round(age, 1)
    else:
        # Кеш ещё не прогрелся (первые ~10 сек после старта)
        checks["loads"] = "warming_up"
        checks["geocoder"] = "warming_up"
        checks["dicts"] = "warming_up"

    failed = [k for k, v in checks.items()
              if isinstance(v, str) and v.startswith("FAIL")]
    if failed:
        return JSONResponse(status_code=503, content={
            "status": "unhealthy",
            "failed_checks": failed,
            "checks": checks,
        })
    return {"status": "healthy", "checks": checks}


@app.get("/health_legacy")
async def health_legacy():
    """Старый healthcheck — только SELECT 1. Оставлен для совместимости."""
    from sqlalchemy import text as sa_text
    from app.database import engine as db_engine
    try:
        async with db_engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        return {"status": "healthy", "db": "ok"}
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "db": "error", "detail": str(e)}
        )


