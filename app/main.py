from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import loads, trucks, auth, ai, users, deals, responses, tg_bot, cities, dictionaries, stats
from app.database import engine, Base
from app.models import user, load, truck, response, deal, city, status_change  # noqa — регистрируем модели
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Создаём таблицы при старте (не удаляем существующие данные!)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Миграции — добавляем новые колонки если их нет
    from sqlalchemy import text
    migrations = [
        # Тарификация — счётчик откликов
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS responses_this_month INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS responses_month_reset TIMESTAMP WITH TIME ZONE",
        # pro_plus план в enum (если не добавлен)
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='pro_plus' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='userplan')) THEN ALTER TYPE userplan ADD VALUE 'pro_plus'; END IF; END $$",
        # paused статус груза (Трек 10, 2.4.2)
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='paused' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='loadstatus')) THEN ALTER TYPE loadstatus ADD VALUE 'paused'; END IF; END $$",
        # withdrawn статус отклика (Трек 8)
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='withdrawn' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='responsestatus')) THEN ALTER TYPE responsestatus ADD VALUE 'withdrawn'; END IF; END $$",
        # ADR-006: поля валюты в loads
        "ALTER TABLE loads ADD COLUMN IF NOT EXISTS exchange_rate_at_creation FLOAT",
        # ADR-006: поля валюты в responses
        "ALTER TABLE responses ADD COLUMN IF NOT EXISTS price_gel FLOAT",
        "ALTER TABLE responses ADD COLUMN IF NOT EXISTS exchange_rate_at_creation FLOAT",
        # ADR-006: поля валюты в deals
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS exchange_rate_snapshot FLOAT",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS final_price_gel FLOAT",
        "ALTER TABLE deals ADD COLUMN IF NOT EXISTS final_price_usd FLOAT",
        # ADR-007: таблица cities и FK в loads
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
        "ALTER TABLE loads ADD COLUMN IF NOT EXISTS from_city_id INTEGER",
        "ALTER TABLE loads ADD COLUMN IF NOT EXISTS to_city_id INTEGER",
        # Трек 8: audit log
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
        # ADR-010: soft delete
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE",
        # reset_codes table (если не было)
        """CREATE TABLE IF NOT EXISTS reset_codes (
            id SERIAL PRIMARY KEY,
            email VARCHAR NOT NULL,
            code VARCHAR NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(text(sql))
                print(f"[MIGRATION] ✅ {sql[:60]}...", flush=True)
            except Exception as e:
                print(f"[MIGRATION] ⚠️ {sql[:60]}: {e}", flush=True)

    # Проверка что данные на месте
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

@app.get("/")
def root():
    return {"status": "ok", "service": "CaucasHub API v1.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}


