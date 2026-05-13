# Schema Drift Audit — emergency_migrations vs Alembic

**Date:** 2026-05-13  
**Auditor:** Builder  
**Basis:** `app/main.py` `_emergency_migrations` list vs `alembic/versions/001–015`

---

## ADD COLUMN (17 операций)

| Таблица | Колонка | Тип | Emergency | Alembic | Статус |
|---------|---------|-----|-----------|---------|--------|
| loads | is_demo | BOOLEAN | ✅ строка ~28 | ✅ 005_track11_demo_mode | in sync |
| users | is_demo | BOOLEAN | ✅ строка ~29 | ✅ 005_track11_demo_mode | in sync |
| users | password_changed_at | TIMESTAMP TZ | ✅ строка ~30 | ✅ 006_password_changed_at | in sync |
| users | completed_deals_count | INTEGER | ✅ строка ~31 | ✅ 007_ux_fixes | in sync |
| users | ratings_received_count | INTEGER | ✅ строка ~32 | ✅ 007_ux_fixes | in sync |
| responses | price_gel | FLOAT | ✅ строка ~33 | ✅ 001_adr006_currency_fields | in sync |
| responses | exchange_rate_at_creation | FLOAT | ✅ строка ~34 | ✅ 001_adr006_currency_fields | in sync |
| loads | exchange_rate_at_creation | FLOAT | ✅ строка ~35 | ✅ 001_adr006_currency_fields | in sync |
| deals | exchange_rate_snapshot | FLOAT | ✅ строка ~36 | ✅ 001_adr006_currency_fields | in sync |
| deals | final_price_gel | FLOAT | ✅ строка ~37 | ✅ 001_adr006_currency_fields | in sync |
| deals | final_price_usd | FLOAT | ✅ строка ~38 | ✅ 001_adr006_currency_fields | in sync |
| loads | from_city_id | INTEGER | ✅ строка ~39 | ✅ 002_adr007_cities_table | in sync |
| loads | to_city_id | INTEGER | ✅ строка ~40 | ✅ 002_adr007_cities_table | in sync |
| users | responses_this_month | INTEGER | ✅ строка ~41 | ⚠️ НЕ НАЙДЕНО | **DRIFT** |
| users | responses_month_reset | TIMESTAMP TZ | ✅ строка ~42 | ⚠️ НЕ НАЙДЕНО | **DRIFT** |
| users | is_deleted | BOOLEAN | ✅ строка ~43 | ✅ 004_adr010_gdpr_soft_delete | in sync |
| users | deleted_at | TIMESTAMP TZ | ✅ строка ~44 | ✅ 004_adr010_gdpr_soft_delete | in sync |
| users | is_verified | BOOLEAN | ✅ строка ~45 | ⚠️ НЕ НАЙДЕНО | **DRIFT** |
| deals | transport_offer_id | INTEGER | ✅ строка ~138 | ✅ 009_adr016_transport_bilateral | in sync |
| deals | transport_request_id | INTEGER | ✅ строка ~139 | ✅ 009_adr016_transport_bilateral | in sync |

> Примечание: фактически в emergency_migrations 19 ADD COLUMN операций (считая deals.transport_offer_id и deals.transport_request_id).

---

## ALTER TYPE (4 операции)

| Тип | Значение | Emergency | Alembic | Статус |
|-----|----------|-----------|---------|--------|
| userplan | pro_plus | ✅ | ✅ 011_enum_additions | in sync |
| loadstatus | paused | ✅ | ✅ 011_enum_additions | in sync |
| loadstatus | completed | ✅ | ✅ 011_enum_additions | in sync |
| responsestatus | withdrawn | ✅ | ✅ 011_enum_additions | in sync |

---

## CREATE TABLE (7 операций)

| Таблица | Emergency | Alembic | Статус |
|---------|-----------|---------|--------|
| status_changes | ✅ | ✅ 003_track8_state_machine | in sync* |
| cities | ✅ | ✅ 002_adr007_cities_table | in sync |
| reset_codes | ✅ | ⚠️ НЕ НАЙДЕНО | **DRIFT** |
| route_subscriptions | ✅ | ✅ 008_route_subscriptions | in sync |
| transport_offers | ✅ | ✅ 009_adr016_transport_bilateral | in sync |
| transport_requests | ✅ | ✅ 009_adr016_transport_bilateral | in sync |
| transport_subscriptions | ✅ | ✅ 009_adr016_transport_bilateral | in sync |

> *status_changes: создана в 003 с VARCHAR(20), расширена до VARCHAR(50) в 015.  
> В emergency_migrations CREATE TABLE уже с VARCHAR(50), 003 — с VARCHAR(20). Minor inconsistency, не drift.

---

## CREATE INDEX (8 операций из emergency)

