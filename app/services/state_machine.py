"""
Машина состояний CaucasHub (ADR — Трек 8).

Валидные переходы зафиксированы здесь как единственный источник истины.
Все роутеры, меняющие статус, ОБЯЗАНЫ вызывать validate_transition().

Правило: если переход не указан явно — он запрещён.
"""
from fastapi import HTTPException

# ── Load.status ───────────────────────────────────────────────────────────────
# Кто инициирует указан в комментарии
LOAD_TRANSITIONS: dict[str, list[str]] = {
    "active":   ["taken", "canceled"],    # taken: system (accept); canceled: shipper
    "taken":    ["active", "canceled"],   # active: system (deal canceled); canceled: shipper (+ no active deal check)
    "expired":  [],                        # терминальный
    "canceled": [],                        # терминальный
}

# ── Response.status ───────────────────────────────────────────────────────────
RESPONSE_TRANSITIONS: dict[str, list[str]] = {
    "pending":   ["accepted", "rejected", "withdrawn"],
    # accepted: shipper only; rejected: shipper only; withdrawn: carrier only
    "accepted":  [],    # терминальный
    "rejected":  [],    # терминальный
    "withdrawn": [],    # терминальный
}

# ── Deal.status ───────────────────────────────────────────────────────────────
DEAL_TRANSITIONS: dict[str, list[str]] = {
    "confirmed":  ["loading", "canceled"],     # loading: carrier; canceled: both
    "loading":    ["in_transit", "canceled"],  # in_transit: carrier
    "in_transit": ["delivered", "canceled"],   # delivered: both (двойное подтверждение)
    "delivered":  ["completed", "canceled"],   # completed: system (оба подтвердили)
    "completed":  ["rated"],                   # rated: system (после оценки)
    "rated":      [],                           # терминальный
    "disputed":   ["completed", "canceled"],   # admin only
    "canceled":   [],                           # терминальный
}

_TRANSITION_MAP = {
    "load":     LOAD_TRANSITIONS,
    "response": RESPONSE_TRANSITIONS,
    "deal":     DEAL_TRANSITIONS,
}


def validate_transition(
    entity_type: str,
    current_status: str,
    new_status: str,
    raise_on_invalid: bool = True,
) -> bool:
    """
    Проверяет что переход current → new допустим.

    Args:
        entity_type: "load" | "response" | "deal"
        current_status: текущий статус (строка)
        new_status: желаемый новый статус
        raise_on_invalid: если True — кидает HTTPException 400, иначе False

    Returns:
        True если переход валидный

    Raises:
        HTTPException 400 если переход недопустим и raise_on_invalid=True
    """
    transitions = _TRANSITION_MAP.get(entity_type)
    if transitions is None:
        if raise_on_invalid:
            raise HTTPException(400, f"Unknown entity type: {entity_type}")
        return False

    allowed = transitions.get(current_status, [])
    if new_status in allowed:
        return True

    if raise_on_invalid:
        if not allowed:
            raise HTTPException(
                400,
                f"Status '{current_status}' is terminal — no further transitions allowed"
            )
        raise HTTPException(
            400,
            f"Invalid transition for {entity_type}: '{current_status}' → '{new_status}'. "
            f"Allowed: {allowed}"
        )
    return False


def get_allowed_transitions(entity_type: str, current_status: str) -> list[str]:
    """Возвращает список допустимых переходов для текущего статуса."""
    transitions = _TRANSITION_MAP.get(entity_type, {})
    return transitions.get(current_status, [])
