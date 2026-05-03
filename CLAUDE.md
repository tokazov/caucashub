# CLAUDE.md — Правила работы с кодом CaucasHub

## Какой код считается продакшном

**Продакшн = папка `/app/`**

Это единственный код который деплоится на Railway. Все анализ, правки, дебаг и рефакторинг — только здесь.

### Структура:
```
caucashub/
├── app/              ← ПРОДАКШН (Railway)
│   ├── main.py       ← точка входа
│   ├── routers/      ← API роуты
│   ├── models/       ← SQLAlchemy модели
│   ├── services/     ← бизнес-логика
│   └── config.py     ← настройки
├── frontend/         ← Фронт (Cloudflare Pages)
│   ├── main.js       ← весь фронтенд JS
│   └── index.html    ← разметка
├── tests/            ← интеграционные тесты
├── docs/             ← ADR и документация
├── _archive_backend/ ← ⛔ АРХИВ, НЕ ТРОГАТЬ
└── main.py           ← wrapper для uvicorn
```

## ⛔ _archive_backend/ — ЗАПРЕЩЁННАЯ ЗОНА

Папка `_archive_backend/` — это старый черновой код, который **никогда не деплоился**.

**Правила:**
- Не читать файлы из `_archive_backend/`
- Не анализировать импорты оттуда
- Не ссылаться на него как на «текущий код»
- Не копировать оттуда логику

Если видишь баг в `_archive_backend/` — это не баг продакшна.

## Начало каждого задания

Каждое задание по коду начинать с фразы:
**«Работаю в app/ (продакшн), не в backend/»**

## Деплой

- Бэкенд → Railway (автодеплой при пуше в master)
- Фронт → Cloudflare Pages (из папки `frontend/out/` или статика)
- Запуск: `python main.py` → `uvicorn app.main:app`

## Тесты

```bash
cd caucashub
pytest tests/ -v
```

## Линтер

```bash
ruff check app/
ruff check app/ --fix  # автофиксы
```
