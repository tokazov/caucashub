"""
Telegram Bot webhook для CaucasHub.
Обрабатывает /start <token> — привязывает chat_id к аккаунту пользователя.
Мари — AI-ассистент поддержки отвечает на вопросы пользователей.
"""
import os
import secrets
import logging
import httpx
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.routers.loads import require_user
from app.services.telegram_notify import notify_welcome, send_tg_message, get_text

logger = logging.getLogger(__name__)
router = APIRouter()

BOT_TOKEN = os.getenv("CAUCASHUB_TG_BOT_TOKEN", "")
BOT_USERNAME = os.getenv("CAUCASHUB_TG_BOT_USERNAME", "caucashub_notify_bot")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Системный промпт Мари ─────────────────────────────────────────────
MARI_PROMPT_RU = """Ты Мари — дружелюбный AI-помощник платформы CaucasHub.ge, первой грузовой биржи Кавказа.

Ты помогаешь пользователям разобраться с платформой:
- Как разместить груз или добавить транспорт
- Как откликнуться на груз и создать сделку
- Как работают статусы сделок (confirmed → loading → in_transit → delivered → completed)
- Как подключить Telegram-уведомления
- Как скачать акт выполненных работ
- Расчёт ставок на маршруты по Грузии и СНГ
- Вопросы по документам (CMR, накладная, таможня)

Правила:
- Отвечай кратко, по-дружески, без воды
- Если не знаешь точного ответа — предложи написать в поддержку
- Не придумывай несуществующие функции
- Направляй на сайт: caucashub.ge
- Ты Мари, не упоминай что ты AI или Gemini
"""

MARI_PROMPT_GE = """შენ ხარ მარი — CaucasHub.ge პლატფორმის მეგობრული AI-თანაშემწე, კავკასიის პირველი სატვირთო ბირჟა.

შენ ეხმარები მომხმარებლებს პლატფორმის გამოყენებაში:
- როგორ განათავსოს ტვირთი ან დაამატოს ტრანსპორტი
- როგორ გამოეხმაუროს ტვირთს და შექმნას გარიგება
- როგორ მუშაობს გარიგების სტატუსები
- როგორ დაუკავშიროს Telegram შეტყობინებები
- მარშრუტების ტარიფების გაანგარიშება
- დოკუმენტაციის კითხვები (CMR, სასაქონლო ზედნადები, საბაჟო)

წესები:
- პასუხობ მოკლედ და მეგობრულად
- მიმართე საიტზე: caucashub.ge
- შენ ხარ მარი
"""


async def mari_reply(user_text: str, lang: str = "ru") -> str:
    """Мари отвечает на вопрос пользователя через Gemini."""
    if not GEMINI_API_KEY:
        if lang == "ge":
            return "გთხოვთ დაუკავშირდეთ მხარდაჭერას: caucashub.ge 🙏"
        return "Напишите нам на caucashub.ge — мы поможем! 🙏"

    system = MARI_PROMPT_GE if lang == "ge" else MARI_PROMPT_RU
    prompt = f"{system}\n\nПользователь: {user_text}\n\nМари:"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 300, "temperature": 0.7}
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return text
            else:
                logger.error(f"Gemini error: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Mari error: {e}")

    if lang == "ge":
        return "ბოდიში, ახლა ვერ ვპასუხობ. სცადეთ მოგვიანებით ან ეწვიეთ caucashub.ge-ს"
    return "Извините, сейчас не могу ответить. Попробуйте позже или зайдите на caucashub.ge"


# ── Генерация deep-link токена ────────────────────────────────────────

@router.post("/generate-link")
async def generate_tg_link(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    """Генерирует одноразовый токен и возвращает deep-link для привязки TG."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        from fastapi import HTTPException
        raise HTTPException(404, "User not found")

    # Генерируем токен и сохраняем в telegram_id временно (до привязки chat_id)
    token = secrets.token_urlsafe(16)
    user.telegram_id = f"pending:{token}"
    await db.commit()

    link = f"https://t.me/{BOT_USERNAME}?start={token}"
    return {"link": link, "token": token}


@router.get("/status")
async def tg_status(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    """Проверяет привязан ли Telegram к аккаунту."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    linked = bool(
        user and user.telegram_id
        and not user.telegram_id.startswith("pending:")
    )
    return {"linked": linked, "telegram_id": user.telegram_id if linked else None}


@router.delete("/unlink")
async def tg_unlink(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    """Отвязать Telegram от аккаунта."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.telegram_id = None
        await db.commit()
    return {"ok": True}


# ── Webhook от Telegram ───────────────────────────────────────────────

@router.post(f"/webhook/{BOT_TOKEN}")
async def tg_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Принимает обновления от Telegram."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False}

    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    from_user = message.get("from", {})
    first_name = from_user.get("first_name", "")

    if not chat_id:
        return {"ok": True}

    # Обработка /start <token>
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        token = parts[1].strip() if len(parts) > 1 else ""

        if token:
            # Ищем пользователя с этим токеном
            result = await db.execute(
                select(User).where(User.telegram_id == f"pending:{token}")
            )
            user = result.scalar_one_or_none()

            if user:
                # Привязываем chat_id
                user.telegram_id = str(chat_id)
                await db.commit()
                lang = user.lang or "ru"
                name = user.company_name or user.full_name or first_name or "пользователь"
                await notify_welcome(chat_id, name, lang=lang)
                logger.info(f"TG linked: user_id={user.id} chat_id={chat_id} lang={lang}")
            else:
                await send_tg_message(chat_id, get_text("ru", "invalid_token"))
        else:
            # /start без токена — определяем язык по language_code Telegram
            tg_lang = from_user.get("language_code", "ru")
            lang = "ge" if tg_lang in ("ka", "ge") else "ru"
            await send_tg_message(chat_id, get_text(lang, "start_no_token"))
    else:
        # Любое другое сообщение — отвечает Мари
        res = await db.execute(select(User).where(User.telegram_id == str(chat_id)))
        known_user = res.scalar_one_or_none()

        # Определяем язык: из профиля → из TG language_code → ru
        if known_user and known_user.lang:
            lang = known_user.lang
        else:
            tg_lang = from_user.get("language_code", "ru")
            lang = "ge" if tg_lang in ("ka", "ge") else "ru"

        # Показываем индикатор набора текста
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendChatAction",
                    json={"chat_id": chat_id, "action": "typing"}
                )
        except Exception:
            pass

        # Мари отвечает
        reply = await mari_reply(text, lang=lang)
        # Подпись Мари
        prefix = "👩‍💼 <b>Мари</b>\n\n" if lang != "ge" else "👩‍💼 <b>მარი</b>\n\n"
        await send_tg_message(chat_id, prefix + reply)

    return {"ok": True}
