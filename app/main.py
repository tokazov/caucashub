from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import loads, trucks, auth, ai, users, deals, responses, tg_bot, cities, dictionaries, stats, subscriptions
from app.database import engine
from app.models import user, load, truck, response, deal, city, status_change  # noqa — регистрируем модели
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
    # nixpacks [phases.migrate] может не поддерживаться на Railway Hobby.
    # Применяем только недостающие колонки через IF NOT EXISTS — идемпотентно.
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
        """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='pro_plus' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='userplan')) THEN ALTER TYPE userplan ADD VALUE 'pro_plus'; END IF; END $$""",
        """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='paused' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='loadstatus')) THEN ALTER TYPE loadstatus ADD VALUE 'paused'; END IF; END $$""",
        """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='withdrawn' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='responsestatus')) THEN ALTER TYPE responsestatus ADD VALUE 'withdrawn'; END IF; END $$""",
        """CREATE TABLE IF NOT EXISTS status_changes (
            id SERIAL PRIMARY KEY,
            entity_type VARCHAR(20) NOT NULL,
            entity_id INTEGER NOT NULL,
            from_status VARCHAR(30),
            to_status VARCHAR(30) NOT NULL,
            user_id INTEGER REFERENCES users(id),
            changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            reason TEXT
        )""",
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

    yield

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

@app.get("/")
def root():
    return {"status": "ok", "service": "CaucasHub API v1.0"}

@app.get("/health")
async def health():
    """
    ADR-011: healthcheck с проверкой соединения с БД.
    Railway использует этот эндпоинт для определения готовности сервиса.
    Возвращает 200 только если БД доступна.
    """
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


