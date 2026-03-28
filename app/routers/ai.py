from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.load import Load, LoadStatus
from app.config import settings
from pydantic import BaseModel
from typing import Optional, List
import google.generativeai as genai
import json, re

router = APIRouter()

genai.configure(api_key=settings.GEMINI_API_KEY)
try:
    model = genai.GenerativeModel("gemini-2.5-flash")
except Exception:
    model = genai.GenerativeModel("gemini-1.5-flash")

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

class DispatcherMessage(BaseModel):
    message: str
    history: List[dict] = []   # [{role: "user"|"assistant", text: "..."}]
    state: dict = {}            # накопленные данные {role, from, to, weight_cap, truck, date, ...}

@router.get("/dispatcher/test")
async def dispatcher_test():
    """Quick test — проверяем Gemini"""
    try:
        test_model = genai.GenerativeModel("gemini-1.5-flash")
        r = test_model.generate_content("Скажи 'ОК' одним словом")
        return {"status": "ok", "gemini": r.text.strip(), "key_prefix": settings.GEMINI_API_KEY[:8]}
    except Exception as e:
        return {"status": "error", "error": str(e), "key_prefix": settings.GEMINI_API_KEY[:8]}

@router.post("/dispatcher")
async def dispatcher(req: DispatcherMessage, db: AsyncSession = Depends(get_db)):
    """
    Живой AI диспетчер — Gemini понимает контекст, отвечает естественно,
    параллельно извлекает структурированные данные для поиска/размещения груза.
    """

    # Загружаем активные грузы из БД для контекста
    result = await db.execute(
        select(Load).where(Load.status == LoadStatus.active).limit(20)
    )
    loads = result.scalars().all()
    loads_ctx = "\n".join([
        f"ID:{l.id} | {l.from_city} → {l.to_city} | {l.weight_kg}кг | {l.truck_type} | {l.price_usd}{'$' if l.scope=='intl' else '₾'} | {l.company_name}"
        for l in loads
    ]) or "Грузов пока нет"

    # История диалога для контекста
    history_text = ""
    for msg in req.history[-6:]:  # последние 6 сообщений
        role = "Пользователь" if msg["role"] == "user" else "Диспетчер"
        history_text += f"{role}: {msg['text']}\n"

    state_json = json.dumps(req.state, ensure_ascii=False)

    system_prompt = f"""Ты Мари — AI диспетчер биржи грузов CaucasHub.ge.
Биржа для Кавказа: Грузия, Армения, Азербайджан, Турция, Россия.

ТВОЯ ЗАДАЧА:
1. Общайся живо и естественно — как опытный диспетчер, не как бот
2. Понимай любой формат: сокращения, опечатки, смешанный язык
3. Параллельно извлекай данные для поиска/размещения

ПРАВИЛА ОБЩЕНИЯ:
- Не задавай больше одного вопроса за раз
- Не повторяй то что уже знаешь из контекста
- Короткие живые ответы, без воды
- Если пользователь написал маршрут — сразу ищи, не переспрашивай

РОЛИ:
- Перевозчик: ищет грузы. Нужно: from, to, тоннаж (опц), кузов (опц), дата (опц)
- Грузовладелец: размещает груз. Нужно: from, to, вес, что везём, дата

АКТИВНЫЕ ГРУЗЫ НА БИРЖЕ:
{loads_ctx}

ТЕКУЩЕЕ СОСТОЯНИЕ ДИАЛОГА:
{state_json}

ИСТОРИЯ:
{history_text}

ИНСТРУКЦИЯ ПО ОТВЕТУ:
Ответь в формате JSON (только JSON, без markdown):
{{
  "reply": "твой живой ответ пользователю",
  "state": {{
    "role": "carrier" | "shipper" | null,
    "from": "город или null",
    "to": "город или null",
    "weight_cap": число_кг или null,
    "weight": число_кг или null,
    "truck": "тент/рефриж/борт/фургон/термос/контейнер или null",
    "date": "дата или null",
    "date2": "конец интервала или null",
    "cargo_desc": "описание груза или null",
    "price": число или null,
    "ready_to_search": true/false,
    "ready_to_post": true/false
  }},
  "search_filters": {{
    "from": "...", "to": "...", "max_kg": число или null
  }} | null
}}

Сохраняй все данные из предыдущего state которые уже были заполнены.
ready_to_search = true когда у перевозчика есть from + to.
ready_to_post = true когда у грузовладельца есть from + to + weight.
"""

    try:
        response = model.generate_content(
            system_prompt + f"\n\nПользователь: {req.message}"
        )
        raw = response.text.strip()

        # Чистим все варианты markdown-обёрток
        raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        raw = raw.strip()

        # Ищем JSON внутри ответа если он обёрнут в текст
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            raw = json_match.group(0)

        data = json.loads(raw)
        matched_loads = []
        if data.get("state", {}).get("ready_to_search"):
            matched_loads = [
                {
                    "id": l.id,
                    "from": l.from_city,
                    "to": l.to_city,
                    "kg": l.weight_kg,
                    "truck": l.truck_type,
                    "price": l.price_usd,
                    "scope": l.scope,
                    "company": l.company_name,
                    "rating": "4.8",
                }
                for l in loads
                if _load_matches(l, data.get("search_filters"))
            ][:3]

        return {
            "reply": data.get("reply", ""),
            "state": data.get("state", req.state),
            "search_filters": data.get("search_filters"),
            "loads": matched_loads
        }
    except Exception as e:
        # Возвращаем пустой reply чтобы фронт ушёл в офлайн логику
        return {
            "reply": "",
            "state": req.state,
            "search_filters": None,
            "loads": [],
            "error": str(e)
        }


def _load_matches(load: Load, filters: Optional[dict]) -> bool:
    if not filters:
        return False
    from_f = (filters.get("from") or "").lower()[:4]
    to_f = (filters.get("to") or "").lower()[:4]
    max_kg = filters.get("max_kg")
    if from_f and from_f not in load.from_city.lower():
        return False
    if to_f and to_f not in load.to_city.lower():
        return False
    if max_kg and load.weight_kg > max_kg:
        return False
    return True


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
