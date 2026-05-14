# CaucasHub Frontend Tests

Тесты для vanilla JS фронта. Используют Node.js built-in test runner (`node:test`) + jsdom.

## Запуск

```bash
cd tests/frontend
npm install        # один раз
node --test tests/ # запустить все тесты
```

## Структура

```
tests/frontend/
├── package.json        — зависимости (только jsdom + node:test встроенный)
├── README.md           — этот файл
├── helpers/
│   └── setup.js        — создание jsdom-окружения с main.js/api.js
└── tests/
    ├── package_a_xss.test.js     — XSS-фиксы (Пакет A)
    └── package_b_contracts.test.js — Контракты + silent failures (Пакет B)
```

## Подход

Фронт — pure vanilla JS без сборки. Тесты:
1. Создают jsdom `window` с нужными глобалами (TRANSLATIONS, localStorage, fetch-mock)
2. Загружают нужные функции из main.js через `eval` в контексте jsdom
3. Проверяют поведение через стандартный `node:test` + `assert`

Prod bundle не затронут. npm только в `tests/frontend/`.
