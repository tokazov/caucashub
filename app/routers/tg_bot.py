"""
Telegram Bot webhook для CaucasHub.
Обрабатывает /start <token> — привязывает chat_id к аккаунту пользователя.
"""
import os
import secrets
import logging
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.routers.loads import require_user
from app.services.telegram_notify import notify_welcome, send_tg_message

logger = logging.getLogger(__name__)
router = APIRouter()

BOT_TOKEN = os.getenv("CAUCASHUB_TG_BOT_TOKEN", "")
BOT_USERNAME = os.getenv("CAUCASHUB_TG_BOT_USERNAME", "caucashub_notify_bot")


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
                name = user.company_name or user.full_name or first_name or "пользователь"
                await notify_welcome(chat_id, name)
                logger.info(f"TG linked: user_id={user.id} chat_id={chat_id}")
            else:
                await send_tg_message(
                    chat_id,
                    "❌ Ссылка недействительна или уже использована.\n"
                    "Сгенерируйте новую в настройках профиля CaucasHub."
                )
        else:
            # /start без токена
            await send_tg_message(
                chat_id,
                "👋 Это бот уведомлений <b>CaucasHub.ge</b>\n\n"
                "Для привязки аккаунта:\n"
                "1. Войдите на <a href='https://caucashub.ge'>caucashub.ge</a>\n"
                "2. Откройте профиль → Telegram-уведомления\n"
                "3. Нажмите «Подключить Telegram»"
            )
    else:
        # Любое другое сообщение
        await send_tg_message(
            chat_id,
            "Этот бот только для уведомлений 🔔\n"
            "Управляйте грузами на <a href='https://caucashub.ge'>caucashub.ge</a>"
        )

    return {"ok": True}
