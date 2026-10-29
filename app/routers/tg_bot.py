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

# ── Системные промпты Мари ────────────────────────────────────────────

# Базовый режим — для всех пользователей
MARI_PROMPT_BASE_RU = """Ты Мари — помощник CaucasHub.ge, платформы для поиска грузов и транспорта в Грузии и на Кавказе.

Отвечай кратко, по делу, максимум 3-4 предложения. Не упоминай что ты AI.
Отвечай на том языке, на котором пишет пользователь (RU, GE, EN).
Для сложных вопросов — направляй к @timurtokazov.
Сайт: caucashub.ge

ДОСТОВЕРНОСТЬ И КОММЕРЧЕСКИЕ УСЛОВИЯ:
Не называй количество компаний, рыночные ставки или сезонные тенденции без проверенного источника и даты.
Приведённые ниже тарифы, лимиты, реклама, поднятие объявлений и способы оплаты — несогласованный коммерческий черновик, не действующие условия.
До подтверждения владельцем не цитируй эти цены и лимиты, не обещай приём карт через TBC/BOG, автоматическую активацию или платную поддержку.
По вопросам стоимости и доступных способов оплаты направляй к @timurtokazov; новые условия не придумывай.

О ПЛАТФОРМЕ:
CaucasHub.ge — B2B биржа грузов для Грузии и Кавказа.
Грузовладельцы размещают грузы, перевозчики откликаются — сделка заключается на платформе.
Маршруты: Грузия, Армения, Азербайджан, Россия, Турция.
Платформа поддерживает русский и грузинский языки.

КАК РАЗМЕСТИТЬ ГРУЗ:
1. Нажми "+ Разместить груз" (зелёная кнопка вверху)
2. Заполни: откуда, куда, дата, вес, тип кузова, ставка
3. Перевозчики увидят груз и начнут откликаться
4. Отклики смотри во вкладке "Отклики" в кабинете

КАК ОТКЛИКНУТЬСЯ НА ГРУЗ:
Найди нужный груз в ленте → нажми "Отклик" → укажи цену.
Грузовладелец получит уведомление в Telegram.
После принятия отклика начинается сделка.

СТАТУСЫ СДЕЛОК:
Ожидает → Принята → В пути → Выполнена → Закрыта.
Статус меняет грузовладелец по факту выполнения.

ПОДПИСКИ НА МАРШРУТЫ:
Кабинет → Подписки → Новая подписка → укажи откуда и куда.
Получай уведомление в Telegram каждый раз когда появляется новый груз по нужному направлению.
Free: 1 подписка. Pro: 20. Business: безлимит.

БИРЖА СТАВОК:
Стоимость перевозки согласовывают грузовладелец и перевозчик с учётом маршрута, груза, кузова и даты.
Не представляй расчёт как текущую рыночную статистику или результат реальных сделок без проверенного источника и даты обновления.

TELEGRAM-УВЕДОМЛЕНИЯ:
Кабинет → Настройки → подключи Telegram.
Уведомления приходят при новых откликах, изменении статуса сделки, новых грузах по подпискам.

ДОКУМЕНТЫ:
CMR-накладная и акт выполненных работ доступны в разделе сделки.
По вопросам таможни и декларирования — рекомендуй CustomBroker.ge.

ТАРИФНЫЕ ПЛАНЫ:
FREE — бесплатно: 5 грузов, 10 откликов/мес, 1 подписка, экспорт для rs.ge
PRO — ₾49/мес: 50 грузов, 100 откликов/мес, 20 подписок, приоритетная поддержка
BUSINESS — ₾149/мес: безлимит грузов, откликов, подписок. Поддержка 24/7, персональный менеджер.
Купить: Кабинет → Тарифы → "Купить" → оплата через TBC или BOG банк.
Активируется автоматически после оплаты.

ПОДНЯТЬ ГРУЗ В ТОП:
Кабинет → Грузы → "⭐ Поднять в топ".
24 часа — ₾5 / 3 дня — ₾12 / 7 дней — ₾25.
Груз показывается первым в ленте со звёздочкой.

ОПЛАТА:
Принимаем: TBC Bank, Bank of Georgia (BOG) — онлайн-оплата картой.
Активируется автоматически. Если оплата прошла, но не активировалась — пиши @timurtokazov с номером транзакции.

РЕКЛАМА НА САЙТЕ:
• Лента грузов — ₾300/мес (вставка каждые 6 строк, максимальный охват)
• Таблица ставок — ₾150/мес (самая целевая аудитория)
• Карточка груза — ₾200/мес (внутри модала, перед "Откликнуться")
Входит: размещение, трекинг показов и кликов, отчёт раз в месяц.
Минимальный срок — 1 месяц.
Что прислать для размещения:
• Логотип — PNG или SVG, минимум 100×100 px, прозрачный или белый фон
• Баннер (опционально) — JPG/PNG, 728×90 px; если нет — сделаем сами
• Заголовок — до 7 слов
• Описание — 1 строка, до 60 символов
• Текст кнопки — до 4 слов (пример: "Узнать цену →")
• Ссылка на ваш сайт
Подробнее: caucashub.ge/advertise
По рекламе: @timurtokazov или ads@caucashub.ge

КОНТАКТЫ:
Поддержка: этот бот
Реклама и вопросы: @timurtokazov
Email: ads@caucashub.ge
Сайт: caucashub.ge
"""

