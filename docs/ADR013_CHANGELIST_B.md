# ADR-013 Changelist — Вариант B

> **Суть:** Удалить флаг PRICING_ENABLED. Контакты грузовладельца показываются ТОЛЬКО
> в рамках сделки (после accepted-отклика). Для всех пользователей, без исключений.
> Архитектурно чисто, соответствует ADR-001.

> **Статус:** Changelist готов. Ждём прямого «B» от Тимура перед реализацией.

---

## Затронутые файлы

### 1. `app/services/plan_check.py` — полное упрощение

**До:**
```python
PRICING_ENABLED = os.getenv("PRICING_ENABLED", "false").lower() == "true"

def check_can_respond(user, db): 
    if not PRICING_ENABLED: return (True, "ok")
    # ... проверки тарифа ...

def is_paid_plan(user) -> bool:
    if not PRICING_ENABLED: return True   # все считаются платными
    return user.plan in (UserPlan.standard, UserPlan.pro)
    
def get_response_limit(user) -> int:
    if not PRICING_ENABLED: return 9999   # безлимит
    ...
```

**После:**
```python
# PRICING_ENABLED удалён — тарификация определяется по плану пользователя
# Пока нет Pro-тарифа — check_can_respond всегда разрешает

def check_can_respond(user, db):
    return (True, "ok")   # до реализации Pro-тарифа

def is_paid_plan(user) -> bool:
    return True  # до реализации Pro-тарифа: все имеют полный доступ
```

**Объём изменений:** ~40 строк удалить, ~10 оставить.

---

### 2. `app/routers/loads.py` — логика показа контактов

**До (строки 334–345):**
```python
from app.services.plan_check import PRICING_ENABLED, is_paid_plan
show_contacts = False
if viewer_id:
    if not PRICING_ENABLED:
        show_contacts = True  # Тарификация выключена — контакты всем
    else:
        viewer = ...
        if viewer: show_contacts = is_paid_plan(viewer)
```

**После:**
```python
# Контакты только в сделке (ADR-001, ADR-013 Вариант B)
# GET /api/loads/{id} никогда не показывает контакты напрямую
show_contacts = False
# Контакты доступны только через GET /api/deals/{id} когда viewer = участник сделки
```

**Объём изменений:** 10 строк → 3 строки.

---

### 3. `app/routers/deals.py` — добавить контакты в ответ сделки

**Текущее состояние:** `deal_to_dict` возвращает shipper/carrier без phone/email.

**Нужно добавить:** В `GET /api/deals/my` и `GET /api/deals/{id}` — показывать контакты
участника сделки (phone, email) только если запрашивающий = участник сделки.

```python
# В deal_to_dict или в get_my_deals enrichment:
base["shipper"]["phone"] = sh.phone if sh and viewer_is_participant else None
base["carrier"]["phone"] = ca.phone if ca and viewer_is_participant else None
```

**Объём изменений:** ~20 строк в deals.py.

---

### 4. `app/routers/responses.py` — удалить импорт plan_check

**До:**
```python
from app.services.plan_check import check_can_respond
# ... в create_response:
can, reason = await check_can_respond(current_user, db)
if not can:
    raise HTTPException(402, reason)
current_user.responses_this_month += 1
```

**После (Вариант B):**
```python
# check_can_respond удалён — лимит откликов вернём с Pro-тарифом
# responses_this_month счётчик оставляем (пригодится для Pro)
```

**Объём изменений:** 5 строк удалить.

---

### 5. Railway ENV — удалить переменную

Удалить `PRICING_ENABLED` из Railway ENV (если она там есть — сейчас не задана, значит уже false по умолчанию).

---

### 6. `app/models/user.py` — поля оставить

`responses_this_month`, `responses_month_reset` — оставляем в модели. Понадобятся для Pro-тарифа.

---

### 7. Тесты

Удалить/обновить тесты которые проверяли `PRICING_ENABLED=true` поведение.
Добавить тест: `GET /api/loads/{id}` → `owner_phone=None` для авторизованного (не в сделке).
Добавить тест: `GET /api/deals/{id}` → `carrier.phone` виден участнику сделки.

---

## Оценка работ

| Файл | Действие | Время |
|------|---------|-------|
| plan_check.py | Упростить, удалить PRICING_ENABLED | 15 мин |
| loads.py | show_contacts=False всегда | 10 мин |
| deals.py | Добавить контакты для участников | 30 мин |
| responses.py | Убрать check_can_respond | 5 мин |
| Тесты | Обновить + добавить | 30 мин |
| **Итого** | | **~1.5 часа** |

---

## Риски

1. **Существующие пользователи** — сейчас контакты открыты всем авторизованным.
   После Варианта B — контакты исчезнут из карточки груза. Если кто-то привык
   открывать контакт без отклика — потеряет этот способ.
   
2. **Deals UI** — нужно убедиться что фронт показывает телефон/email в «Сделках»,
   иначе пользователи не смогут связаться с контрагентом вообще.

3. **Обратная совместимость** — `is_paid_plan()` используется в нескольких местах.
   После упрощения нужно проверить все вызовы.
