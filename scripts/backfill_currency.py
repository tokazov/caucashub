"""
Скрипт разового пересчёта валют для существующих записей (ADR-006).

Запуск: python scripts/backfill_currency.py

Что делает:
- Для loads с price_gel но без price_usd → заполняет price_usd по текущему курсу
- Для loads с price_usd но без price_gel → заполняет price_gel
- То же для responses
- Для deals без exchange_rate_snapshot → заполняет
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


async def main():
    from sqlalchemy import select
    from app.database import engine, Base, AsyncSessionLocal
    from app.models.load import Load
    from app.models.response import Response
    from app.models.deal import Deal
    from app.services.exchange_rate import get_usd_gel_rate, convert_gel_to_usd, convert_usd_to_gel

    rate = await get_usd_gel_rate()
    print(f"Current NBG rate: 1 USD = {rate} GEL")

    async with AsyncSessionLocal() as db:
        # ── Loads ────────────────────────────────────────────────────────────
        result = await db.execute(select(Load))
        loads = result.scalars().all()
        loads_updated = 0
        for load in loads:
            changed = False
            if load.price_gel and not load.price_usd:
                load.price_usd = convert_gel_to_usd(load.price_gel, rate)
                changed = True
            elif load.price_usd and not load.price_gel:
                load.price_gel = convert_usd_to_gel(load.price_usd, rate)
                changed = True
            if not load.exchange_rate_at_creation:
                load.exchange_rate_at_creation = rate
                changed = True
            if changed:
                loads_updated += 1
        await db.commit()
        print(f"Loads updated: {loads_updated}/{len(loads)}")

        # ── Responses ─────────────────────────────────────────────────────────
        result = await db.execute(select(Response))
        responses = result.scalars().all()
        resp_updated = 0
        for resp in responses:
            changed = False
            if resp.price_gel and not resp.price_usd:
                resp.price_usd = convert_gel_to_usd(resp.price_gel, rate)
                changed = True
            elif resp.price_usd and not resp.price_gel:
                resp.price_gel = convert_usd_to_gel(resp.price_usd, rate)
                changed = True
            if not resp.exchange_rate_at_creation:
                resp.exchange_rate_at_creation = rate
                changed = True
            if changed:
                resp_updated += 1
        await db.commit()
        print(f"Responses updated: {resp_updated}/{len(responses)}")

        # ── Deals ─────────────────────────────────────────────────────────────
        result = await db.execute(select(Deal))
        deals = result.scalars().all()
        deal_updated = 0
        for deal in deals:
            changed = False
            if not deal.exchange_rate_snapshot:
                deal.exchange_rate_snapshot = rate
                changed = True
            if deal.agreed_price and not deal.final_price_gel:
                deal.final_price_gel = deal.agreed_price if deal.currency == "GEL" else convert_usd_to_gel(deal.agreed_price, rate)
                deal.final_price_usd = deal.agreed_price if deal.currency == "USD" else convert_gel_to_usd(deal.agreed_price, rate)
                changed = True
            if changed:
                deal_updated += 1
        await db.commit()
        print(f"Deals updated: {deal_updated}/{len(deals)}")

    print("✅ Backfill complete")


if __name__ == "__main__":
    asyncio.run(main())
