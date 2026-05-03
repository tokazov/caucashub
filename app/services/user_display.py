"""
Хелперы для отображения имени пользователя (ADR-010 GDPR).

Все места в коде, где показывается имя пользователя, ОБЯЗАНЫ использовать
display_name() вместо прямого обращения к user.company_name.

Это гарантирует что «Удалённый пользователь #N» отображается корректно.
"""
from typing import Optional


def display_name(user, fallback: str = "CaucasHub") -> str:
    """
    Возвращает отображаемое имя пользователя.

    Для удалённых (is_deleted=True) — возвращает анонимное имя из БД.
    Это работает потому что при удалении мы СНАЧАЛА пишем
    company_name = 'Удалённый пользователь #{id}', потом is_deleted=True.
    """
    if user is None:
        return fallback
    if getattr(user, 'is_deleted', False):
        # company_name уже анонимизировано при удалении
        return user.company_name or f"Удалённый пользователь #{user.id}"
    return user.company_name or (
        user.email.split('@')[0] if user.email else fallback
    )


def display_phone(user) -> Optional[str]:
    """Телефон удалённого пользователя не показываем."""
    if user is None or getattr(user, 'is_deleted', False):
        return None
    return user.phone


def display_email(user) -> Optional[str]:
    """Email удалённого пользователя не показываем."""
    if user is None or getattr(user, 'is_deleted', False):
        return None
    return user.email
