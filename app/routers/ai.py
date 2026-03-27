from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.load import Load, LoadStatus
from app.config import settings
from pydantic import BaseModel
import google.generativeai as genai

router = APIRouter()

genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

SYSTEM_PROMPT = """
Ты AI ассистент биржи грузов CaucasHub.ge — первой грузовой биржи Кавказа.
Ты помогаешь перевозчикам и грузовладельцам:
- Найти подходящие грузы или машины
- Рассчитать справедливую ставку на маршрут
- Разобраться с документами (CMR, TIR, таможня)
- Понять требования к перевозке

Рынки: Грузия, Армения, Азербайджан, Россия, Турция, Китай.
Отвечай кратко и по делу. Язык — тот на котором пишет пользователь.
"""

class ChatRequest(BaseModel):
    message: str
    lang: str = "ru"
    scope: str = "local"

class RateRequest(BaseModel):
    from_city: str
    to_city: str
    weight_kg: float
    truck_type: str

@router.post("/chat")
async def ai_chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    # Получаем последние грузы для контекста
    result = await db.execute(
        select(Load).where(Load.status == LoadStatus.active).limit(10)
    )
    loads = result.scalars().all()
    loads_ctx = "\n".join([
        f"- {l.from_city} → {l.to_city}, {l.weight_kg}кг, {l.truck_type}, ${l.price_usd}"
        for l in loads
    ]) or "Грузы не найдены"

    prompt = f"{SYSTEM_PROMPT}\n\nАктивные грузы на бирже:\n{loads_ctx}\n\nПользователь: {req.message}"

    response = model.generate_content(prompt)
    return {
        "reply": response.text,
        "loads_count": len(loads)
    }

@router.post("/rate")
async def calculate_rate(req: RateRequest):
    """AI расчёт рыночной ставки на маршрут"""
    prompt = f"""
    Рассчитай рыночную ставку для перевозки:
    Маршрут: {req.from_city} → {req.to_city}
    Вес: {req.weight_kg} кг
    Тип кузова: {req.truck_type}

    Дай:
    1. Минимальную ставку ($)
    2. Среднерыночную ставку ($)
    3. Максимальную ставку ($)
    4. Краткое объяснение (2 предложения)

    Формат JSON: {{"min": X, "avg": Y, "max": Z, "note": "..."}}
    """
    response = model.generate_content(prompt)
    return {"rate_analysis": response.text}

@router.post("/parse-load")
async def parse_load_from_text(text: str):
    """AI парсинг груза из свободного текста"""
    prompt = f"""
    Извлеки данные о грузе из текста и верни JSON:
    Текст: "{text}"

    Верни JSON: {{
        "from_city": "...",
        "to_city": "...",
        "weight_kg": число или null,
        "truck_type": "tent/ref/bort/termos/gazel или null",
        "load_date": "сегодня/завтра/дата или null",
        "price_usd": число или null,
        "cargo_desc": "описание груза"
    }}
    Только JSON, без пояснений.
    """
    response = model.generate_content(prompt)
    return {"parsed": response.text}
