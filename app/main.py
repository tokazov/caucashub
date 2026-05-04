from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import loads, trucks, auth, ai, users, deals, responses, tg_bot, cities, dictionaries, stats
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


