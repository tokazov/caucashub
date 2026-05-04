"""
plan_check.py — утилиты доступа к данным.

ADR-013 Вариант B (принято 2026-05-05):
PRICING_ENABLED удалён. Контакты участника сделки доступны только через Deal.
Функции оставлены как заглушки для обратной совместимости.
Pro-тарифные ограничения вернутся при реализации billing-модуля.
"""
from typing import Tuple


def check_can_respond(user) -> Tuple[bool, str]:
    """Всегда разрешает отклик. Pro-лимиты добавим с billing."""
    return True, "ok"


def is_paid_plan(user) -> bool:
    """Все пользователи считаются полноправными до введения Pro."""
    return True


def get_responses_limit(user) -> str:
    """Безлимит до введения Pro-тарифа."""
    return "∞"
