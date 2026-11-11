# Черновик контрактов A–D

Исходная точка для задачи **G0.1** из [плана ML-ядра](../docs/team/01_ML_CORE_BACKLOG.md). Это не утверждённые схемы: в G0.1 их уточняем, переносим в машиночитаемый вид, добавляем примеры в `fixtures/` и контракт E (agent ↔ knowledge-service). После этого файл можно удалить.

Отличия от текущего плана, которые нужно учесть в G0.1:
- Поиск по базе знаний вынесен из `agent` в `knowledge-service` (контракт E ещё не описан).
- Контракт A сейчас используется API-клиентом и интеграционными тестами; интерфейса пока нет.
- Сценарий «вопрос наставнику» (`mentor_question`, `mentor_question_create_draft`, `calendar_upcoming`) в план не входит.

### Ключевой принцип безопасности
LLM **никогда сама не выполняет необратимое действие**. Агент через MCP создаёт только ЧЕРНОВИК (`*_create_draft`). Отправку делает core-api после явного подтверждения стажёром в UI (кнопка в карточке действия) → `POST corp-mock /api/v1/requests/{id}/submit` с JWT пользователя. Права проверяются в трёх местах: core-api (роль/владелец ресурса), agent (фильтр базы знаний по правам до поиска), corp-mock (каждый вызов по JWT).

### Переменные окружения (единые имена)
`JWT_SECRET`, `DATABASE_URL`, `REDIS_URL`, `AGENT_URL=http://agent:8090`, `CORP_MOCK_URL=http://corp-mock:8070`, `MCP_URL=http://corp-mock:8070/mcp`, `LLM_PROVIDER=mock|openai`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS=30`, `FEATURE_FLAGS_FILE=/config/flags.yaml`, `VITE_API_URL=http://localhost:8080`. В репозитории только `.env.example` без секретов.


### Контракт A: API-клиент ↔ core-api (REST JSON, префикс `/api`, авторизация `Authorization: Bearer <jwt>`)
Ошибки всегда: `{"error": {"code": "string", "message": "текст для пользователя"}}`.
- `POST /api/auth/login` `{login, password}` → `{token, user: User}`
- `GET /api/me` → `User`
- `GET /api/onboarding` → `Onboarding`
- `PATCH /api/onboarding/tasks/{id}` `{status}` → `Task`
- `GET /api/chat/messages?limit=50` → `{messages: ChatMessage[]}`
- `POST /api/chat/messages` `{text}` → `{user_message: ChatMessage, assistant_message: ChatMessage}` (может длиться до 30 с — UI не блокируется, показывает статус ожидания)
- `POST /api/actions/{id}/confirm` (заголовок `Idempotency-Key`) → `ActionCard`
- `POST /api/actions/{id}/cancel` → `ActionCard`
- `GET /api/actions` → `{actions: ActionCard[]}` (история, статусы обновляются из corp-mock)
- `GET /api/notifications` → `{items: Notification[]}` (напоминания ИИ-крона и смены статусов)
- `POST /api/feedback` `{message_id, rating: "up"|"down", comment?}` → 204
- `POST /api/events` `{name, props}` → 204 (клиентская аналитика)
- `GET /api/flags` → `{flags: Record<string, boolean>}`
- `GET /api/mentor/interns` (только mentor/manager/hr) → прогресс своих стажёров
- `GET /api/health` → `{status:"ok"}`

Типы (TypeScript-нотация, в Go/Python — те же поля в snake_case):
```ts
type Role = "intern" | "mentor" | "manager" | "hr";
type User = { id: string; login: string; name: string; role: Role; team: {id: string; name: string} | null;
  mentor?: {id: string; name: string}; manager?: {id: string; name: string};
  start_date: string /* ISO date */; internship_week: number; program: "6m" | "9m" };
type TaskStatus = "todo" | "in_progress" | "done" | "blocked";
type Task = { id: string; stage_id: string; title: string; description: string; status: TaskStatus;
  due_date: string | null; source: "checklist" | "agent" | "mentor"; links: {title: string; url: string}[];
  related_action_id?: string };
type Stage = { id: string; title: string; period: string; status: "done" | "in_progress" | "todo"; tasks: Task[] };
type Onboarding = { stages: Stage[]; progress: number /* 0..100 */;
  next_steps: { task_id: string; title: string; reason: string }[] };
type Source = { doc_id: string; title: string; url: string };
type ActionType = "absence_request" | "access_request" | "mentor_question" | "task_status_update";
type ActionStatus = "draft" | "submitted" | "approved" | "rejected" | "cancelled" | "failed";
type ActionCard = { id: string; type: ActionType; status: ActionStatus; title: string;
  fields: Record<string, string>; /* человекочитаемые поля карточки: "Даты": "12.11–12.11" */
  external_id: string | null; /* id черновика/заявки в corp-mock */
  result?: { message: string; data?: Record<string, unknown> }; error?: string;
  created_at: string; updated_at: string };
type ChatMessage = { id: string; role: "user" | "assistant" | "system"; text: string /* markdown */;
  sources: Source[]; actions: ActionCard[]; suggestions: string[] /* быстрые ответы-чипы */;
  status: "ok" | "degraded" | "error"; created_at: string };
type Notification = { id: string; kind: "reminder" | "action_status"; text: string; created_at: string; read: boolean };
```

