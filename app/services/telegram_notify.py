"""
Telegram уведомления для CaucasHub.
Отправляет сообщения пользователям у которых привязан Telegram (tg_chat_id).
"""
import os
import httpx
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("CAUCASHUB_TG_BOT_TOKEN", "")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def send_tg_message(chat_id: int | str, text: str, parse_mode: str = "HTML") -> bool:
    """Отправить сообщение в Telegram. Возвращает True если успешно."""
    if not BOT_TOKEN:
        logger.warning("CAUCASHUB_TG_BOT_TOKEN not set — skip TG notify")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{API_URL}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                return True
            else:
                logger.error(f"TG send failed: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"TG send error: {e}")
        return False


# ── Шаблоны уведомлений ─────────────────────────────────────────────

async def notify_new_response(chat_id, carrier_name: str, from_city: str, to_city: str, price: float, cur: str):
    """Грузовладельцу: новый отклик на его груз."""
    text = (
        f"📩 <b>Новый отклик на ваш груз</b>\n\n"
        f"🚛 Перевозчик: <b>{carrier_name}</b>\n"
        f"📍 Маршрут: {from_city} → {to_city}\n"
        f"💰 Ставка: {price} {cur}\n\n"
        f"Войдите в <a href='https://caucashub.ge'>CaucasHub</a> чтобы принять или отклонить."
    )
    await send_tg_message(chat_id, text)


async def notify_response_accepted(chat_id, shipper_name: str, from_city: str, to_city: str, price: float, cur: str):
    """Перевозчику: его отклик принят."""
    text = (
        f"✅ <b>Ваш отклик принят!</b>\n\n"
        f"📦 Грузовладелец: <b>{shipper_name}</b>\n"
        f"📍 Маршрут: {from_city} → {to_city}\n"
        f"💰 Сумма: {price} {cur}\n\n"
        f"Войдите в <a href='https://caucashub.ge'>CaucasHub</a> для управления сделкой."
    )
    await send_tg_message(chat_id, text)


async def notify_deal_status(chat_id, status_label: str, deal_num: str, from_city: str, to_city: str):
    """Обоим: изменился статус сделки."""
    text = (
        f"🔄 <b>Статус сделки обновлён</b>\n\n"
        f"📋 Сделка: <b>{deal_num}</b>\n"
        f"📍 {from_city} → {to_city}\n"
        f"📌 Статус: <b>{status_label}</b>\n\n"
        f"<a href='https://caucashub.ge'>Открыть CaucasHub</a>"
    )
    await send_tg_message(chat_id, text)


async def notify_deal_completed(chat_id, deal_num: str, from_city: str, to_city: str, price: float, cur: str):
    """Обоим: сделка завершена."""
    text = (
        f"🏆 <b>Сделка завершена!</b>\n\n"
        f"📋 {deal_num} | {from_city} → {to_city}\n"
        f"💰 Сумма: <b>{price} {cur}</b>\n\n"
        f"Акт выполненных работ доступен в <a href='https://caucashub.ge'>личном кабинете</a>.\n"
        f"Не забудьте оценить партнёра! ⭐"
    )
    await send_tg_message(chat_id, text)


async def notify_welcome(chat_id, name: str):
    """Приветствие после привязки Telegram."""
    text = (
        f"👋 <b>Добро пожаловать в CaucasHub, {name}!</b>\n\n"
        f"Теперь вы будете получать уведомления о:\n"
        f"• 📩 Новых откликах на ваши грузы\n"
        f"• ✅ Принятых откликах\n"
        f"• 🔄 Изменениях статуса сделок\n"
        f"• 🏆 Завершённых сделках\n\n"
        f"<a href='https://caucashub.ge'>Открыть CaucasHub</a>"
    )
    await send_tg_message(chat_id, text)
