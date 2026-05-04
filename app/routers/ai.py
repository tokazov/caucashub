from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.load import Load, LoadStatus, LoadScope
from app.config import settings
from pydantic import BaseModel
from typing import Optional, List
from google import genai as genai_new
import json
import re

router = APIRouter()

# Используем новый SDK google-genai (google-generativeai deprecated)
_genai_client = genai_new.Client(api_key=settings.GEMINI_API_KEY)
_GEMINI_MODEL = "gemini-2.5-flash"


class _ModelCompat:
    """Совместимый враппер: model.generate_content(prompt) → новый SDK."""
    def generate_content(self, prompt: str):
        resp = _genai_client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=prompt,
        )
        return resp


model = _ModelCompat()

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
        f"- {lo.from_city} → {lo.to_city}, {lo.weight_kg}кг, {lo.truck_type}, ${lo.price_usd}"
        for lo in loads
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
    user_role: Optional[str] = None   # "carrier" | "shipper" | "both" | None (ADR-016.4)

@router.get("/dispatcher/test")
async def dispatcher_test():
    """Quick test — проверяем Gemini"""
    try:
        r = model.generate_content("Скажи 'ОК' одним словом")
        return {"status": "ok", "gemini": r.text.strip(), "key_prefix": settings.GEMINI_API_KEY[:8]}
    except Exception as e:
        return {"status": "error", "error": str(e), "key_prefix": settings.GEMINI_API_KEY[:8]}

# Фикс 1: /dispatcher/debug удалён из продакшена (P0 Cat5)

