# ARCHITECTURE.md — Архитектура CaucasHub

> Последнее обновление: 03.05.2026

---

## Стек

| Слой | Технология |
|------|-----------|
| Бэкенд | Python 3.12, FastAPI, SQLAlchemy 2.0 async |
| БД | PostgreSQL (продакшн), SQLite (тесты) |
| Хостинг | Railway |
| Фронт | Vanilla JS + HTML (Cloudflare Pages) |
| Email | Resend API (резерв: Brevo) |
| AI | Gemini 2.5 Flash |
| Геокодер | Yandex Geocoder Advanced (ожидаем ключ, сейчас заглушка) |
| Курсы валют | NBG API (nbg.gov.ge), кеш 1 час |

---

## Модели данных

### User

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer PK | |
| `email` | String unique | Нормализуется к lowercase. NULL после удаления аккаунта |
| `phone` | String | E.164 формат (+995...). NULL после удаления |
| `hashed_password` | String | sha256_crypt. `<deleted>` после удаления |
| `company_name` | String | `Удалённый пользователь #{id}` после удаления |
| `full_name` | String | NULL после удаления |
| `role` | Enum | `carrier` / `shipper` / `both` |
| `plan` | Enum | `free` / `standard` / `pro` / `pro_plus` |
| `is_verified` | Boolean | Верифицирован администратором |
| `is_active` | Boolean | `False` при блокировке или удалении |
| `telegram_id` | String | NULL после удаления |
| `rating` | Integer | 0–50 → отображается 0.0–5.0 |
| `trips_count` | Integer | |
| `lang` | String | `ru` / `ge` / `en` |
| `inn` | String | Tax ID Грузии (9 цифр). **Сохраняется после удаления** (rs.ge, 6 лет) |
| `org_type` | String | Нормализованный id: `llc` / `ie` / `jsc` / `private` |
| `city` | String | Город работы |
| `responses_this_month` | Integer | Счётчик откликов (для лимитов плана) |
| `responses_month_reset` | DateTime | Дата сброса счётчика |
| `is_deleted` | Boolean | **Soft delete** (ADR-010). `True` = аккаунт удалён |
| `deleted_at` | DateTime UTC | Timestamp удаления (NULL если не удалён) |
| `created_at` | DateTime UTC | |

> ⚠️ При `is_deleted=True`: логин запрещён (401), любой активный токен инвалидируется при следующем запросе.

### Load (Груз)

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer PK | |
| `user_id` | FK → users | |
| `from_city` | String | Город отправления (свободный текст, нормализуется) |
| `from_city_id` | FK → cities | Nullable — нормализованный город |
| `to_city` | String | Город назначения |
| `to_city_id` | FK → cities | Nullable |
| `scope` | Enum | `local` / `intl` |
| `weight_kg` | Float | Вес в кг |
| `volume_m3` | Float | Объём м³ |
| `truck_type` | Enum | `tent`/`ref`/`bort`/`termos`/`gazel`/`container`/`auto`/`other` |
| `cargo_desc` | Text | Описание груза |
| `price_usd` | Float | Цена в USD |
| `price_gel` | Float | Цена в GEL |
| `exchange_rate_at_creation` | Float | Курс GEL/USD из NBG на момент создания |
| `payment_type` | String | Нормализованный id: `cash`/`bank_3d`/`bank_7d`/`prepay_50` |
| `load_date` | DateTime | Дата загрузки (≥ today при создании) |
| `is_urgent` | Boolean | |
| `is_boosted` | Boolean | Платное поднятие |
| `status` | Enum | `active`/`taken`/`expired`/`canceled` |
| `views` | Integer | |
| `created_at` | DateTime UTC | |

### Response (Отклик)

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer PK | |
| `load_id` | FK → loads | |
| `user_id` | FK → users | Перевозчик |
| `message` | Text | |
| `price_gel` | Float | Цена в GEL |
| `price_usd` | Float | Цена в USD |
| `exchange_rate_at_creation` | Float | Курс на момент отклика |
| `status` | Enum | `pending`/`accepted`/`rejected`/`withdrawn` |
| `created_at` | DateTime UTC | |

