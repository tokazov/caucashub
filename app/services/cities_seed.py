"""
Сидинг таблицы cities — топ-50 городов Грузии, СНГ и Турции.
Запуск: python -m app.services.cities_seed

Или через API: POST /api/cities/seed?secret=...
"""
from typing import List, Dict

CITIES_SEED: List[Dict] = [
    # ── Грузия (GE) ───────────────────────────────────────────────────────────
    {"name_ru": "Тбилиси",      "name_ge": "თბილისი",    "country_iso": "GE", "lat": 41.6941, "lon": 44.8337, "is_popular": True},
    {"name_ru": "Батуми",       "name_ge": "ბათუმი",     "country_iso": "GE", "lat": 41.6424, "lon": 41.6355, "is_popular": True},
    {"name_ru": "Кутаиси",      "name_ge": "ქუთაისი",    "country_iso": "GE", "lat": 42.2679, "lon": 42.6975, "is_popular": True},
    {"name_ru": "Поти",         "name_ge": "ფოთი",       "country_iso": "GE", "lat": 42.1528, "lon": 41.6726, "is_popular": True},
    {"name_ru": "Рустави",      "name_ge": "რუსთავი",    "country_iso": "GE", "lat": 41.5489, "lon": 44.9986, "is_popular": True},
    {"name_ru": "Гори",         "name_ge": "გორი",       "country_iso": "GE", "lat": 41.9865, "lon": 44.1133, "is_popular": True},
    {"name_ru": "Зугдиди",      "name_ge": "ზუგდიდი",    "country_iso": "GE", "lat": 42.5090, "lon": 41.8710, "is_popular": True},
    {"name_ru": "Телави",       "name_ge": "თელავი",     "country_iso": "GE", "lat": 41.9213, "lon": 45.4729, "is_popular": True},
    {"name_ru": "Ахалцихе",     "name_ge": "ახალციხე",   "country_iso": "GE", "lat": 41.6388, "lon": 42.9842, "is_popular": True},
    {"name_ru": "Озургети",     "name_ge": "ოზურგეთი",   "country_iso": "GE", "lat": 41.9218, "lon": 42.0071, "is_popular": True},
    {"name_ru": "Натахтари",    "name_ge": "ნატახტარი",  "country_iso": "GE", "lat": 41.8940, "lon": 44.7160, "is_popular": False},
    {"name_ru": "Цхалтубо",     "name_ge": "წყალტუბო",   "country_iso": "GE", "lat": 42.3275, "lon": 42.5980, "is_popular": False},
    {"name_ru": "Сенаки",       "name_ge": "სენაკი",     "country_iso": "GE", "lat": 42.2661, "lon": 42.0624, "is_popular": False},
    {"name_ru": "Хашури",       "name_ge": "ხაშური",     "country_iso": "GE", "lat": 41.9986, "lon": 43.5956, "is_popular": False},
    {"name_ru": "Мцхета",       "name_ge": "მცხეთა",     "country_iso": "GE", "lat": 41.8439, "lon": 44.7193, "is_popular": False},
    {"name_ru": "Боржоми",      "name_ge": "ბორჯომი",    "country_iso": "GE", "lat": 41.8408, "lon": 43.3929, "is_popular": False},
    {"name_ru": "Ахалкалаки",   "name_ge": "ახალქალაქი", "country_iso": "GE", "lat": 41.4014, "lon": 43.4878, "is_popular": False},
    {"name_ru": "Цероване",     "name_ge": "წეროვანი",   "country_iso": "GE", "lat": 41.7977, "lon": 44.8601, "is_popular": False},
    {"name_ru": "Каспи",        "name_ge": "კასპი",      "country_iso": "GE", "lat": 41.9261, "lon": 44.4143, "is_popular": False},

    # ── Армения (AM) ──────────────────────────────────────────────────────────
    {"name_ru": "Ереван",       "name_ge": "ერევანი",    "country_iso": "AM", "lat": 40.1872, "lon": 44.5152, "is_popular": True},
    {"name_ru": "Гюмри",        "name_ge": None,         "country_iso": "AM", "lat": 40.7942, "lon": 43.8453, "is_popular": True},
    {"name_ru": "Ванадзор",     "name_ge": None,         "country_iso": "AM", "lat": 40.8128, "lon": 44.4887, "is_popular": False},

    # ── Азербайджан (AZ) ──────────────────────────────────────────────────────
    {"name_ru": "Баку",         "name_ge": "ბაქო",       "country_iso": "AZ", "lat": 40.4093, "lon": 49.8671, "is_popular": True},
    {"name_ru": "Гянджа",       "name_ge": None,         "country_iso": "AZ", "lat": 40.6828, "lon": 46.3606, "is_popular": False},

    # ── Турция (TR) ───────────────────────────────────────────────────────────
    {"name_ru": "Стамбул",      "name_ge": "სტამბული",   "country_iso": "TR", "lat": 41.0082, "lon": 28.9784, "is_popular": True},
    {"name_ru": "Анкара",       "name_ge": None,         "country_iso": "TR", "lat": 39.9334, "lon": 32.8597, "is_popular": True},
    {"name_ru": "Измир",        "name_ge": None,         "country_iso": "TR", "lat": 38.4192, "lon": 27.1287, "is_popular": False},
    {"name_ru": "Трабзон",      "name_ge": None,         "country_iso": "TR", "lat": 41.0027, "lon": 39.7168, "is_popular": True},
    {"name_ru": "Карс",         "name_ge": None,         "country_iso": "TR", "lat": 40.6013, "lon": 43.0975, "is_popular": True},
    {"name_ru": "Эрзурум",      "name_ge": None,         "country_iso": "TR", "lat": 39.9051, "lon": 41.2658, "is_popular": True},
    {"name_ru": "Самсун",       "name_ge": None,         "country_iso": "TR", "lat": 41.2867, "lon": 36.3300, "is_popular": False},

    # ── Россия (RU) ───────────────────────────────────────────────────────────
    {"name_ru": "Москва",       "name_ge": "მოსკოვი",    "country_iso": "RU", "lat": 55.7558, "lon": 37.6176, "is_popular": True},
    {"name_ru": "Ростов-на-Дону", "name_ge": None,       "country_iso": "RU", "lat": 47.2357, "lon": 39.7015, "is_popular": True},
    {"name_ru": "Краснодар",    "name_ge": None,         "country_iso": "RU", "lat": 45.0448, "lon": 38.9760, "is_popular": True},
    {"name_ru": "Сочи",         "name_ge": None,         "country_iso": "RU", "lat": 43.5992, "lon": 39.7257, "is_popular": True},
    {"name_ru": "Владикавказ",  "name_ge": None,         "country_iso": "RU", "lat": 43.0241, "lon": 44.6814, "is_popular": True},
    {"name_ru": "Минеральные Воды", "name_ge": None,     "country_iso": "RU", "lat": 44.2139, "lon": 43.1370, "is_popular": False},
    {"name_ru": "Ставрополь",   "name_ge": None,         "country_iso": "RU", "lat": 45.0448, "lon": 41.9692, "is_popular": False},

    # ── Казахстан (KZ) ────────────────────────────────────────────────────────
    {"name_ru": "Алматы",       "name_ge": None,         "country_iso": "KZ", "lat": 43.2220, "lon": 76.8512, "is_popular": True},
    {"name_ru": "Астана",       "name_ge": None,         "country_iso": "KZ", "lat": 51.1801, "lon": 71.4460, "is_popular": False},

    # ── Иран (IR) ─────────────────────────────────────────────────────────────
    {"name_ru": "Тегеран",      "name_ge": None,         "country_iso": "IR", "lat": 35.6892, "lon": 51.3890, "is_popular": True},
    {"name_ru": "Тебриз",       "name_ge": None,         "country_iso": "IR", "lat": 38.0962, "lon": 46.2738, "is_popular": False},

    # ── Украина (UA) ──────────────────────────────────────────────────────────
    {"name_ru": "Одесса",       "name_ge": None,         "country_iso": "UA", "lat": 46.4825, "lon": 30.7233, "is_popular": False},

    # ── Беларусь (BY) ─────────────────────────────────────────────────────────
    {"name_ru": "Минск",        "name_ge": None,         "country_iso": "BY", "lat": 53.9045, "lon": 27.5615, "is_popular": False},

    # ── Польша (PL) ───────────────────────────────────────────────────────────
    {"name_ru": "Варшава",      "name_ge": None,         "country_iso": "PL", "lat": 52.2297, "lon": 21.0122, "is_popular": False},

    # ── Германия (DE) ─────────────────────────────────────────────────────────
    {"name_ru": "Берлин",       "name_ge": None,         "country_iso": "DE", "lat": 52.5200, "lon": 13.4050, "is_popular": False},
]


async def seed_cities(db) -> int:
    """Заполняет таблицу cities если она пустая. Возвращает количество добавленных."""
    from sqlalchemy import select
    from app.models.city import City

    result = await db.execute(select(City).limit(1))
    if result.scalar_one_or_none():
        return 0  # уже заполнено

    count = 0
    for c in CITIES_SEED:
        city = City(**c)
        db.add(city)
        count += 1

    await db.commit()
    return count


if __name__ == "__main__":
    import asyncio
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

    async def main():
        os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/caucashub")
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            n = await seed_cities(db)
            print(f"Seeded {n} cities")

    asyncio.run(main())
