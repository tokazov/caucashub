"""
plan_check.py — лимиты тарифных планов CaucasHub.

Тарифы:
  free:     5 активных грузов, 10 откликов/мес, 1 подписка
  standard: 20 активных грузов, 50 откликов/мес, 10 подписок
  pro:      50 активных грузов, 100 откликов/мес, 20 подписок
  pro_plus: безлимит (0 = ∞)
  business: безлимит (0 = ∞)
"""
from typing import Tuple

PLAN_LIMITS = {
    "free":     {"loads": 5,  "responses": 10,  "subscriptions": 1},
    "standard": {"loads": 20, "responses": 50,  "subscriptions": 10},
    "pro":      {"loads": 50, "responses": 100, "subscriptions": 20},
    "pro_plus": {"loads": 0,  "responses": 0,   "subscriptions": 0},
    "business": {"loads": 0,  "responses": 0,   "subscriptions": 0},
}

UPGRADE_URL = "/pricing"


def _plan_key(user) -> str:
    plan = user.plan
    if hasattr(plan, "value"):
        plan = plan.value
    return str(plan) if plan else "free"


def get_limits(user) -> dict:
    return PLAN_LIMITS.get(_plan_key(user), PLAN_LIMITS["free"])


def check_loads_limit(user, active_loads_count: int) -> Tuple[bool, dict | None]:
    """Проверяет лимит активных грузов. Возвращает (ok, error_body)."""
    lim = get_limits(user)["loads"]
    if lim == 0:
        return True, None
    if active_loads_count >= lim:
        return False, {
            "error": "limit_exceeded",
            "resource": "loads",
            "plan": _plan_key(user),
            "limit": lim,
            "current": active_loads_count,
            "upgrade_url": UPGRADE_URL,
        }
    return True, None


def check_responses_limit(user) -> Tuple[bool, dict | None]:
    """Проверяет лимит откликов в месяц."""
    lim = get_limits(user)["responses"]
    if lim == 0:
        return True, None
    used = user.responses_this_month or 0
    if used >= lim:
        return False, {
            "error": "limit_exceeded",
            "resource": "responses",
            "plan": _plan_key(user),
            "limit": lim,
            "current": used,
            "upgrade_url": UPGRADE_URL,
        }
    return True, None


def check_subscriptions_limit(user, current_count: int) -> Tuple[bool, dict | None]:
    """Проверяет лимит подписок."""
    lim = get_limits(user)["subscriptions"]
    if lim == 0:
        return True, None
    if current_count >= lim:
        return False, {
            "error": "limit_exceeded",
            "resource": "subscriptions",
            "plan": _plan_key(user),
            "limit": lim,
            "current": current_count,
            "upgrade_url": UPGRADE_URL,
        }
    return True, None


# --- Обратная совместимость ---

def check_can_respond(user) -> Tuple[bool, str]:
    ok, err = check_responses_limit(user)
    return ok, "ok" if ok else str(err)


def is_paid_plan(user) -> bool:
    return _plan_key(user) in ("pro", "pro_plus", "business", "standard")


def get_responses_limit(user) -> str:
    lim = get_limits(user)["responses"]
    return "∞" if lim == 0 else str(lim)
