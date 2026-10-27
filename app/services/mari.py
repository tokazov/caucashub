"""Validated conversation state and exact, public listing matching for Mari.

The model proposes a draft or filters. Application code selects listings and
computes readiness; model output never publishes or accepts anything.
"""
import math
import re
from datetime import timedelta

from app.services.cities_seed import CITIES_SEED
from app.services.listing_freshness import loading_day, listing_day_start, parse_loading_day


def city_key(value):
    value = re.sub(r"^(?:г\.?|город|ქალაქი)\s+", "", str(value or "").strip(), flags=re.I)
    return re.sub(r"[\W_]+", " ", value.split(",")[0].casefold()).strip()


CITY_ALIASES = {}
for city in CITIES_SEED:
    for name in [city["name_ru"], city.get("name_ge")]:
        if name:
            CITY_ALIASES[city_key(name)] = city_key(city["name_ru"])
for name, canonical in {
    "tbilisi": "Тбилиси", "batumi": "Батуми", "kutaisi": "Кутаиси",
    "poti": "Поти", "rustavi": "Рустави", "gori": "Гори",
    "moscow": "Москва", "yerevan": "Ереван", "baku": "Баку", "istanbul": "Стамбул",
}.items():
    CITY_ALIASES[city_key(name)] = city_key(canonical)


def same_city(left, right):
    a, b = city_key(left), city_key(right)
    return bool(a and b) and CITY_ALIASES.get(a, a) == CITY_ALIASES.get(b, b)


TRUCK_ALIASES = {
    "тент": "tent", "ტენტი": "tent", "рефрижератор": "ref", "რეფრიჟერატორი": "ref",
    "фургон": "gazel", "газель": "gazel", "ფურგონი": "gazel",
    "бортовой": "bort", "борт": "bort", "open": "bort", "ღია": "bort",
    "контейнер": "container", "კონტეინერი": "container", "autovoz": "auto",
    "автовоз": "auto", "lowboy": "evacuator", "эвакуатор": "evacuator",
}
TRUCK_TYPES = {"tent", "ref", "reftent", "megatent", "bort", "termos", "gazel",
               "container", "auto", "evacuator", "cistern", "grain", "dump", "other"}


def truck_key(value):
    value = str(getattr(value, "value", value) or "").strip().casefold()
    value = TRUCK_ALIASES.get(value, value)
    return value if value in TRUCK_TYPES else None


def positive_number(value, maximum=100000):
    if isinstance(value, bool):
        return None
    try:
        scale = 1
        if isinstance(value, str):
            value = value.strip().casefold().replace(",", ".")
            match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(кг|kg|კგ|т|тн|тонн[аы]?|t|ტ)?", value)
            if not match:
                return None
            scale = 1000 if match[2] in {"т", "тн", "тонна", "тонны", "тонн", "t", "ტ"} else 1
            value = match[1]
        result = float(value) * scale
        return result if math.isfinite(result) and 0 < result <= maximum else None
    except (ValueError, TypeError):
        return None


def calendar_day(value):
    if not value:
        return None
    today = loading_day(listing_day_start())
    relative = {"today": 0, "сегодня": 0, "დღეს": 0,
                "tomorrow": 1, "завтра": 1, "ხვალ": 1}
    text = str(value).strip().casefold()
    if text in relative:
        return (today + timedelta(days=relative[text])).isoformat()
    try:
        return loading_day(parse_loading_day(text)).isoformat()
    except (ValueError, TypeError):
        return None


INTENTS = {"search_load", "search_transport", "post_load", "post_transport", "help"}
FIELDS = {"role", "intent", "from", "to", "weight_cap", "capacity_kg", "truck", "date",
          "date_end", "cargo_desc", "price", "currency", "scope", "from_country", "to_country"}


