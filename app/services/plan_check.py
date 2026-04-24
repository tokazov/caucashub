"""
plan_check.py — утилиты проверки тарифного плана пользователя.
"""
from datetime import datetime, timezone
from typing import Tuple


def _start_of_month(dt: datetime) -> datetime:
    """Начало текущего месяца (UTC)."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def check_can_respond(user) -> Tuple[bool, str]:
    """
    Проверяет, может ли пользователь откликнуться на груз.

    Возвращает (can: bool, reason: str):
      - (False, "plan_required")  — план free
      - (False, "limit_reached")  — standard, лимит 50 исчерпан
      - (True,  "ok")             — standard (есть лимит), pro, pro_plus
    """
    plan = user.plan.value if hasattr(user.plan, "value") else str(user.plan)

    if plan == "free":
        return False, "plan_required"

    if plan == "standard":
        now = datetime.now(timezone.utc)
        month_start = _start_of_month(now)

        # Сброс счётчика если он из прошлого месяца
        reset_ts = user.responses_month_reset
        if reset_ts is not None:
            # Нормализуем: если naive datetime — считаем UTC
            if reset_ts.tzinfo is None:
                reset_ts = reset_ts.replace(tzinfo=timezone.utc)
            if reset_ts < month_start:
                user.responses_this_month = 0
                user.responses_month_reset = now

        count = user.responses_this_month or 0
        if count >= 50:
            return False, "limit_reached"
        return True, "ok"

    # pro / pro_plus — безлимит
    if plan in ("pro", "pro_plus"):
        return True, "ok"

    # Неизвестный план — запрещаем
    return False, "plan_required"
