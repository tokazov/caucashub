"""
Telegram уведомления для CaucasHub.
Отправляет сообщения на языке пользователя (ru / ge).
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


# ── Шаблоны уведомлений ──────────────────────────────────────────────

TEMPLATES = {
    "ru": {
        "new_response": (
            "📩 <b>Новый отклик на ваш груз</b>\n\n"
            "🚛 Перевозчик: <b>{carrier}</b>\n"
            "📍 Маршрут: {from_city} → {to_city}\n"
            "💰 Ставка: {price} {cur}\n\n"
            "Войдите в <a href='https://caucashub.ge'>CaucasHub</a> чтобы принять или отклонить."
        ),
        "response_accepted": (
            "✅ <b>Ваш отклик принят!</b>\n\n"
            "📦 Грузовладелец: <b>{shipper}</b>\n"
            "📍 Маршрут: {from_city} → {to_city}\n"
            "💰 Сумма: {price} {cur}\n\n"
            "Войдите в <a href='https://caucashub.ge'>CaucasHub</a> для управления сделкой."
        ),
        "deal_status": (
            "🔄 <b>Статус сделки обновлён</b>\n\n"
            "📋 Сделка: <b>{deal_num}</b>\n"
            "📍 {from_city} → {to_city}\n"
            "📌 Статус: <b>{status}</b>\n\n"
            "<a href='https://caucashub.ge'>Открыть CaucasHub</a>"
        ),
        "deal_completed": (
            "🏆 <b>Сделка завершена!</b>\n\n"
            "📋 {deal_num} | {from_city} → {to_city}\n"
            "💰 Сумма: <b>{price} {cur}</b>\n\n"
            "Акт выполненных работ доступен в <a href='https://caucashub.ge'>личном кабинете</a>.\n"
            "Не забудьте оценить партнёра! ⭐"
        ),
        "welcome": (
            "👋 <b>გამარჯობა, {name}!</b>\n\n"
            "Теперь вы будете получать уведомления о:\n"
            "• 📩 Новых откликах на ваши грузы\n"
            "• ✅ Принятых откликах\n"
            "• 🔄 Изменениях статуса сделок\n"
            "• 🏆 Завершённых сделках\n\n"
            "<a href='https://caucashub.ge'>Открыть CaucasHub</a>"
        ),
        "start_no_token": (
            "👋 Это бот уведомлений <b>CaucasHub.ge</b>\n\n"
            "Для привязки аккаунта:\n"
            "1. Войдите на <a href='https://caucashub.ge'>caucashub.ge</a>\n"
            "2. Откройте профиль → Telegram-уведомления\n"
            "3. Нажмите «Подключить Telegram»"
        ),
        "invalid_token": (
            "❌ Ссылка недействительна или уже использована.\n"
            "Сгенерируйте новую в настройках профиля CaucasHub."
        ),
        "only_notifications": (
            "Этот бот только для уведомлений 🔔\n"
            "Управляйте грузами на <a href='https://caucashub.ge'>caucashub.ge</a>"
        ),
    },
    "ge": {
        "new_response": (
            "📩 <b>თქვენს ტვირთზე ახალი გამოხმაურება</b>\n\n"
            "🚛 გადამზიდი: <b>{carrier}</b>\n"
            "📍 მარშრუტი: {from_city} → {to_city}\n"
            "💰 ფასი: {price} {cur}\n\n"
            "შედით <a href='https://caucashub.ge'>CaucasHub</a>-ზე მისაღებად ან უარსაყოფად."
        ),
        "response_accepted": (
            "✅ <b>თქვენი გამოხმაურება მიღებულია!</b>\n\n"
            "📦 დამქირავებელი: <b>{shipper}</b>\n"
            "📍 მარშრუტი: {from_city} → {to_city}\n"
            "💰 თანხა: {price} {cur}\n\n"
            "შედით <a href='https://caucashub.ge'>CaucasHub</a>-ზე გარიგების სამართავად."
        ),
        "deal_status": (
            "🔄 <b>გარიგების სტატუსი განახლდა</b>\n\n"
            "📋 გარიგება: <b>{deal_num}</b>\n"
            "📍 {from_city} → {to_city}\n"
            "📌 სტატუსი: <b>{status}</b>\n\n"
            "<a href='https://caucashub.ge'>CaucasHub-ის გახსნა</a>"
        ),
        "deal_completed": (
            "🏆 <b>გარიგება დასრულდა!</b>\n\n"
            "📋 {deal_num} | {from_city} → {to_city}\n"
            "💰 თანხა: <b>{price} {cur}</b>\n\n"
            "სამუშაოს ჩაბარების აქტი ხელმისაწვდომია <a href='https://caucashub.ge'>პირად კაბინეტში</a>.\n"
            "არ დაგავიწყდეთ პარტნიორის შეფასება! ⭐"
        ),
        "welcome": (
            "👋 <b>კეთილი იყოს თქვენი მობრძანება CaucasHub-ში, {name}!</b>\n\n"
            "ახლა მიიღებთ შეტყობინებებს:\n"
            "• 📩 თქვენს ტვირთებზე ახალი გამოხმაურებების შესახებ\n"
            "• ✅ მიღებული გამოხმაურებების შესახებ\n"
            "• 🔄 გარიგებების სტატუსის ცვლილებების შესახებ\n"
            "• 🏆 დასრულებული გარიგებების შესახებ\n\n"
            "<a href='https://caucashub.ge'>CaucasHub-ის გახსნა</a>"
        ),
        "start_no_token": (
            "👋 ეს არის <b>CaucasHub.ge</b>-ის შეტყობინებების ბოტი\n\n"
            "ანგარიშის მისაბმელად:\n"
            "1. შედით <a href='https://caucashub.ge'>caucashub.ge</a>-ზე\n"
            "2. გახსენით პროფილი → Telegram-შეტყობინებები\n"
            "3. დააჭირეთ «Telegram-ის მიბმა»"
        ),
        "invalid_token": (
            "❌ ბმული არასწორია ან უკვე გამოყენებულია.\n"
            "CaucasHub-ის პარამეტრებში შექმენით ახალი."
        ),
        "only_notifications": (
            "ეს ბოტი მხოლოდ შეტყობინებებისთვისაა 🔔\n"
            "მართეთ ტვირთები <a href='https://caucashub.ge'>caucashub.ge</a>-ზე"
        ),
    }
}


def _t(lang: str, key: str) -> str:
    """Получить шаблон на нужном языке (fallback: ru)."""
    return TEMPLATES.get(lang, TEMPLATES["ru"]).get(key, TEMPLATES["ru"][key])


# ── Функции уведомлений ──────────────────────────────────────────────

async def notify_new_response(chat_id, carrier_name: str, from_city: str, to_city: str,
                               price: float, cur: str, lang: str = "ru"):
    text = _t(lang, "new_response").format(
        carrier=carrier_name, from_city=from_city, to_city=to_city,
        price=int(price) if price == int(price) else price, cur=cur
    )
    await send_tg_message(chat_id, text)


async def notify_response_accepted(chat_id, shipper_name: str, from_city: str, to_city: str,
                                    price: float, cur: str, lang: str = "ru"):
    text = _t(lang, "response_accepted").format(
        shipper=shipper_name, from_city=from_city, to_city=to_city,
        price=int(price) if price == int(price) else price, cur=cur
    )
    await send_tg_message(chat_id, text)


async def notify_deal_status(chat_id, status_label: str, deal_num: str,
                              from_city: str, to_city: str, lang: str = "ru"):
    text = _t(lang, "deal_status").format(
        deal_num=deal_num, from_city=from_city, to_city=to_city, status=status_label
    )
    await send_tg_message(chat_id, text)


async def notify_deal_completed(chat_id, deal_num: str, from_city: str, to_city: str,
                                 price: float, cur: str, lang: str = "ru"):
    text = _t(lang, "deal_completed").format(
        deal_num=deal_num, from_city=from_city, to_city=to_city,
        price=int(price) if price == int(price) else price, cur=cur
    )
    await send_tg_message(chat_id, text)


async def notify_welcome(chat_id, name: str, lang: str = "ru"):
    text = _t(lang, "welcome").format(name=name)
    await send_tg_message(chat_id, text)


def get_text(lang: str, key: str, **kwargs) -> str:
    """Утилита: получить текст шаблона с подстановкой."""
    return _t(lang, key).format(**kwargs)