def clean_state(previous, proposed, action=None, user_role=None, scope="local", clear_fields=None):
    merged = {key: value for key, value in previous.items() if key in FIELDS}
    for key in clear_fields or []:
        if key in FIELDS:
            merged.pop(key, None)
    merged.update({key: value for key, value in proposed.items() if key in FIELDS and value is not None})
    state = {}
    for key in ["from", "to", "cargo_desc", "from_country", "to_country"]:
        value = merged.get(key)
        if isinstance(value, str) and value.strip():
            state[key] = value.strip()[:500 if key == "cargo_desc" else 100]
    for key in ["weight_cap", "capacity_kg", "price"]:
        value = positive_number(merged.get(key), 10000000 if key == "price" else 100000)
        if value is not None:
            state[key] = value
    for key in ["date", "date_end"]:
        value = calendar_day(merged.get(key))
        if value:
            state[key] = value
    truck = truck_key(merged.get("truck"))
    if truck:
        state["truck"] = truck
    state["scope"] = merged.get("scope") if merged.get("scope") in {"local", "intl"} else scope
    state["currency"] = merged.get("currency") if merged.get("currency") in {"GEL", "USD"} else ("USD" if state["scope"] == "intl" else "GEL")
    role = merged.get("role") or user_role
    state["role"] = role if role in {"carrier", "shipper", "both"} else None
    intent = merged.get("intent")
    if intent not in INTENTS:
        intent = action if action in INTENTS else None
    if intent is None and (action == "search" or proposed.get("ready_to_search") is True):
        intent = "search_transport" if state["role"] == "shipper" else "search_load"
    if intent is None and proposed.get("ready_to_post_transport") is True:
        intent = "post_transport"
    if intent is None and proposed.get("ready_to_post") is True:
        intent = "post_load"
    ambiguous = proposed.get("awaiting_role_clarification") is True
    if ambiguous:
        intent = None
    state["intent"] = intent
    state["awaiting_role_clarification"] = ambiguous
    route = bool(state.get("from") and state.get("to"))
    state["ready_to_search"] = bool(intent in {"search_load", "search_transport"} and state.get("from"))
    complete = route and draft_question(state, "ru") is None
    state["ready_to_post"] = bool(intent == "post_load" and complete)
    state["ready_to_post_transport"] = bool(intent == "post_transport" and complete)
    return state


def draft_question(state, language):
    """Ask for one missing form field; never turn an incomplete draft into a claim."""
    if state.get("intent") not in {"post_load", "post_transport"}:
        return None
    transport = state["intent"] == "post_transport"
    kg = (state.get("capacity_kg") or state.get("weight_cap")) if transport else state.get("weight_cap")
    today = loading_day(listing_day_start()).isoformat()
    questions = [
        (not state.get("from"), "Из какого города отправление?", "რომელი ქალაქიდან არის გამგზავრება?"),
        (not state.get("to"), "В какой город доставка?", "რომელ ქალაქშია მიწოდება?"),
        (not kg or kg < (100 if transport else 1) or kg > (100000 if transport else 50000),
         "Какой вес груза в килограммах (до 50 000)?" if not transport else "Какая вместимость машины в килограммах (от 100)?",
         "რამდენი კილოგრამია ტვირთი (მაქს. 50 000)?" if not transport else "რამდენი კილოგრამია მანქანის ტევადობა (მინ. 100)?"),
        (not state.get("truck"), "Какой тип кузова?", "რა ტიპის ძარაა?"),
        (not state.get("date") or state["date"] < today,
         "На какую дату планируется погрузка? Укажите сегодня или позднее.", "როდის იგეგმება დატვირთვა? მიუთითეთ დღევანდელი ან მომავალი თარიღი."),
        (bool(state.get("date_end") and state.get("date") and state["date_end"] < state["date"]),
         "Дата окончания раньше начала. Какую дату окончания указать?", "დასრულების თარიღი დასაწყისზე ადრეა. რომელი თარიღი მივუთითო?"),
        (not transport and not state.get("price"),
         f"Какую ставку указать в {state.get('currency', 'GEL')}?", f"რა ფასი მივუთითო {state.get('currency', 'GEL')}-ში?"),
    ]
    for missing, ru, ge in questions:
        if missing:
            return ge if language == "ge" else ru
    return None


def listing_matches(row, state, transport=False):
    if state.get("from") and not same_city(state["from"], row.from_city):
        return False
    if state.get("to") and not same_city(state["to"], row.to_city):
        return False
    if state.get("truck") and truck_key(row.truck_type) != state["truck"]:
        return False
    kg = state.get("capacity_kg") or state.get("weight_cap")
    weight = row.capacity_kg if transport else row.weight_kg
    if kg and ((transport and weight < kg) or (not transport and weight > kg)):
        return False
    requested = state.get("date")
    if requested:
        start = row.available_from if transport else row.load_date
        end = (row.available_to or start) if transport else (row.load_date_end or start)
        if not loading_day(start).isoformat() <= requested <= loading_day(end).isoformat():
            return False
    return True


def public_listing(row, transport=False):
    intl = getattr(getattr(row, "scope", None), "value", None) == "intl"
    if transport:
        price = row.price if row.price is not None else row.price_usd
        currency = "₾" if row.price is not None else "$"
    else:
        price = row.price_usd if intl else row.price_gel
        currency = "$" if intl else "₾"
    return {"id": row.id, "from": row.from_city, "to": row.to_city,
            "kg": row.capacity_kg if transport else row.weight_kg,
            "truck": truck_key(row.truck_type), "price": float(price) if price is not None else None,
            "cur": currency, "kind": "transport" if transport else "load"}
