# Примеры запросов и ответов

Один файл — одна операция контракта. Эти примеры используют и заглушки, и проверки настоящих сервисов.

```json
{
  "contract": "D",
  "operation": "request_submit",
  "method": "POST",
  "path": "/api/v1/requests/{request_id}/submit",
  "request_schema": null,
  "cases": [
    {
      "name": "submitted",
      "kind": "success",
      "description": "Черновик отправлен.",
      "request": { "headers": {}, "path_params": {}, "body": null },
      "response": { "status": 200, "body": {} },
      "response_schema": "common.yaml#/components/schemas/CorpRequest"
    }
  ]
}
```

- `operation` — `operationId` из контракта. Для MCP вместо `method` и `path` указывается `tool`, в запросе — `arguments`, в ответе — `is_error`.
- `kind` — вид примера: `success`, `empty` (пустой результат), `forbidden` (401 или 403), `unavailable` (503), а также `validation`, `conflict`, `not_found`, `degraded`.
- `response_schema` — схема ответа. Для ошибок её можно не указывать: подставится общая схема ошибки.
- `match` — когда заглушка выбирает этот пример сама: `{"body": {"message": "отгул"}}` (подстрока в поле запроса) или `{"path_params": {"request_id": "req_max_vacation_1"}}`.
- `delay_ms` — задержка ответа заглушки.
- `<jwt:u_anna>` в заголовках — место для токена пользователя. Заглушки токен не проверяют.

У каждого контракта есть примеры успеха, пустого результата, отказа в доступе и недоступности. Идентификаторы в примерах должны существовать в `data/` — это проверяет `make contracts`.
