"""
Нормализация данных пользователя (Трек 9).
Вызывается при регистрации и обновлении профиля.
XSS-санитизация (Категория 4, Part A).
"""
import re
from typing import Optional

# Паттерны опасных HTML-конструкций
_DANGEROUS_TAGS = re.compile(
    r'<\s*(script|iframe|object|embed|form|input|button|link|meta|base|frame|frameset|applet|svg|math)[^>]*>',
    re.IGNORECASE,
)
_DANGEROUS_ATTRS = re.compile(
    r'\s(on\w+|javascript:|data:text/html)\s*=',
    re.IGNORECASE,
)
_SCRIPT_CONTENT = re.compile(r'<script[\s\S]*?</script>', re.IGNORECASE)


def sanitize_text(value: str, max_length: int = None) -> str:
    """
    Санитизирует пользовательский текст:
    - Удаляет опасные HTML-теги и обработчики событий
    - НЕ экранирует — хранит исходный текст (экранирование на фронте через esc())
    - Обрезает до max_length если задан
    """
    if not value:
        return value
    s = str(value)
    # Удаляем <script>...</script> блоки
    s = _SCRIPT_CONTENT.sub('', s)
    # Удаляем опасные теги
    s = _DANGEROUS_TAGS.sub('', s)
    # Удаляем on* атрибуты и javascript: ссылки
    s = _DANGEROUS_ATTRS.sub(' ', s)
    if max_length:
        s = s[:max_length]
    return s.strip()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_phone(phone: str) -> Optional[str]:
    """
    Приводит телефон к формату E.164.
    Поддерживает грузинские (+995), российские (+7) и другие номера.
    Если нормализовать невозможно — возвращает очищенную строку.
    """
    if not phone:
        return None
    # Оставляем только цифры и +
    cleaned = re.sub(r'[^\d+]', '', phone.strip())

    # Если начинается с 995 без + — добавляем +
    if cleaned.startswith('995') and not cleaned.startswith('+'):
        cleaned = '+' + cleaned

    # Если начинается с 8 (Россия) — меняем на +7
    if cleaned.startswith('8') and len(cleaned) == 11:
        cleaned = '+7' + cleaned[1:]

    # Если начинается с 7 без + — добавляем +
    if cleaned.startswith('7') and len(cleaned) == 11:
        cleaned = '+' + cleaned

    # Грузинский формат 05X: 0551234567 → +995551234567 (задача 7)
    if cleaned.startswith('0') and len(cleaned) == 10:
        cleaned = '+995' + cleaned[1:]

    # Минимальная длина E.164: +[code][number] ≥ 10 символов
    if len(cleaned) >= 10:
        return cleaned
    return phone.strip()  # fallback без изменений


def normalize_company_name(name: str) -> Optional[str]:
    """Убирает пробелы по краям и нормализует двойные пробелы."""
    if not name:
        return None
    return re.sub(r'\s{2,}', ' ', name.strip())


def normalize_tax_id(tax_id: str, country: str = "GE") -> Optional[str]:
    """
    Нормализует ИНН/tax ID.
    Грузия: 9 цифр для физлиц и юрлиц.
    """
    if not tax_id:
        return None
    digits = re.sub(r'\D', '', tax_id.strip())
    if country == "GE" and len(digits) != 9:
        return None  # невалидный
    return digits


def normalize_user_fields(
    email: Optional[str] = None,
    phone: Optional[str] = None,
    company_name: Optional[str] = None,
    inn: Optional[str] = None,
) -> dict:
    """Нормализует все поля пользователя и возвращает словарь изменений."""
    result = {}
    if email is not None:
        result["email"] = normalize_email(email)
    if phone is not None:
        result["phone"] = normalize_phone(phone)
    if company_name is not None:
        result["company_name"] = normalize_company_name(company_name)
    if inn is not None:
        result["inn"] = normalize_tax_id(inn)
    return result
