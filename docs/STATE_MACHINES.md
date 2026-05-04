# STATE_MACHINES.md — Жизненные циклы сущностей CaucasHub

> Единственный источник истины по допустимым переходам состояний.
> Код в `app/services/state_machine.py` — зеркало этого документа.
> При изменении здесь — обязательно обновить код, и наоборот.

---

## 1. Load.status — Жизненный цикл груза

```
              [active] ──────────────────────────────────┐
                 │                                        │
       (перевозчик принят,                        (shipper: отменил)
        система)                                         ▼
                 ▼                                   [canceled] ⛔
              [taken]
                 │
    ┌────────────┴────────────┐
    │                         │
(deal.canceled,          (shipper:
 система)               отменил)
    │                         │
    ▼                         ▼
 [active]               [canceled] ⛔
```

### Переходы

| От | К | Кто | Условие |
|----|---|-----|---------|
| `active` | `taken` | Система (при accept отклика) | Груз не отменён |
| `active` | `canceled` | Грузовладелец | Нет активной сделки |
| `taken` | `completed` | Система (при rate_deal) | Случай B — taken≡completed поведенчески |
| `taken` | `canceled` | Грузовладелец | Нет активной сделки |
| ~~`taken` → `active`~~ | — | — | Удалено: переразмещение не реализовано (случай B) |
| `expired` | — | — | Терминальный |
| `canceled` | — | — | Терминальный |

> ⚠️ `expired` пока не реализован автоматически — задача для будущей версии (cron-job)

---

## 2. Response.status — Жизненный цикл отклика

```
            [pending]
           /    |    \
          /     |     \
    (shipper) (shipper) (carrier:
     accept)  reject)   withdraw)
        ▼       ▼         ▼
   [accepted] [rejected] [withdrawn]
      ⛔         ⛔          ⛔
```

### Переходы

| От | К | Кто | Условие |
|----|---|-----|---------|
| `pending` | `accepted` | Грузовладелец | Это его груз; груз в статусе `active`/`taken` |
| `pending` | `rejected` | Грузовладелец | Это его груз |
| `pending` | `withdrawn` | Перевозчик | Это его отклик |
| `accepted` | — | — | Терминальный |
| `rejected` | — | — | Терминальный |
| `withdrawn` | — | — | Терминальный |

> При `accepted` → все остальные `pending`-отклики на тот же груз → `rejected` (автоматически)

---

## 3. Deal.status — Жизненный цикл сделки

```
         [confirmed]
              │
       (carrier: загрузка)
              ▼
          [loading]
              │
       (carrier: отправил)
              ▼
         [in_transit]
              │
      (обе стороны подтверждают)
              ▼
          [delivered]
              │
    (обе стороны подтвердили)
              ▼
          [completed]
              │
       (оценка выставлена)
              ▼
            [rated] ⛔


На любом этапе (кроме completed/rated):
              │
        (отмена)
              ▼
          [canceled] ⛔

Спор:
    [in_transit] / [delivered] → [disputed]
    [disputed] → [completed] / [canceled]  (только admin)
```

### Переходы

| От | К | Кто | Условие |
|----|---|-----|---------|
| `confirmed` | `loading` | Перевозчик | |
| `confirmed` | `canceled` | Любая сторона | |
| `loading` | `in_transit` | Перевозчик | |
| `loading` | `canceled` | Любая сторона | |
| `in_transit` | `delivered` | Система | Обе стороны нажали «Подтвердить доставку» |
| `in_transit` | `canceled` | Любая сторона | |
| `in_transit` | `disputed` | Любая сторона | |
| `delivered` | `completed` | Система | Обе стороны подтвердили |
| `delivered` | `canceled` | Любая сторона | |
| `completed` | `rated` | Система | После выставления оценки |
| `disputed` | `completed` | Администратор | Ручное разрешение спора |
| `disputed` | `canceled` | Администратор | |
| `canceled` | — | — | Терминальный |
| `rated` | — | — | Терминальный |

> При `canceled`: если груз в статусе `taken` — груз возвращается в `active` (нужен backfill)

---

## Audit Log

Все переходы пишутся в таблицу `status_changes`:

| Поле | Тип | Описание |
|------|-----|----------|
| `entity_type` | str | `load` / `response` / `deal` |
| `entity_id` | int | ID объекта |
| `from_status` | str | Статус до |
| `to_status` | str | Статус после |
| `user_id` | int | Кто инициировал (null = система) |
| `changed_at` | datetime UTC | Когда |
| `reason` | str | Опциональный комментарий |

---

## Глоссарий

- **Грузовладелец (shipper)** — создаёт груз, принимает/отклоняет отклики
- **Перевозчик (carrier)** — откликается, управляет статусами доставки
- **Система** — автоматический переход без участия пользователя
- **Администратор** — только через защищённый admin-эндпоинт
- **Терминальный** ⛔ — из этого статуса выйти нельзя

---

## 6. TransportOffer.status — Жизненный цикл транспортного предложения (ADR-016)

**Симметрично Load.status** — цикл сделки идёт через Deal.status, не через источник.

```
              [active] ──────────────────────────────────┐
                 │                                        │
    (перевозчик принимает                        (перевозчик: снял /
     TransportRequest,                            DELETE /api/transport/{id})
     система)                                            ▼
                 ▼                                   [canceled] ⛔
              [taken]
                 │
    ┌────────────┴────────────┐
    │                         │
(deal.canceled,          (rate_deal:
 система)               обе стороны оценили)
    │                         │
    ▼                         ▼
 [active]               [completed] ✅
```

### Переходы TransportOffer

| От | К | Кто | Условие |
|----|---|-----|---------|
| `active` | `taken` | Система (при accept TransportRequest) | Предложение не отменено |
| `active` | `canceled` | Перевозчик (DELETE) | Нет активной сделки |
| `taken` | `active` | Система | При отмене сделки (deal.canceled) |
| `taken` | `completed` | Система (при rate_deal) | Deal.status = rated |
| `canceled` | — | — | Терминальный |
| `completed` | — | — | Терминальный |

### Сравнение с Load.status

| | Load | TransportOffer |
|--|------|----------------|
| Стартовый статус | `active` | `active` |
| После accept | `taken` | `taken` |
| После rate | `taken` (не меняется) | `completed` |
| Терминал отмены | `canceled` | `canceled` |

> **Различие:** Load остаётся `taken` навсегда после сделки (для исторических данных).
> TransportOffer переходит в `completed` при rate_deal — логично, так как предложение
> транспорта однократное, а груз может быть переразмещён.
