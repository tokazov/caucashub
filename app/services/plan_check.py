"""
plan_check.py — утилиты проверки тарифного плана пользователя.

PRICING_ENABLED (env var) — глобальный переключатель тарификации.
Если False (по умолчанию) — все функции доступны бесплатно.
Включается командой: установить PRICING_ENABLED=true в Railway ENV.
"""
import os
from datetime import datetime, timezone
from typing import Tuple

# ── Глобальный флаг тарификации ──────────────────────────────────────
# False = все пользователи работают без ограничений (период роста)
# True  = ограничения по плану включены
PRICING_ENABLED = os.getenv("PRICING_ENABLED", "false").lower() == "true"


def _start_of_month(dt: datetime) -> datetime:
    """Начало текущего месяца (UTC)."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def check_can_respond(user) -> Tuple[bool, str]:
    """
    Проверяет, может ли пользователь откликнуться на груз.

    Если PRICING_ENABLED=false — всегда возвращает (True, "ok").
    Если PRICING_ENABLED=true:
      - (False, "plan_required")  — план free
      - (False, "limit_reached")  — standard, лимит 50 исчерпан
      - (True,  "ok")             — standard (есть лимит), pro, pro_plus
    """
    # Тарификация выключена — всё бесплатно
    if not PRICING_ENABLED:
        return True, "ok"

    plan = user.plan.value if hasattr(user.plan, "value") else str(user.plan)

    if plan == "free":
        return False, "plan_required"

    if plan == "standard":
        now = datetime.now(timezone.utc)
        month_start = _start_of_month(now)

        # Сброс счётчика если он из прошлого месяца
        reset_ts = user.responses_month_reset
        if reset_ts is not None:
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

    return False, "plan_required"


def is_paid_plan(user) -> bool:
    """Проверяет платный ли план пользователя.
    Если PRICING_ENABLED=false — все считаются платными (полный доступ).
    """
    if not PRICING_ENABLED:
        return True
    plan = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
    return plan in ("standard", "pro", "pro_plus")


def get_responses_limit(user) -> int | str:
    """Возвращает лимит откликов пользователя.
    Если PRICING_ENABLED=false — безлимит у всех.
    """
    if not PRICING_ENABLED:
        return "∞"
    plan = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
    limits = {"free": 0, "standard": 50, "pro": "∞", "pro_plus": "∞"}
    return limits.get(plan, 0)
