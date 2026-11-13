# devkit — проверка контрактов и заглушки

Общие инструменты задач G0.1 и G0.3. Запускаются через Docker, локальный Python не нужен.

| Команда | Что делает |
|---|---|
| `make contracts` | Сверяет примеры из `fixtures/` со схемами из `contracts/`, а идентификаторы в них — с `data/` |
| `make stubs-up` | Запускает заглушки четырёх сервисов |
| `make smoke` | Запускает сервисы и заглушки и проходит по сети все примеры, включая MCP |
| `make integration` | Общая сборка I1: отдельный стенд с чистой базой, контракты A–E на настоящих сервисах (`devkit/fullstack.py`) |
| `make test-devkit` | Тесты самих инструментов |

## Заглушки

Заглушка отвечает примерами из `fixtures/`. Правки примеров подхватываются после перезапуска контейнера.

| Сервис | Контракты | С твоей машины | Из другого контейнера |
|---|---|---|---|
| core-api | A | http://localhost:18080 | http://stub-core-api:8080 |
| agent | B | http://localhost:18090 | http://stub-agent:8090 |
| corp-mock | C, D | http://localhost:18070 (MCP: `/mcp`) | http://stub-corp-mock:8070 |
| knowledge-service | E | http://localhost:18060 | http://stub-knowledge-service:8060 |

Какой пример вернётся:

1. Заголовок `X-Stub-Case: <имя или вид примера>` в запросе.
2. Общий режим заглушки: `POST /__stub/case` с телом `{"case": "unavailable"}`. Сброс — `{"case": null}`.
3. Правило `match` в примере: например, сообщение со словом «отгул» вернёт уточнение даты.
4. Иначе — успешный пример по умолчанию.

Виды `forbidden` и `unavailable` работают для любой операции. Так сервис можно проверить на успех, отказ в доступе и сбой соседа.

```bash
curl -s -X POST http://localhost:18090/v1/chat -H 'Content-Type: application/json' -d '{"message": "Хочу отгул в пятницу"}'
```

```bash
curl -s -H 'X-Stub-Case: unavailable' http://localhost:18070/api/v1/requests/req_anna_dayoff_1
```

Служебные адреса: `GET /__stub/fixtures` — какие операции и примеры есть, `GET /__stub/calls` — журнал вызовов (`DELETE` очищает его).

Заглушки не проверяют токены и не хранят состояние: один и тот же запрос всегда даёт один и тот же ответ.

## Локальный запуск без Docker

```bash
cd devkit && python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

```bash
cd devkit && .venv/bin/python -m pytest
```