### Контракт B: core-api → agent (`POST {AGENT_URL}/v1/chat`)
Запрос:
```json
{ "request_id": "uuid",
  "user": { "id": "u_anna", "name": "Анна", "role": "intern", "team_id": "team_delivery", "team_name": "Авито Доставка",
            "internship_week": 1, "mentor": {"id": "u_igor", "name": "Игорь"}, "manager": {"id": "u_olga", "name": "Ольга"} },
  "auth_token": "<JWT пользователя — агент передаёт его в MCP-вызовы>",
  "onboarding": { "...": "объект Onboarding (сжатый)" },
  "history": [ {"role": "user", "text": "..."}, {"role": "assistant", "text": "..."} ],
  "message": "Как оформить отгул на пятницу?" }
```
Ответ:
```json
{ "text": "markdown-ответ", "sources": [ {"doc_id": "...", "title": "...", "url": "/kb/..."} ],
  "proposed_actions": [ { "type": "absence_request", "title": "Отгул 14.11", "external_id": "req_123",
                          "fields": {"Тип": "Отгул", "Даты": "14.11.2026", "Согласующий": "Ольга"} } ],
  "task_updates": [ {"task_id": "t_access_jira", "status": "in_progress"} ],
  "suggestions": ["Предупредить наставника", "Что ещё сделать на этой неделе?"],
  "escalation": {"needed": false, "contact": null},
  "status": "ok", "trace": [ {"tool": "absence_create_draft", "ok": true, "ms": 120} ] }
```
core-api сохраняет `proposed_actions` как `ActionCard` со статусом `draft`. При ошибке/таймауте LLM агент возвращает `status: "degraded"` и полезный ответ без LLM (шаблон), а не 500.

### Контракт C: agent → corp-mock (MCP-инструменты, streamable HTTP `/mcp`, заголовок `Authorization: Bearer <jwt пользователя>`)
| Инструмент | Аргументы | Результат |
|---|---|---|
| `directory_get_me` | — | профиль, команда, наставник, руководитель (только рабочие контакты) |
| `directory_find_contact` | `topic: string` | кто отвечает за тему (доступы, отпуска, Jira, онбординг…) в рамках доступного |
| `absence_get_rules` | — | тестовые правила оформления отгула/отпуска (с пометкой «тестовая инструкция») |
| `absence_list_my` | — | мои заявки на отсутствие и статусы |
| `absence_create_draft` | `kind: "day_off"\|"vacation", date_from, date_to, comment?` | `{request_id, status:"draft", approver, summary}` |
| `access_list_my` | — | `[{system, required, status: "granted"\|"pending"\|"missing"}]` |
| `access_create_draft` | `system, reason` | `{request_id, status:"draft", approver, summary}` |
| `mentor_question_create_draft` (S5) | `text, urgency: "low"\|"normal"` | `{request_id, status:"draft", meeting?}` |
| `calendar_upcoming` (S5) | `days: int` | ближайшие встречи (1:1, экватор) |

Ошибки инструментов: `{"error": {"code": "forbidden"|"not_found"|"validation"|"unavailable", "message": "..."}}`.

### Контракт D: core-api → corp-mock (REST `/api/v1`, JWT пользователя)
- `POST /api/v1/requests/{id}/submit` → `{id, type, status:"submitted", external_ref, approver}`
- `POST /api/v1/requests/{id}/cancel` → `{..., status:"cancelled"}`
- `GET /api/v1/requests/{id}` → текущий статус (`draft|submitted|approved|rejected|cancelled`)
- `POST /api/v1/requests/{id}/approve` / `reject` — только manager своей команды (для демо руководителем и для авто-согласования по флагу `demo_auto_approve`)
- `GET /api/v1/health`