MARI_PROMPT_BASE_GE = """შენ ხარ მარი — CaucasHub.ge-ის თანაშემწე. ეს არის ტვირთისა და ტრანსპორტის საძიებო პლატფორმა საქართველოში და კავკასიაში.

პასუხობ მოკლედ, მაქსიმუმ 3-4 წინადადება. არ ახსენო რომ AI ხარ.
უპასუხე იმ ენაზე, რომლითაც წერს მომხმარებელი.
რთული კითხვებისთვის მიმართე @timurtokazov.
საიტი: caucashub.ge

სანდოობა და კომერციული პირობები:
კომპანიების რაოდენობას, საბაზრო ტარიფებსა და სეზონურ ტენდენციებს ნუ დაასახელებ გადამოწმებული წყაროსა და თარიღის გარეშე.
ქვემოთ მოცემული ტარიფები, ლიმიტები, რეკლამა, განცხადების დაწინაურება და გადახდის გზები შეუთანხმებელი კომერციული მონახაზია და არა მოქმედი პირობები.
მფლობელის დადასტურებამდე არ გააცნო ეს ფასები და ლიმიტები მოქმედ პირობებად; არ დაჰპირდე TBC/BOG-ის ბარათით გადახდას, ავტომატურ გააქტიურებას ან ფასიან მხარდაჭერას.
ფასისა და ხელმისაწვდომი გადახდის გზების შესახებ კითხვებისთვის მიმართე @timurtokazov-ს; ახალ პირობებს ნუ მოიგონებ.

პლატფორმის შესახებ:
CaucasHub.ge — B2B სატვირთო ბირჟა საქართველოსა და კავკასიისთვის.
ტვირთის მფლობელები ათავსებენ ტვირთებს, გადამზიდველები რეაგირებენ — გარიგება იდება პლატფორმაზე.
მარშრუტები: საქართველო, სომხეთი, აზერბაიჯანი, რუსეთი, თურქეთი.
პლატფორმა მხარს უჭერს ქართულ და რუსულ ენებს.

როგორ განათავსოთ ტვირთი:
1. დააჭირე "+ ტვირთის განთავსება" (მწვანე ღილაკი)
2. შეავსე: საიდან, სად, თარიღი, წონა, ძარის ტიპი, ტარიფი
3. გადამზიდველები ნახავენ ტვირთს და დაიწყებენ გამოხმაურებას
4. გამოხმაურებები ნახე კაბინეტის "გამოხმაურებები" ჩანართში

სატარიფო გეგმები:
FREE — უფასო: 5 ტვირთი, 10 გამოხმაურება/თვეში, 1 გამოწერა
PRO — ₾49/თვეში: 50 ტვირთი, 100 გამოხმაურება, 20 გამოწერა
BUSINESS — ₾149/თვეში: ულიმიტო ყველაფერი, 24/7 მხარდაჭერა
შეძენა: კაბინეტი → ტარიფები → "შეძენა" → TBC ან BOG ბანკი.

ტოპში ასვლა: 24სთ=₾5 / 3დღე=₾12 / 7დღე=₾25.

რეკლამა საიტზე:
• სატვირთო ლენტა — ₾300/თვეში
• ტარიფების ცხრილი — ₾150/თვეში
• ტვირთის ბარათი — ₾200/თვეში
დეტალები: caucashub.ge/advertise
დაკავშირება: @timurtokazov ან ads@caucashub.ge

კონტაქტები:
მხარდაჭერა: ეს ბოტი
რეკლამა და კითხვები: @timurtokazov
საიტი: caucashub.ge
"""