### Deal (Сделка)

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer PK | |
| `load_id` | FK → loads | |
| `shipper_id` | FK → users | |
| `carrier_id` | FK → users | |
| `response_id` | FK → responses (nullable) | |
| `status` | Enum | `confirmed`/`loading`/`in_transit`/`delivered`/`completed`/`rated`/`disputed`/`canceled` |
| `agreed_price` | Float | Согласованная цена |
| `currency` | String(3) | `GEL` / `USD` |
| `exchange_rate_snapshot` | Float | Курс зафиксированный при создании сделки |
| `final_price_gel` | Float | Итог в GEL |
| `final_price_usd` | Float | Итог в USD |
| `act_number` | String unique | CH-YYYY-NNNN |
| `shipper_confirmed` | Boolean | |
| `carrier_confirmed` | Boolean | |
| `loading_at` / `delivered_at` / `completed_at` | DateTime | |
| `notes` | Text | |

### City (Справочник городов)

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer PK | |
| `name_ru` | String | |
| `name_ge` | String | |
| `country_iso` | String(2) | GE / RU / TR и т.д. |
| `lat` / `lon` | Float | Координаты (нужны для Advanced Яндекс) |
| `is_popular` | Boolean | Показывать в дефолтном списке |
| `yandex_geo_id` | String | Сохраняется из ответа Яндекса (лицензионное требование) |

### StatusChange (Audit Log)

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer PK | |
| `entity_type` | String(20) | `load` / `response` / `deal` / `user` |
| `entity_id` | Integer | ID объекта |
| `from_status` | String | NULL при создании |
| `to_status` | String | |
| `user_id` | FK → users (nullable) | NULL = система |
| `changed_at` | DateTime UTC | |
| `reason` | Text | |

---

## API роутеры

| Префикс | Файл | Назначение |
|---------|------|-----------|
| `/api/auth` | `routers/auth.py` | Регистрация, логин, сброс пароля |
| `/api/users` | `routers/users.py` | Профиль, настройки, удаление (ADR-010) |
| `/api/loads` | `routers/loads.py` | CRUD грузов |
| `/api/trucks` | `routers/trucks.py` | CRUD машин |
| `/api/responses` | `routers/responses.py` | Отклики, accept, reject, withdraw |
| `/api/deals` | `routers/deals.py` | Сделки, статусы, PDF акт, экспорт |
| `/api/cities` | `routers/cities.py` | Автокомплит городов |
| `/api/dictionaries` | `routers/dictionaries.py` | Справочники truck-types/countries/etc |
| `/api/stats` | `routers/stats.py` | Счётчики шапки (кеш 5 мин) |
| `/api/ai` | `routers/ai.py` | AI-ассистент (Gemini) |
| `/api/tg` | `routers/tg_bot.py` | Telegram webhook |

---

## Сервисы

| Модуль | Назначение |
|--------|-----------|
| `services/state_machine.py` | Валидация переходов статусов |
| `services/audit_log.py` | Запись в status_changes |
| `services/exchange_rate.py` | Курс NBG (кеш 1 час) |
| `services/cities_seed.py` | Сидинг 45 городов |
| `services/yandex_geocoder.py` | Яндекс Geocoder (заглушка, ждём ключ) |
| `services/dictionaries.py` | Справочники (truck types, org types, etc) |
| `services/normalizers.py` | Нормализация email/phone/name/inn |
| `services/user_display.py` | Отображение имени (с учётом is_deleted) |
| `services/plan_check.py` | Проверка тарифного плана |
| `services/telegram_notify.py` | Telegram уведомления |

---

## Доступ к контактам (ADR-013 B, принято 05.05.2026)

### Правило
Контактные данные (phone, email) участника сделки видны **только** другому участнику активной или завершённой сделки.

### Где раскрываются контакты

| Эндпоинт | Контакты | Условие |
|----------|----------|---------|
| `GET /api/loads/{id}` | **Никогда** | `owner_phone=None`, `owner_email=None` всегда |
| `GET /api/users/{id}` | **Никогда** | публичный профиль без контактов |
| `GET /api/deals/my` | ✅ Да | `viewer_is_participant = True` → shipper.phone, carrier.phone |
| `GET /api/deals/{id}` | ✅ Да | только если viewer = shipper_id или carrier_id |

### Что удалено
- `PRICING_ENABLED` (env var) — полностью удалён из `plan_check.py`
- `is_paid_plan()` — возвращает `True` для всех (заглушка до Pro-тарифа)
- `check_can_respond()` — возвращает `(True, "ok")` для всех
- Ограничения `responses_this_month` — счётчик сохранён в модели, но не проверяется

### Контакты в фронте
Компонент `renderDealCard()` показывает phone/email из `deal.shipper.phone` и `deal.carrier.phone`. Эти поля заполнены только если viewer — участник сделки.
