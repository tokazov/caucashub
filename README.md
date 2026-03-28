# CaucasHub.ge 🚛

**Первая биржа грузов и транспорта Кавказа**

## Стек
- **Backend:** FastAPI + PostgreSQL + SQLAlchemy
- **Frontend:** Next.js (в разработке)
- **AI:** Gemini 2.5 Flash
- **Хостинг:** Railway

## Запуск бэкенда локально

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

## Структура

```
backend/
  app/
    main.py          # FastAPI app
    config.py        # Настройки
    database.py      # PostgreSQL
    models/          # Таблицы БД
      user.py
      load.py
      truck.py
      response.py
    routers/         # API эндпоинты
      auth.py        # Регистрация/вход
      loads.py       # Грузы
      trucks.py      # Транспорт
      ai.py          # AI ассистент
      users.py       # Профили

frontend/            # Next.js (в разработке)
```

## API

| Метод | URL | Описание |
|---|---|---|
| POST | /api/auth/register | Регистрация |
| POST | /api/auth/login | Вход |
| GET  | /api/loads | Список грузов |
| POST | /api/loads | Разместить груз |
| GET  | /api/trucks | Список транспорта |
| POST | /api/ai/chat | AI ассистент |
| POST | /api/ai/rate | Расчёт ставки |
| POST | /api/ai/parse-load | Парсинг груза из текста |
# redeploy Sat Mar 28 12:29:17 PM UTC 2026
