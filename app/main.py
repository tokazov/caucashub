from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import loads, trucks, auth, ai, users, deals, responses, tg_bot
from app.database import engine, Base
from app.models import user, load, truck, response, deal  # noqa — регистрируем модели
from contextlib import asynccontextmanager
import os

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

@app.get("/")
def root():
    return {"status": "ok", "service": "CaucasHub API v1.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}


