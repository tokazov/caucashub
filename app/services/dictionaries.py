"""
Справочники CaucasHub — единственный источник истины (Трек 9).
Используется в API /api/dictionaries/* и на фронте при старте.
"""

TRUCK_TYPES = [
    {"id": "tent",      "label_ru": "Тент",          "label_ge": "ტენტი",            "icon": "🚛"},
    {"id": "ref",       "label_ru": "Рефрижератор",  "label_ge": "რეფრიჟერატორი",    "icon": "❄️"},
    {"id": "bort",      "label_ru": "Борт",           "label_ge": "ბორტიანი",         "icon": "🚚"},
    {"id": "termos",    "label_ru": "Термос",         "label_ge": "თერმოსი",          "icon": "🌡️"},
    {"id": "gazel",     "label_ru": "Фургон / Газель","label_ge": "ფურგონი",          "icon": "🚐"},
    {"id": "container", "label_ru": "Контейнер",      "label_ge": "კონტეინერი",       "icon": "📦"},
    {"id": "auto",      "label_ru": "Автовоз",        "label_ge": "ავტოვოზი",         "icon": "🚗"},
    {"id": "tanker",    "label_ru": "Цистерна",       "label_ge": "ტანკერი",          "icon": "⛽"},
    {"id": "lowboy",    "label_ru": "Низкорамник",    "label_ge": "დაბალბარი",        "icon": "🏗️"},
    {"id": "other",     "label_ru": "Другой",         "label_ge": "სხვა",             "icon": "🔧"},
]

PAYMENT_TYPES = [
    {"id": "cash",       "label_ru": "Наличные",       "label_ge": "ნაღდი ანგარიშსწორება"},
    {"id": "bank_3d",    "label_ru": "Безнал 3 дня",   "label_ge": "უნაღდო 3 დღე"},
    {"id": "bank_7d",    "label_ru": "Безнал 7 дней",  "label_ge": "უნაღდო 7 დღე"},
    {"id": "prepay_50",  "label_ru": "50% предоплата", "label_ge": "50% წინასწარ"},
    {"id": "prepay_100", "label_ru": "100% предоплата","label_ge": "100% წინასწარ"},
]

ORG_TYPES = [
    {"id": "llc",     "label_ru": "ООО",              "label_ge": "შპს"},
    {"id": "ie",      "label_ru": "ИП",               "label_ge": "ი/მ"},
    {"id": "jsc",     "label_ru": "АО",               "label_ge": "სს"},
    {"id": "private", "label_ru": "Частное лицо",     "label_ge": "ფიზიკური პირი"},
]

COUNTRIES = [
    {"iso": "GE", "label_ru": "Грузия",       "label_ge": "საქართველო",  "flag": "🇬🇪"},
    {"iso": "RU", "label_ru": "Россия",       "label_ge": "რუსეთი",      "flag": "🇷🇺"},
    {"iso": "AM", "label_ru": "Армения",      "label_ge": "სომხეთი",     "flag": "🇦🇲"},
    {"iso": "AZ", "label_ru": "Азербайджан", "label_ge": "აზერბაიჯანი", "flag": "🇦🇿"},
    {"iso": "TR", "label_ru": "Турция",       "label_ge": "თურქეთი",     "flag": "🇹🇷"},
    {"iso": "UA", "label_ru": "Украина",      "label_ge": "უკრაინა",     "flag": "🇺🇦"},
    {"iso": "KZ", "label_ru": "Казахстан",   "label_ge": "ყაზახეთი",    "flag": "🇰🇿"},
    {"iso": "BY", "label_ru": "Беларусь",    "label_ge": "ბელარუსი",    "flag": "🇧🇾"},
    {"iso": "IR", "label_ru": "Иран",         "label_ge": "ირანი",       "flag": "🇮🇷"},
    {"iso": "DE", "label_ru": "Германия",    "label_ge": "გერმანია",     "flag": "🇩🇪"},
    {"iso": "PL", "label_ru": "Польша",       "label_ge": "პოლონეთი",    "flag": "🇵🇱"},
    {"iso": "CN", "label_ru": "Китай",        "label_ge": "ჩინეთი",      "flag": "🇨🇳"},
    {"iso": "US", "label_ru": "США",          "label_ge": "აშშ",         "flag": "🇺🇸"},
]

# Маппинг строковых org_type → стандартный id (для миграции старых записей)
ORG_TYPE_NORMALIZE_MAP = {
    "ооо": "llc", "LLC": "llc", "llc": "llc", "შპს": "llc",
    "ип": "ie", "IE": "ie", "ie": "ie", "ი/მ": "ie", "ИП": "ie",
    "ао": "jsc", "JSC": "jsc", "jsc": "jsc", "სს": "jsc", "АО": "jsc",
    "частное": "private", "private": "private", "физлицо": "private",
    "частное лицо": "private", "ფიზიკური პირი": "private",
}


def normalize_org_type(raw: str) -> str:
    """Нормализует строковый org_type к одному из стандартных id."""
    if not raw:
        return "private"
    clean = raw.strip().lower()
    return ORG_TYPE_NORMALIZE_MAP.get(clean, ORG_TYPE_NORMALIZE_MAP.get(raw, "private"))


def normalize_payment_type(raw: str) -> str:
    """Нормализует строковый payment_type к стандартному id."""
    if not raw:
        return "cash"
    mapping = {
        "нал": "cash", "наличные": "cash", "cash": "cash", "ნაღდი": "cash",
        "безнал 3": "bank_3d", "безнал 3 дня": "bank_3d", "bank_3d": "bank_3d",
        "безнал 7": "bank_7d", "безнал 7 дней": "bank_7d", "bank_7d": "bank_7d",
        "безнал": "bank_3d",  # если просто "безнал" — по умолчанию 3 дня
        "50% предоплата": "prepay_50", "предоплата": "prepay_50", "prepay_50": "prepay_50",
        "100% предоплата": "prepay_100", "prepay_100": "prepay_100",
    }
    return mapping.get(raw.strip().lower(), "cash")
