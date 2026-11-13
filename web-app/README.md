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
| `npm run gen:api` | Пересоздать типы `src/shared/api/schema.ts` из `contracts/a_core_api.yaml` |

Без Node, через Docker: `make test-web-app` — чистая установка по lockfile, проверка типов и тесты.

В `make up` интерфейс собирается и отдаётся nginx на http://localhost:3000 (порт — `WEB_PORT`). Тот же nginx пересылает `/api` в core-api: адрес задаёт `WEB_CORE_API_URL`, по умолчанию `http://core-api:8080`, без пути. Если адрес пустой, контейнер не стартует и пишет в лог, чего не хватает.

## Адрес API

Браузер ходит в core-api по пути `/api` того же адреса, поэтому CORS не нужен.

| Переменная | Когда | Что задаёт |
|---|---|---|
| `API_PROXY_TARGET` | `dev` и `preview` | Куда Vite проксирует `/api`. По умолчанию `http://localhost:8080` (core-api из `make up`) |
| `VITE_API_URL` | `build` | Адрес core-api, если он на другом хосте. По умолчанию пусто — тот же адрес, что у страницы |

Всё с префиксом `VITE_` попадает в код страницы и видно любому пользователю. Ключи и секреты туда не кладём: LLM и JWT_SECRET остаются на сервере.

## API-клиент

`src/shared/api/client.ts` — единый клиент контракта A. Типы запросов и ответов генерируются из контракта; тест `schema.test.ts` падает, если контракт поменяли, а типы — нет.

```ts
const { api } = useSession();
const me = await call(api.GET("/api/me"));
await call(api.POST("/api/actions/{action_id}/confirm", {
  params: { path: { action_id }, header: { "Idempotency-Key": key } },
}));
```

- Сам ставит `Authorization` и `X-Request-Id`.
- `call()` возвращает данные или бросает `ApiError` с `status`, `code` из контракта и текстом для пользователя. Нет сети — `code: "network"`, сервер не ответил вовремя — `"timeout"` (15 с на чтение, 60 с на запись: ответ в чате ждёт модель).
- GET после сбоя сети или 502/503/504 повторяется ещё два раза. POST и PATCH сам не повторяет никогда. Для повтора мутации создай ключ `newIdempotencyKey()` один раз на попытку пользователя и передавай тот же при повторе.
- Отмена: передай `signal` из `AbortController` — придёт обычный `AbortError`, не `ApiError`.
- 401 на запросе с токеном закрывает сессию и ведёт на вход.
- В тестах вместо сети — `fixtureFetch()` из `src/shared/api/fixtures.ts`: отвечает примерами из `fixtures/a_core_api/`. Выбрать случай: `fixtureFetch({ auth_login: "wrong_password" })`. В приложение он не подключается.

## Вход и сессия

`SessionProvider` и `useSession()` в `src/app/session.tsx`: пользователь, клиент, `login()` и `logout()`. Страницы за входом кладём в `children` маршрута с `RequireAuth`.

JWT хранится в `sessionStorage`: переживает перезагрузку вкладки, пропадает при её закрытии и сам не уходит с запросами, поэтому CSRF не страшен. Его могут прочитать скрипты страницы, поэтому интерфейс не вставляет чужой HTML. Профиль не хранится: после перезагрузки он берётся из `/api/me`. При выходе и при 401 токен и профиль удаляются, а страницы за входом пересоздаются, поэтому следующий пользователь не видит данных предыдущего.
