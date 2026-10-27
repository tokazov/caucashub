"""Business events are inserted in the caller's transaction, never sent here."""
from datetime import timezone
from decimal import Decimal
from html import escape
import math
from sqlalchemy import select
from app.models.notification import Notification, NotificationDelivery

KINDS = frozenset({"new_response", "new_transport_request", "deal_created",
                   "delivery_waiting", "delivery_confirmation_required", "deal_completed",
                   "response_rejected", "transport_request_rejected"})
_ID_FIELDS = {"load_id", "transport_offer_id", "transport_request_id", "response_id", "deal_id"}
_TEXT_FIELDS = {"source", "deal_number", "from_city", "to_city", "currency"}

def utc_iso(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc)).isoformat()

def clean_data(data):
    result = {}
    for key, value in (data or {}).items():
        if key in _ID_FIELDS and isinstance(value, int) and not isinstance(value, bool) and value > 0:
            result[key] = value
        elif key in _TEXT_FIELDS and isinstance(value, str):
            result[key] = value[:500]
        elif key == "price" and isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            number = float(value)
            if math.isfinite(number):
                result[key] = number
    return result

async def enqueue_event(db, *, event_key, kind, recipient_ids, actor_id=None, data=None):
    if kind not in KINDS or not isinstance(event_key, str) or not 1 <= len(event_key) <= 160:
        raise ValueError("Unsupported notification event")
    recipients = sorted(set(recipient_ids))
    if any(not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0 for uid in recipients):
        raise ValueError("Invalid notification recipient")
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Notification events require a supported transactional store")
    rows = []
    for recipient in recipients:
        statement = insert(Notification).values(
            event_key=event_key, kind=kind, recipient_id=recipient,
            actor_id=actor_id, data=clean_data(data),
        ).on_conflict_do_nothing(index_elements=["event_key", "recipient_id"]).returning(Notification.id)
        identifier = (await db.execute(statement)).scalar_one_or_none()
        if identifier is None:
            row = (await db.execute(select(Notification).where(
                Notification.event_key == event_key, Notification.recipient_id == recipient))).scalar_one()
        else:
            row = await db.get(Notification, identifier)
            if kind != "delivery_waiting":
                db.add_all([NotificationDelivery(notification_id=identifier, channel=channel)
                            for channel in ("email", "telegram")])
        rows.append(row)
    await db.flush()
    return rows

def normalize_language(value):
    return "ge" if str(value or "").lower() in ("ge", "ka", "ka-ge") else "ru"

_TITLES = {
    "new_response": ("Новый отклик на груз", "ტვირთზე ახალი გამოხმაურებაა"),
    "new_transport_request": ("Новый запрос на транспорт", "ტრანსპორტზე ახალი მოთხოვნაა"),
    "deal_created": ("Сделка подтверждена", "გარიგება დადასტურებულია"),
    "delivery_waiting": ("Ожидаем вторую сторону", "ველოდებით მეორე მხარეს"),
    "delivery_confirmation_required": ("Подтвердите доставку", "დაადასტურეთ მიწოდება"),
    "deal_completed": ("Сделка завершена", "გარიგება დასრულებულია"),
    "response_rejected": ("Отклик отклонён", "გამოხმაურება უარყოფილია"),
    "transport_request_rejected": ("Запрос отклонён", "მოთხოვნა უარყოფილია"),
}
_BODIES = {
    "new_response": ("На ваш груз поступил новый отклик. Посмотрите его в кабинете.",
                     "თქვენს ტვირთზე ახალი გამოხმაურებაა. ნახეთ პირად კაბინეტში."),
    "new_transport_request": ("На ваш транспорт поступил новый запрос. Посмотрите его в кабинете.",
                              "თქვენს ტრანსპორტზე ახალი მოთხოვნაა. ნახეთ პირად კაბინეტში."),
    "deal_created": ("Условия приняты. Сделка и контакты второй стороны доступны в кабинете.",
                     "პირობები მიღებულია. გარიგება და მეორე მხარის კონტაქტები პირად კაბინეტშია."),
    "delivery_waiting": ("Ваше подтверждение сохранено. Ждём подтверждения второй стороны.",
                         "თქვენი დადასტურება შენახულია. ველოდებით მეორე მხარის დადასტურებას."),
    "delivery_confirmation_required": ("Вторая сторона подтвердила доставку. Подтвердите её в разделе «Сделки».",
                                       "მეორე მხარემ მიწოდება დაადასტურა. დაადასტურეთ იგი „გარიგებების“ განყოფილებაში."),
    "deal_completed": ("Обе стороны подтвердили доставку. Акт PDF и оценка доступны в кабинете.",
                       "ორივე მხარემ მიწოდება დაადასტურა. PDF აქტი და შეფასება პირად კაბინეტშია."),
    "response_rejected": ("Ваш отклик на груз отклонён. Статус обновлён в кабинете.",
                          "ტვირთზე თქვენი გამოხმაურება უარყოფილია. სტატუსი პირად კაბინეტში განახლდა."),
    "transport_request_rejected": ("Ваш запрос на транспорт отклонён. Статус обновлён в кабинете.",
                                   "ტრანსპორტზე თქვენი მოთხოვნა უარყოფილია. სტატუსი პირად კაბინეტში განახლდა."),
}

def render_message(notification, language, actor_name=""):
    index = 1 if normalize_language(language) == "ge" else 0
    title = _TITLES[notification.kind][index]
    body = _BODIES[notification.kind][index]
    data = clean_data(notification.data)
    route = " → ".join(str(data.get(key, "—")) for key in ("from_city", "to_city"))
    reference = str(data.get("deal_number") or "")
    amount = (f"{data['price']:,.2f} {data.get('currency', 'GEL')}" if 'price' in data else '')
    details = [value for value in (reference, route if route != "— → —" else "", actor_name, amount) if value]
    plain = title + "\n\n" + body
    if details:
        plain += "\n\n" + "\n".join(details)
    # Only escaped neutral metadata enters provider HTML. No contact/message snapshots.
    safe = escape(plain).replace("\n", "<br>")
    url = "https://www.caucashub.ge/"
    html = ('<div style="font-family:Arial,sans-serif;color:#1a1a2e">'
            '<h2>CaucasHub.ge</h2><p>' + safe + '</p>'
            '<p><a href="' + url + '">CaucasHub.ge</a></p></div>')
    # Telegram uses plain text; deliberately no parse_mode/HTML interpolation.
    return {"subject": "CaucasHub: " + title, "text": plain + "\n\n" + url, "html": html}
