# web-app — интерфейс AI-buddy

React + TypeScript, сборка Vite. Один frontend и один артефакт сборки. Модули чата, адаптации и заявок живут в `src/features/` (задачи H, O, R), общие оболочка и клиент — в `src/app/` и `src/shared/` (задачи F).

## Команды

Нужен Node 22 или новее.

```bash
npm ci
```

```bash
npm run dev
```

| Команда | Что делает |
|---|---|
| `npm run dev` | Сервер разработки на http://localhost:5173 |
| `npm run build` | Проверка типов и production-сборка в `dist/` |
| `npm run typecheck` | Только проверка типов |
| `npm test` | Тесты Vitest и отчёт покрытия всего `src/` |
| `npm run preview` | Отдать собранный `dist/` локально |

Без Node, через Docker: `make test-web-app` — чистая установка по lockfile, проверка типов и тесты.

## Адрес API

Браузер ходит в core-api по пути `/api` того же адреса, поэтому CORS не нужен.

| Переменная | Когда | Что задаёт |
|---|---|---|
| `API_PROXY_TARGET` | `dev` и `preview` | Куда Vite проксирует `/api`. По умолчанию `http://localhost:8080` (core-api из `make up`) |
| `VITE_API_URL` | `build` | Адрес core-api, если он на другом хосте. По умолчанию пусто — тот же адрес, что у страницы |

Всё с префиксом `VITE_` попадает в код страницы и видно любому пользователю. Ключи и секреты туда не кладём: LLM и JWT_SECRET остаются на сервере.