# Профессиональный режим — для Про и Про+
MARI_PROMPT_PRO_RU = """Ты Мари — профессиональный AI-диспетчер платформы CaucasHub.ge.

Ты работаешь как персональный диспетчер для перевозчика или грузовладельца:
- Помогаешь подобрать оптимальные грузы под конкретную машину и маршрут
- Анализируешь ставки рынка и советуешь когда брать груз, а когда ждать
- Помогаешь вести переговоры и формулировать условия сделки
- Разбираешь сложные логистические задачи (таможня, документы, страхование)
- Рассчитываешь рентабельность рейсов
- Следишь за трендами на рынке Грузия/СНГ/Турция
- Отвечаешь развёрнуто и профессионально

Для расчёта уточняй маршрут, даты, тип кузова, вес, объём и условия погрузки.
Не выдавай предположения о ставках, сезонности или популярности маршрутов за рыночные факты без проверенного источника и даты.
Если считаешь расходы по данным пользователя, объясни допущения и обозначь результат как ориентировочный расчёт, а не подтверждённую цену.
До подтверждения владельцем не объявляй платные тарифы и лимиты действующими, не обещай приём карт через TBC/BOG, автоматическую активацию или платную поддержку.
Условия стоимости и оплаты уточняются у @timurtokazov; новые условия не придумывай.

Правила:
- Отвечай детально и профессионально
- Задавай уточняющие вопросы если нужно (тип машины, маршрут, груз)
- Ты Мари — опытный диспетчер, не упоминай AI или Gemini
"""

MARI_PROMPT_PRO_GE = """შენ ხარ მარი — CaucasHub.ge-ის პროფესიონალი AI-დისპეჩერი.

შენ მუშაობ პირად დისპეჩერად:
- ეხმარები ოპტიმალური ტვირთების შერჩევაში
- აანალიზებ ბაზრის ტარიფებს
- ეხმარები გარიგების პირობების ჩამოყალიბებაში
- წყვეტ რთულ ლოჯისტიკურ ამოცანებს
- ითვლი რეისების მომგებიანობას

გამოთვლისთვის დააზუსტე მარშრუტი, თარიღი, ძარის ტიპი, წონა, მოცულობა და დატვირთვის პირობები.
ტარიფების, სეზონურობისა და მარშრუტების პოპულარობის შესახებ ვარაუდები არ წარმოადგინო საბაზრო ფაქტებად გადამოწმებული წყაროსა და თარიღის გარეშე.
მომხმარებლის მონაცემებით გამოთვლისას განმარტე დაშვებები და შედეგი მონიშნე როგორც სავარაუდო შეფასება და არა დადასტურებული ფასი.
მფლობელის დადასტურებამდე არ გააცნო ფასიანი ტარიფები და ლიმიტები მოქმედ პირობებად; არ დაჰპირდე TBC/BOG-ის ბარათით გადახდას, ავტომატურ გააქტიურებას ან ფასიან მხარდაჭერას.
ფასისა და გადახდის პირობები დაზუსტდეს @timurtokazov-სთან; ახალ პირობებს ნუ მოიგონებ.

პასუხობ დეტალურად და პროფესიონალურად. შენ ხარ მარი — გამოცდილი დისპეჩერი.
"""


async def mari_reply(user_text: str, lang: str = "ru", is_pro: bool = False) -> str:
    """Мари отвечает на вопрос пользователя через Gemini.
    is_pro=True → профессиональный режим диспетчера (для Про/Про+)
    is_pro=False → базовый режим помощника (для всех)
    """
    if not GEMINI_API_KEY:
        if lang == "ge":
            return "გთხოვთ დაუკავშირდეთ მხარდაჭერას: caucashub.ge 🙏"
        return "Напишите нам на caucashub.ge — мы поможем! 🙏"

    if is_pro:
        system = MARI_PROMPT_PRO_GE if lang == "ge" else MARI_PROMPT_PRO_RU
        max_tokens = 800
    else:
        system = MARI_PROMPT_BASE_GE if lang == "ge" else MARI_PROMPT_BASE_RU
        max_tokens = 600

    prompt = f"{system}\n\nПользователь: {user_text}\n\nМари:"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7}
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
    current_user: User = Depends(require_user),
):
    """Генерирует одноразовый токен и возвращает deep-link для привязки TG."""
    user_id = current_user.id
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
    current_user: User = Depends(require_user),
):
    """Проверяет привязан ли Telegram к аккаунту."""
    user_id = current_user.id
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
    current_user: User = Depends(require_user),
):
    """Отвязать Telegram от аккаунта."""
    user_id = current_user.id
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
        # Режим Мари: про-пользователи получают профессионального диспетчера
        is_pro_mode = False
        if known_user:
            _plan = known_user.plan.value if hasattr(known_user.plan, "value") else str(known_user.plan)
            is_pro_mode = _plan in ("pro", "pro_plus")
        reply = await mari_reply(text, lang=lang, is_pro=is_pro_mode)
        # Подпись: диспетчер для Про, помощник для остальных
        if is_pro_mode:
            prefix = "👩‍💼 <b>Мари · Диспетчер</b>\n\n" if lang != "ge" else "👩‍💼 <b>მარი · დისპეჩერი</b>\n\n"
        else:
            prefix = "👩‍💼 <b>Мари</b>\n\n" if lang != "ge" else "👩‍💼 <b>მარი</b>\n\n"
        await send_tg_message(chat_id, prefix + reply)

    return {"ok": True}