@router.post("/dispatcher")
async def dispatcher(req: DispatcherMessage, db: AsyncSession = Depends(get_db)):
    """
    Живой AI диспетчер — Gemini понимает контекст, отвечает естественно,
    параллельно извлекает структурированные данные для поиска/размещения груза.
    """

    # Загружаем активные грузы из БД для контекста
    loads = []
    loads_ctx = "Грузов пока нет"
    try:
        result = await db.execute(
            select(Load).where(Load.status == LoadStatus.active).limit(20)
        )
        loads = result.scalars().all()
        loads_ctx = "\n".join([
            f"{lo.from_city} → {lo.to_city} | {lo.weight_kg}кг | {lo.price_usd or lo.price_gel or '?'}{'$' if lo.scope == LoadScope.intl else '₾'}"
            for lo in loads
        ]) or "Грузов пока нет"
    except Exception:
        pass  # БД недоступна — продолжаем без грузов

    # История диалога для контекста
    history_text = ""
    for msg in req.history[-6:]:  # последние 6 сообщений
        role = "Пользователь" if msg["role"] == "user" else "Диспетчер"
        history_text += f"{role}: {msg['text']}\n"

    state_json = json.dumps(req.state, ensure_ascii=False)

    # ADR-016.4: режим Мари зависит от роли пользователя
    user_role = req.user_role  # "carrier" | "shipper" | "both" | None
    role_context = ""
    if user_role == "carrier":
        role_context = """
РЕЖИМ ПОЛЬЗОВАТЕЛЯ: ПЕРЕВОЗЧИК (carrier)
- Если пользователь описывает свой транспорт (маршрут + тип + тоннаж + дата + цена) — это ТРАНСПОРТНОЕ ПРЕДЛОЖЕНИЕ (TransportOffer), НЕ поиск груза!
- ready_to_post_transport=true когда: from + to + truck + capacity заполнены
- Пример: «Тент Тбилиси-Батуми завтра 5т 800₾» → TransportOffer, НЕ Load!
- Если ищет грузы — как обычно (ready_to_search=true)
"""
    elif user_role == "shipper":
        role_context = """
РЕЖИМ ПОЛЬЗОВАТЕЛЯ: ГРУЗОВЛАДЕЛЕЦ (shipper)
- Если пользователь описывает что нужно перевезти (откуда/куда/вес/дата) — это ГРУЗ (Load)
- ready_to_post=true когда: from + to + weight_cap заполнены
- Тот же текст «Тент Тбилиси-Батуми завтра 5т» = размещение груза, НЕ транспортного предложения
"""
    elif user_role == "both":
        role_context = """
РЕЖИМ ПОЛЬЗОВАТЕЛЯ: BOTH (перевозчик и грузовладелец)
- Если пользователь пишет объявление — ОБЯЗАТЕЛЬНО задай один уточняющий вопрос:
  «Вы хотите разместить груз (вам нужна машина) или предложить транспорт (у вас есть машина)?»
- Не угадывай самостоятельно — спроси явно.
- После ответа действуй как carrier или shipper соответственно.
"""
    else:
        role_context = """
РЕЖИМ: НЕЗАЛОГИНЕННЫЙ ПОЛЬЗОВАТЕЛЬ
- Помогай с вопросами, показывай грузы из ленты
- Если хочет разместить объявление — предложи зарегистрироваться
"""

    system_prompt = f"""Ты Мари — AI диспетчер биржи грузов CaucasHub.ge.
Биржа для Кавказа: Грузия, Армения, Азербайджан, Турция, Россия.
{role_context}
ОБЩИЕ ПРАВИЛА ОБЩЕНИЯ:
1. Общайся живо и естественно — как опытный диспетчер, не как бот
2. Понимай любой формат: сокращения, опечатки, смешанный язык
3. Параллельно извлекай данные для поиска/размещения
- Не задавай больше одного вопроса за раз (кроме роли both)
- Не повторяй то что уже знаешь из контекста
- Короткие живые ответы, без воды
- Если пользователь написал откуда едет — сразу ищи грузы из этого города
- Если в базе нет подходящих грузов — честно скажи и предложи подписаться

РОЛИ (справочно):
- carrier (перевозчик): ищет грузы ИЛИ размещает транспортное предложение
- shipper (грузовладелец): размещает груз ИЛИ ищет транспорт

АКТИВНЫЕ ГРУЗЫ НА БИРЖЕ:
{loads_ctx}

ТЕКУЩЕЕ СОСТОЯНИЕ ДИАЛОГА (сохраняй все поля!):
{state_json}

ИСТОРИЯ ДИАЛОГА:
{history_text}

ФОРМАТ ОТВЕТА — строго JSON, без markdown:
{{"reply":"...","state":{{"role":null,"from":null,"to":null,"weight_cap":null,"truck":null,"date":null,"cargo_desc":null,"price":null,"ready_to_search":false,"ready_to_post":false,"ready_to_post_transport":false,"awaiting_role_clarification":false}},"search_filters":null,"action":null}}

Правила state:
- ВСЕГДА копируй все заполненные поля из предыдущего state, не обнуляй их
- ready_to_search=true когда role=carrier и from заполнен (to необязательно)
- ready_to_post=true когда role=shipper и from, to, weight_cap заполнены
- ready_to_post_transport=true когда role=carrier И описан транспорт (from+to+truck+capacity)
- awaiting_role_clarification=true только для role=both когда неясно что хочет
- search_filters заполняй когда ready_to_search=true: {{"from":"...","to":null_или_строка,"max_kg":null}}
- action: "post_load" | "post_transport" | "search" | null
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
        reply_text = data.get("reply", "")
        if data.get("state", {}).get("ready_to_search"):
            sf = data.get("search_filters") or {}
            from_city = data.get("state", {}).get("from") or sf.get("from") or ""
            # Ищем грузы по городу отправления (мягкое совпадение)
            matched_loads = []
            for lo in loads:
                if from_city and from_city.lower()[:4] in lo.from_city.lower():
                    matched_loads.append({
                        "id": lo.id,
                        "from": lo.from_city,
                        "to": lo.to_city,
                        "kg": lo.weight_kg,
                        "truck": str(lo.truck_type),
                        "price": lo.price_gel or lo.price_usd,
                        "cur": "₾" if lo.price_gel else "$",
                        "company": getattr(lo, 'company_name', None) or "—",
                    })
            matched_loads = matched_loads[:5]

            # Если нашли грузы — переопределяем reply
            if matched_loads:
                to_city = data.get("state", {}).get("to") or sf.get("to") or ""
                # Проверяем есть ли точное совпадение по направлению
                exact = [item for item in matched_loads if to_city and to_city.lower()[:4] in item["to"].lower()]
                n = len(matched_loads)
                routes = ", ".join(f"{item['from']} → {item['to']}" for item in matched_loads[:3])
                if exact:
                    reply_text = f"Нашла {n} груз{'а' if n in [2,3,4] else 'ов' if n > 4 else ''} из {from_city}: {routes}. Выбирайте 👆"
                else:
                    # Точного маршрута нет, но есть другие грузы из этого города
                    reply_text = f"Точного маршрута {from_city}→{to_city} нет, но есть {n} груз{'а' if n in [2,3,4] else 'ов' if n > 4 else ''} из {from_city} в другие направления: {routes}. Смотрите 👆"

        return {
            "reply": reply_text,
            "state": data.get("state", req.state),
            "search_filters": data.get("search_filters"),
            "loads": matched_loads,
            "action": data.get("action"),  # ADR-016.4: "post_load" | "post_transport" | "search"
        }
    except Exception as e:
        import traceback
        err_detail = traceback.format_exc()
        print(f"[DISPATCHER ERROR]: {err_detail}", flush=True)
        # Возвращаем пустой reply чтобы фронт ушёл в офлайн логику
        return {
            "reply": "",
            "state": req.state,
            "search_filters": None,
            "loads": [],
            "error": str(e),
            "traceback": err_detail[-500:]
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
async def parse_load_from_text(text: str, user_role: Optional[str] = None):
    """AI парсинг объявления из свободного текста.

    ADR-016.4: Если user_role=carrier → парсит в TransportOffer.
              Если user_role=shipper → парсит в Load.
              Если user_role=both → возвращает оба варианта и requires_clarification=true.
    """
    if user_role == "carrier":
        # Перевозчик описывает свой транспорт → TransportOffer
        prompt = f"""Перевозчик описывает своё транспортное предложение. Извлеки данные и верни JSON.
