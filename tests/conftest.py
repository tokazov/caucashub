"""
conftest.py — изоляция тестового окружения CaucasHub.
"""
import os
import glob

# КРИТИЧНО: до любого импорта app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_shared.db"
os.environ.setdefault("SECRET_KEY", "test-secret-for-all-tests")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Общий engine для всех тестов без собственного override
_shared_engine = create_async_engine(
    "sqlite+aiosqlite:///./test_shared.db",
    connect_args={"check_same_thread": False}
)
_SharedSession = sessionmaker(_shared_engine, class_=AsyncSession, expire_on_commit=False)


async def _shared_get_db():
    async with _SharedSession() as session:
        yield session


@pytest.fixture(autouse=True, scope="session")
def cleanup_stale_db():
    for db_file in glob.glob("*.db"):
        try:
            os.remove(db_file)
        except (FileNotFoundError, PermissionError):
            pass
    yield
    for db_file in glob.glob("*.db"):
        try:
            os.remove(db_file)
        except (FileNotFoundError, PermissionError):
            pass


def pytest_runtest_setup(item):
    """
    Перед каждым тестом: устанавливаем правильный get_db override.
    - Если модуль имеет override_get_db → используем его
    - Иначе → используем общий shared engine (SQLite)
    """
    try:
        from app.main import app
        from app.database import get_db
        
        module = item.module
        if hasattr(module, 'override_get_db'):
            app.dependency_overrides[get_db] = module.override_get_db
        elif hasattr(module, 'override_db'):
            app.dependency_overrides[get_db] = module.override_db
        else:
            # Нет собственного override — используем shared SQLite
            app.dependency_overrides[get_db] = _shared_get_db
    except Exception:
        pass
