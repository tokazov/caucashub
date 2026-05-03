"""
Backfill: нормализация свободных строк городов в loads → city_id (ADR-007).

Запуск: python scripts/backfill_cities.py [--dry-run]

Алгоритм:
1. Загружаем все грузы с from_city_id = NULL или to_city_id = NULL
2. Для каждого from_city/to_city ищем совпадение в таблице cities (ilike первые 3 буквы)
3. Если найдено — ставим from_city_id / to_city_id
4. Если не найдено — оставляем city_id = NULL, логируем (для ручного разбора)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ.setdefault("DATABASE_URL", os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./caucashub.db"))
os.environ.setdefault("SECRET_KEY", "backfill-script")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "")
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("TG_BOT_TOKEN", "")


def _normalize_for_match(s: str) -> str:
    """Первые 4 символа нижнего регистра для мягкого матчинга."""
    return s.strip().lower()[:4]


async def main(dry_run: bool = False):
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.load import Load
    from app.models.city import City

    async with AsyncSessionLocal() as db:
        # Загружаем справочник городов
        cities_res = await db.execute(select(City))
        cities = cities_res.scalars().all()
        city_index = {}  # ключ: первые 4 буквы → список городов
        for c in cities:
            key = _normalize_for_match(c.name_ru)
            city_index.setdefault(key, []).append(c)

        # Загружаем грузы без city_id
        loads_res = await db.execute(
            select(Load).where(
                (Load.from_city_id == None) | (Load.to_city_id == None)  # noqa: E711
            )
        )
        loads = loads_res.scalars().all()
        print(f"Loads to process: {len(loads)}")

        matched_from = 0
        matched_to = 0
        unmatched = []

        for load in loads:
            # from_city
            if load.from_city_id is None and load.from_city:
                key = _normalize_for_match(load.from_city)
                candidates = city_index.get(key, [])
                if len(candidates) == 1:
                    if not dry_run:
                        load.from_city_id = candidates[0].id
                    matched_from += 1
                elif len(candidates) > 1:
                    # Выбираем точное совпадение
                    exact = [c for c in candidates if c.name_ru.lower() == load.from_city.strip().lower()]
                    if exact:
                        if not dry_run:
                            load.from_city_id = exact[0].id
                        matched_from += 1
                    else:
                        unmatched.append(f"AMBIGUOUS from_city={load.from_city!r} (load #{load.id})")
                else:
                    unmatched.append(f"NOT FOUND from_city={load.from_city!r} (load #{load.id})")

            # to_city
            if load.to_city_id is None and load.to_city:
                key = _normalize_for_match(load.to_city)
                candidates = city_index.get(key, [])
                if len(candidates) == 1:
                    if not dry_run:
                        load.to_city_id = candidates[0].id
                    matched_to += 1
                elif len(candidates) > 1:
                    exact = [c for c in candidates if c.name_ru.lower() == load.to_city.strip().lower()]
                    if exact:
                        if not dry_run:
                            load.to_city_id = exact[0].id
                        matched_to += 1
                    else:
                        unmatched.append(f"AMBIGUOUS to_city={load.to_city!r} (load #{load.id})")
                else:
                    unmatched.append(f"NOT FOUND to_city={load.to_city!r} (load #{load.id})")

        if not dry_run:
            await db.commit()
            print(f"✅ Committed")

        print(f"from_city matched: {matched_from}")
        print(f"to_city matched:   {matched_to}")
        print(f"Unmatched ({len(unmatched)}):")
        for u in unmatched:
            print(f"  - {u}")

        mode = "DRY RUN" if dry_run else "COMMITTED"
        print(f"\n{mode} complete.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(main(dry_run=dry_run))