Текст: "{text}"

Верни JSON (TransportOffer):
{{
    "object_type": "transport_offer",
    "from_city": "...",
    "to_city": "...",
    "truck_type": "tent/gazel/ref/open/container/autovoz/lowboy или null",
    "capacity_kg": число (вместимость в кг) или null,
    "available_from": "сегодня/завтра/дата или null",
    "price": число в GEL или null,
    "price_per_km": число или null,
    "notes": "доп. информация или null"
}}
Только JSON, без пояснений."""

    elif user_role == "shipper":
        # Грузовладелец описывает груз → Load
        prompt = f"""Грузовладелец описывает груз для перевозки. Извлеки данные и верни JSON.
Текст: "{text}"

Верни JSON (Load):
{{
    "object_type": "load",
    "from_city": "...",
    "to_city": "...",
    "weight_kg": число или null,
    "truck_type": "tent/ref/gazel/open/container или null",
    "load_date": "сегодня/завтра/дата или null",
    "price_gel": число или null,
    "cargo_desc": "описание груза или null"
}}
Только JSON, без пояснений."""

    elif user_role == "both":
        # Роль both — возвращаем оба варианта и флаг уточнения
        prompt = f"""Пользователь пишет объявление. Определи ОБА возможных варианта и верни JSON.
Текст: "{text}"

Верни JSON:
{{
    "requires_clarification": true,
    "question": "Вы хотите разместить груз (вам нужна машина) или предложить транспорт (у вас есть машина)?",
    "as_load": {{
        "object_type": "load",
        "from_city": "...", "to_city": "...", "weight_kg": null,
        "truck_type": null, "load_date": null, "cargo_desc": null
    }},
    "as_transport_offer": {{
        "object_type": "transport_offer",
        "from_city": "...", "to_city": "...", "truck_type": null,
        "capacity_kg": null, "available_from": null, "price": null
    }}
}}
Только JSON, без пояснений."""

    else:
        # Без роли — универсальный парсинг
        prompt = f"""Извлеки данные о перевозке из текста и верни JSON.
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
Только JSON, без пояснений."""

    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        parsed = json.loads(raw.strip())
        return {"parsed": parsed, "user_role": user_role}
    except Exception as e:
        return {"parsed": None, "error": str(e), "raw": response.text if 'response' in dir() else None}