| Индекс | Таблица | Emergency | Alembic | Статус |
|--------|---------|-----------|---------|--------|
| ix_route_subscriptions_user_id | route_subscriptions | ✅ | ✅ 008_route_subscriptions | in sync |
| ix_route_subscriptions_is_active | route_subscriptions | ✅ | ✅ 008_route_subscriptions | in sync |
| ix_route_sub_route | route_subscriptions | ✅ | ✅ 008_route_subscriptions | in sync |
| ix_transport_offers_user_id | transport_offers | ✅ | ✅ 009_adr016_transport_bilateral | in sync |
| ix_transport_offers_status | transport_offers | ✅ | ✅ 009_adr016_transport_bilateral | in sync |
| ix_transport_requests_offer_id | transport_requests | ✅ | ✅ 009_adr016_transport_bilateral | in sync |
| ix_transport_requests_user_id | transport_requests | ✅ | ✅ 009_adr016_transport_bilateral | in sync |
| ix_transport_requests_status | transport_requests | ✅ | ✅ 009_adr016_transport_bilateral | in sync |
| ix_transport_sub_user | transport_subscriptions | ✅ | ✅ 009_adr016_transport_bilateral | in sync |
| ix_transport_sub_active | transport_subscriptions | ✅ | ✅ 009_adr016_transport_bilateral | in sync |
| ix_transport_sub_route | transport_subscriptions | ✅ | ✅ 009_adr016_transport_bilateral | in sync |

> Примечание: фактически 11 CREATE INDEX в emergency, не 8.

---

## ALTER COLUMN (1 операция)

| Таблица | Колонка | Изменение | Emergency | Alembic | Статус |
|---------|---------|-----------|-----------|---------|--------|
| status_changes | entity_type | VARCHAR(20)→VARCHAR(50) | ✅ PR #12 | ✅ 015_expand_status_changes_entity_type | in sync |

---

## ИТОГ

| Категория | Всего | In Sync | DRIFT |
|-----------|-------|---------|-------|
| ADD COLUMN | 19 | 16 | **3** |
| ALTER TYPE | 4 | 4 | 0 |
| CREATE TABLE | 7 | 6 | **1** |
| CREATE INDEX | 11 | 11 | 0 |
| ALTER COLUMN | 1 | 1 | 0 |
| **ИТОГО** | **42** | **38** | **4** |

---

## Drift-записи (требуют Alembic миграции)

### 1. `users.responses_this_month` (INTEGER)
Есть в emergency, **нет в Alembic**.  
Используется для rate limiting откликов. Критично для чистой установки.

### 2. `users.responses_month_reset` (TIMESTAMP WITH TIME ZONE)
Есть в emergency, **нет в Alembic**.  
Связана с `responses_this_month`. Нужна вместе.

### 3. `users.is_verified` (BOOLEAN)
Есть в emergency, **нет в Alembic**.  
Поле верификации аккаунта. Без него `alembic upgrade head` на чистой БД даст неполную схему users.

### 4. `reset_codes` (TABLE)
Есть в emergency, **нет в Alembic**.  
Таблица для сброса пароля. Без неё `POST /api/auth/forgot-password` падает на чистой БД.

---

## Рекомендации

Создать миграцию **016** покрывающую все 4 drift-записи:
- `ALTER TABLE users ADD COLUMN IF NOT EXISTS responses_this_month INTEGER DEFAULT 0`
- `ALTER TABLE users ADD COLUMN IF NOT EXISTS responses_month_reset TIMESTAMP WITH TIME ZONE`
- `ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE`
- `CREATE TABLE IF NOT EXISTS reset_codes (...)`

**Не делать без явного ОК.**

---

## Задача 4 — PR #8 vs emergency (индексы 014)

PR #8 содержит миграцию `014_add_missing_indexes.py` с 8 индексами:

| Индекс из 014 | Есть в emergency? | Вывод |
|---------------|-------------------|-------|
| ix_loads_status_demo | ❌ | будет создан миграцией 014 |
| ix_loads_city_ids | ❌ | будет создан миграцией 014 |
| ix_responses_load_id | ❌ | будет создан миграцией 014 |
| ix_responses_load_status | ❌ | будет создан миграцией 014 |
| ix_deals_shipper_id | ❌ | будет создан миграцией 014 |
| ix_deals_carrier_id | ❌ | будет создан миграцией 014 |
| ix_deals_load_id | ❌ | будет создан миграцией 014 |
| ix_transport_offers_demo | ❌ | будет создан миграцией 014 |

**Дубликатов с emergency_migrations: 0.**  
Миграция 014 из PR #8 безопасна — создаст новые индексы через `CREATE INDEX IF NOT EXISTS`, не конфликтует с emergency.
