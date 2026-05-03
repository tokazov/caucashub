from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import loads, trucks, auth, ai, users, deals
from app.database import engine, Base
from app.models import user, load, truck, response, deal  # noqa — регистрируем модели
from contextlib import asynccontextmanager
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Создаём таблицы при старте
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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

@app.get("/")
def root():
    return {"status": "ok", "service": "CaucasHub API v1.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}
