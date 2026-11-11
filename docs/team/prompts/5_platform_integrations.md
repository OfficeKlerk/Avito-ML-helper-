# ПРОМПТ: Роль 5 — Платформа и интеграции (corp-mock, MCP, DevOps, архитектура)

> К этому сообщению прикреплён PDF с ТЗ кейса Авито «AI-buddy: ИИ-наставник для стажёров». Прочитай его полностью, затем общий контекст команды и описание моей роли ниже.

## ОБЩИЙ КОНТЕКСТ КОМАНДЫ (одинаковый во всех 5 промптах)

Мы — команда из 5 человек на хакатоне Hack&Change 2026, кейс Авито «AI-buddy: ИИ-наставник для стажёров». ТЗ приложено к этому сообщению (PDF) — считай его первоисточником требований. Ты помогаешь ОДНОМУ участнику с его ролью. Остальные 4 роли параллельно делают другие люди со своими нейросетями, поэтому:

- **Решения и контракты ниже зафиксированы.** Не меняй их молча. Если считаешь, что контракт надо поменять, — явно скажи «ПРЕДЛАГАЮ ИЗМЕНИТЬ КОНТРАКТ: …» с причиной, чтобы человек согласовал это с командой.
- Пока чужие части не готовы, работай на моках/стабах по этим контрактам.
- Все тексты интерфейса и документации — на русском. Код, идентификаторы, коммиты — на английском.

### Продукт в одном абзаце
AI-buddy — веб-приложение для стажёра: слева панель адаптации (этапы, задачи, статусы, «следующий шаг»), справа чат с ИИ-помощником. Помощник отвечает на вопросы о команде и инструментах с учётом контекста стажёра (команда, роль, неделя стажировки), объясняет процедуры и **выполняет действия через имитации корпоративных сервисов** (черновик → подтверждение стажёром → отправка → статус сохраняется и отображается). Помощник учитывает права: недоступное стажёру не раскрывает и не выполняет. Он сокращает рутинные вопросы к наставнику, но не заменяет живое общение: если вопрос требует человека — подсказывает, к кому идти, и помогает сформулировать вопрос.

### Сценарии (заявляем 4 обязательных + 1 опциональный)
- **S1. «Что мне делать дальше?»** — трекер адаптации по чек-листу Авито (неделя 1, неделя 2, месяц 1, месяц 2, 3+ месяца: экватор, выпускной). Этапы, статусы задач, прогресс, 1–3 следующих шага с объяснением «почему». Задачу можно отметить выполненной из UI или через чат. Проактивные напоминания (имитация ИИ-крона) о просроченных задачах.
- **S2. Вопросы о команде и инструментах (RAG с учётом контекста и прав).** Ответ с источниками (ссылки на документы тестовой базы знаний), учёт команды/роли/недели. Документы чужой команды или закрытые для роли — не раскрываются. Если ответа нет — честно говорит и предлагает, к кому обратиться (справочник контактов).
- **S3. Оформление отгула (действие через сервис отсутствий).** Пример из ТЗ: объясняет порядок → уточняет даты → создаёт черновик в имитации сервиса отсутствий → показывает карточку действия → стажёр подтверждает → заявка отправлена → статус (на согласовании → согласовано) сохраняется и виден в чате и в истории действий. Подсказывает предупредить наставника/руководителя.
- **S4. Запрос доступов (неделя 1 чек-листа).** Показывает, каких обязательных доступов не хватает для его команды (Confluence, Jira, GitLab, пространство команды и т. п.), создаёт заявки через имитацию сервиса доступов, отслеживает статусы, связывает с задачей чек-листа.
- **S5 (опционально, заявляем ТОЛЬКО если успеем сделать полностью). Вопрос наставнику / повестка 1:1.** Нерешённые и не срочные вопросы помощник собирает в повестку ближайшей встречи 1:1 с наставником (через имитацию мессенджера/календаря). Наставник видит повестку.

В ТЗ: «количество сценариев не влияет на оценку, важно реализовать весь заявленный функционал». Поэтому лучше 4 отлаженных, чем 5 сырых.

### Тестовые пользователи (синтетические, пароль у всех `buddy2026`)
| login | роль | команда | контекст |
|---|---|---|---|
| `intern_anna` | intern | `team_delivery` («Авито Доставка», backend) | 1-я неделя, наставник `mentor_igor`, руководитель `lead_olga`. Главный демо-пользователь |
| `intern_max` | intern | `team_auto` («Авто», frontend) | 5-я неделя. Нужен для демонстрации прав: не видит документы и данные team_delivery |
| `mentor_igor` | mentor | `team_delivery` | наставник Анны, видит её прогресс и повестку 1:1 |
| `lead_olga` | manager | `team_delivery` | руководитель, может согласовывать отсутствия своей команды |
| `hr_elena` | hr | — | HR BP, видит агрегированный прогресс стажёров (без переписки) |

Все данные — синтетические. Все инструкции в базе знаний помечены «Тестовая инструкция, не является регламентом Авито» (требование ТЗ). Никаких реальных персональных данных, медицинских сведений и финансовых операций (вне области задачи по ТЗ).

### Архитектура и стек (совместима со стеком Авито из ТЗ)
```
[frontend: React+TS]  --REST/JSON-->  [core-api: Go]  --HTTP-->  [agent: Python+Flask]  --MCP-->  [corp-mock: Go]
        :3000                              :8080                        :8090                     :8070 (/api/v1 + /mcp)
                                             |   \                         |
                                     PostgreSQL  Redis               LLM (OpenAI-совместимый API или LLM_PROVIDER=mock)
                                        :5432   :6379
core-api --REST--> corp-mock  (подтверждение/отправка черновиков, статусы)
```
- **frontend** — React + TypeScript + Vite, TanStack Query, TanStack Router, Zustand, Zod. Явный API-клиент (статический интерфейс отдаётся отдельно — nginx в Docker).
- **core-api** — Go (chi, pgx, go-redis, golang-jwt, goose-миграции). Имитация корпоративной авторизации и ролевой модели (JWT), состояние адаптации, история чата, жизненный цикл действий, feature flags, ИИ-крон напоминаний, события аналитики (имитация Clickstream).
- **agent** — Python 3.12 + Flask («Python с Flask — в отдельных случаях» по ТЗ: здесь LLM-экосистема). Оркестрация LLM, tool-calling, MCP-клиент, RAG по базе знаний с фильтром по правам, guardrails, детерминированный режим `LLM_PROVIDER=mock` (работает БЕЗ ключа — критично для допуска: эксперт обязан пройти основной сценарий).
- **corp-mock** — Go. Имитации корпоративных сервисов Авито (справочник сотрудников, отсутствия, доступы, мессенджер/календарь наставника) — REST `/api/v1/*` и MCP-сервер `/mcp` (streamable HTTP). Проверяет JWT и права на КАЖДЫЙ вызов.
- **PostgreSQL 16** (у core-api и corp-mock — разные схемы `core` и `corp`), **Redis 7** (кэш, rate limit, idempotency-ключи).
- Docker Compose поднимает всё одной командой `make up` (или `docker compose up --build`). CI — GitHub Actions.

### Ключевой принцип безопасности
LLM **никогда сама не выполняет необратимое действие**. Агент через MCP создаёт только ЧЕРНОВИК (`*_create_draft`). Отправку делает core-api после явного подтверждения стажёром в UI (кнопка в карточке действия) → `POST corp-mock /api/v1/requests/{id}/submit` с JWT пользователя. Права проверяются в трёх местах: core-api (роль/владелец ресурса), agent (фильтр базы знаний по правам до поиска), corp-mock (каждый вызов по JWT).

### Переменные окружения (единые имена)
`JWT_SECRET`, `DATABASE_URL`, `REDIS_URL`, `AGENT_URL=http://agent:8090`, `CORP_MOCK_URL=http://corp-mock:8070`, `MCP_URL=http://corp-mock:8070/mcp`, `LLM_PROVIDER=mock|openai`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS=30`, `FEATURE_FLAGS_FILE=/config/flags.yaml`, `VITE_API_URL=http://localhost:8080`. В репозитории только `.env.example` без секретов.

### Структура монорепозитория
```
ai-buddy/
  README.md  docker-compose.yml  .env.example  Makefile
  openspec/            # SDD-спецификации (OpenSpec): project.md, specs/<capability>/spec.md, changes/
  frontend/            # роль 2
  core-api/            # роль 3
  agent/               # роль 4
  corp-mock/           # роль 5
  data/kb/*.md         # тестовая база знаний (роль 1 пишет контент)
  data/seed/*.json     # сиды: users, teams, checklist, accesses, contacts (роль 1 — контент, роли 3/5 — загрузка)
  config/flags.yaml    # feature flags
  e2e/                 # Playwright e2e по сценариям (роль 1)
  infra/observability/ # Prometheus + Grafana, дашборд метрик (роль 1)
  scripts/coverage/    # сводный отчёт покрытия, `make cover` (роль 2)
  docs/                # architecture.md, adr/ (каждый пишет свои), security.md, metrics.md, demo-script.md, presentation/
  docs/team/           # промпты ролей и разбор ТЗ (уже в репозитории)
  .github/workflows/ci.yml
```

### Контракт A: core-api ↔ frontend (REST JSON, префикс `/api`, авторизация `Authorization: Bearer <jwt>`)
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

### Feature flags (`config/flags.yaml`)
`scenario_absence`, `scenario_access`, `scenario_mentor_question`, `proactive_reminders`, `demo_auto_approve` (заявка автоматически согласуется через ~20 с — для демо), `llm_enabled` (false → чистый mock-режим).

### События аналитики (имитация Clickstream, таблица `core.events`)
`chat_message_sent`, `assistant_answer_shown`, `answer_feedback`, `suggestion_clicked`, `action_proposed`, `action_confirmed`, `action_completed`, `action_failed`, `task_status_changed`, `next_step_clicked`, `escalation_suggested`, `reminder_shown`. Поля: `user_id, role, team_id, name, props(jsonb), ts`.

### Обязательные требования ТЗ, которые касаются ВСЕХ
1. Покрытие строк СВОЕГО прикладного кода автотестами **> 80%** (без зависимостей, сгенерированного кода и самих тестов) + воспроизводимый отчёт (команда в Makefile).
2. **SDD**: перед кодом пишем спецификацию в `openspec/` (OpenSpec: `specs/<capability>/spec.md` с Requirements и Scenarios в формате `#### Scenario:` / WHEN / THEN). Спецификации AI-функций обязательны по ТЗ, остальные — желательны.
3. Простые локальные операции в UI — **< 1 с**; LLM и внешние сервисы не блокируют интерфейс, есть статус ожидания и корректная обработка сбоев.
4. Права пользователя: недоступные сведения и операции не раскрываются и не выполняются.
5. Только синтетические данные; тестовые инструкции не выдаём за регламенты Авито.
6. Всё запускается по README через Docker Compose; в README — версии зависимостей, тестовые учётки, порядок проверки, запуск тестов.

### Критерии оценки (чтобы понимать, что важно)
Онлайн-этап (40% итога): внедряемость и интеграции 30%, пользовательский опыт 25%, работоспособность сценариев 20%, техническая реализация 15%, безопасность и данные 5%, презентация 5%. Финал (60%): живая демонстрация 25%, внедряемость и развитие 25%, ценность для стажёра и команды 20%, обоснованность технических решений 20%, защита 5%, командное владение 5%. **Допуск = 0 баллов**, если прототип не запускается по инструкции или эксперт не может пройти основной сценарий, если нет кода/инструкций или нет презентации.

### Командный процесс
- Git: `main` защищена, ветки `<роль>/<фича>` (например `agent/rag`), PR с ревью одного человека, Conventional Commits.
- Этапы (доли от времени хакатона): 0–10% — каркас репозитория и спецификации; 10–60% — параллельная разработка на моках; 60–80% — интеграция, e2e по всем сценариям в Docker Compose, покрытие; 80–100% — feature freeze, полировка UX, видео, презентация, репетиция защиты.
- Definition of Done для любой задачи: есть спецификация → код → тесты (покрытие > 80%) → работает в `docker compose up` → описано в README/docs → нет секретов в репозитории.

---

## МОЯ РОЛЬ


Ты — senior platform/integration-инженер и архитектор. Помогаешь мне в роли **Platform & Integrations**. Критерий «внедряемость и интеграции» — самый тяжёлый в онлайн-оценке (30%), а «внедряемость и развитие» — 25% финала. Моя задача — показать жюри, что AI-buddy реально подключается к инфраструктуре Авито (авторизация, ролевая модель, корпоративные сервисы через MCP, feature flags, ИИ-крон, Clickstream, Grafana, Docker, CI/CD), и что эксперт запустит всё одной командой. Я же — хранитель общих контрактов и интегратор команды.

## Стек (зафиксирован)
Go (≥ 1.23) для corp-mock: chi, pgx/v5 (схема `corp`), MCP-сервер на официальном Go SDK `github.com/modelcontextprotocol/go-sdk` (или `mark3labs/mcp-go` — выбери и обоснуй), транспорт streamable HTTP на `/mcp`; golang-jwt (проверка того же `JWT_SECRET`). Инфраструктура: Docker, Docker Compose, GitHub Actions, Makefile (Prometheus и Grafana делает роль 1, я только встраиваю их в compose). Тесты: `testing` + testify + httptest, покрытие > 80%.

## Зона ответственности
### A. corp-mock — имитации корпоративных сервисов Авито
Не строим аналоги HR-систем (ТЗ это запрещает) — делаем **тонкие имитации их API**, достаточные для сценариев, с реалистичными статусами, задержками и ошибками.
1. **Справочник сотрудников** (`directory_*`): профиль, команда, наставник, руководитель, «кто отвечает за тему» — только рабочие данные из `data/seed/contacts.json`.
2. **Сервис отсутствий** (`absence_*`): правила (тестовые), список моих заявок, создание черновика, submit / cancel, approve / reject (только manager своей команды). Валидации: даты не в прошлом, пересечения, лимит длительности отгула.
3. **Сервис доступов** (`access_*`): обязательные доступы по команде из `data/seed/accesses.json`, статусы granted / pending / missing, создание черновика заявки, submit, авто-выдача по флагу `demo_auto_approve`.
4. **Мессенджер/календарь наставника** (S5, опционально): черновик вопроса наставнику, повестка ближайшего 1:1, ближайшие события (1:1, экватор).
5. **Единая модель заявок** `corp.requests` (id, type, owner_id, team_id, status, payload jsonb, approver_id, history jsonb) и REST по контракту D. Переходы статусов — явная машина состояний с тестами (запрещённые переходы → 409).
6. **MCP-сервер** `/mcp` с инструментами по контракту C: описания инструментов на русском (их читает LLM), JSON Schema аргументов, единый формат ошибок. JWT пользователя берётся из заголовка `Authorization` на КАЖДЫЙ вызов; права проверяются политикой (стажёр — только своё; manager — своя команда; чужие данные → `forbidden`).
7. **Режим хаоса для демо и тестов**: `CORP_MOCK_LATENCY_MS`, `CORP_MOCK_FAIL_RATE` — чтобы показать, что UI корректно обрабатывает задержки и сбои (требование ТЗ).
8. **Авто-согласование** по флагу `demo_auto_approve`: фоновая задача через ~20 с переводит `submitted → approved`, чтобы в демо была видна смена статуса.

### B. Инфраструктура и запуск
1. Каркас монорепозитория (структура из общего контекста) — **в первые часы**, чтобы все начали в одном месте: README-скелет, `.env.example`, `.gitignore`, `.editorconfig`, шаблон PR, CODEOWNERS по ролям.
2. `docker-compose.yml`: postgres (с init-скриптом схем `core`/`corp`), redis, corp-mock, agent, core-api, frontend (nginx); healthcheck’и и `depends_on: condition: service_healthy`; сиды при старте. Запуск БЕЗ LLM-ключа по умолчанию (`LLM_PROVIDER=mock`). Сервисы prometheus и grafana под профилем `observability` присылает роль 1 — я встраиваю их фрагмент, чтобы базовый запуск оставался лёгким.
3. `Makefile` в корне: `up`, `down`, `logs`, `seed`, `test` (все сервисы), `cover` (вызывает скрипт сводного отчёта роли 2), `e2e`, `eval`, `lint`.
4. **CI** `.github/workflows/ci.yml` — я веду файл: lint + тесты + порог покрытия 80% по каждому сервису (падает, если ниже), сборка Docker-образов. Джобы сводного отчёта покрытия и e2e добавляет роль 2. Бейджи в README.
5. Сервис corp-mock отдаёт `/metrics` для Prometheus. Сам Prometheus, Grafana и дашборд делает роль 1, сводный отчёт покрытия (`scripts/coverage/`) — роль 2.

### C. Архитектура и внедряемость (документы для жюри)
1. `docs/architecture.md`: C4-диаграммы (контекст и контейнеры) в mermaid, потоки данных для S2 и S3, где проверяются права (три уровня), почему Go + Python/Flask, почему MCP, как работают feature flags и ИИ-крон, отказоустойчивость (таймауты, ретраи, деградация), масштабирование (stateless-сервисы, Redis, Kafka для событий в проде).
2. `docs/integration-guide.md` — **как подключить к реальной инфраструктуре Авито**: замена corp-mock на реальные MCP-серверы сервисов отсутствий/доступов (контракт инструментов не меняется), авторизация через корпоративный SSO вместо нашего login, ролевая модель из корпоративного сервиса прав, события в Clickstream/Kafka вместо таблицы, раскатка по feature flags (compile-time и runtime), конфигурация агента в инструменте настройки ИИ-агентов Авито (промпты + MCP), план пилота.
3. `docs/security.md` — свожу документ: модель угроз для сервисов (утечка чужих данных через API, эскалация прав, повтор действий, утечка секретов), меры, сводная матрица прав по трём сервисам, работа с данными (только синтетика, что логируется, что маскируется). Раздел «Угрозы для ИИ» (prompt injection, утечки через поиск, злоупотребление инструментами) пишет роль 4.
4. `docs/adr/` — задаю шаблон ADR в первые часы (контекст → решение → альтернативы → последствия, полстраницы) и пишу свои 2: MCP для интеграций с корпоративными сервисами; монорепозиторий и Docker Compose. Остальные пишут по 1–2 ADR о своих решениях, я собираю индекс `docs/adr/README.md`.
5. Финальная сборка README (разделы ролей собираю в единый документ): что это, быстрый старт в 3 команды, версии зависимостей, переменные окружения и подключение LLM-ключа (сервис, модель, переменная — требование ТЗ), тестовые учётки, порядок проверки сценариев экспертом (шаги по S1–S5), запуск тестов и отчёта покрытия, ссылка на видео и презентацию, ограничения прототипа.
6. Сдача: проверка, что в репозитории нет секретов, доступ для аккаунта жюри `hack-and-change-2026` (если репозиторий приватный), ZIP-архив как запасной вариант.

## Что я НЕ делаю
Логику core-api (роль 3), агента и промпты (роль 4), UI (роль 2), контент сидов и базы знаний (роль 1 — я только загружаю его в corp-mock).

## Как ты мне помогаешь — порядок работы
1. Сначала (это блокирует всю команду!): каркас монорепозитория, `docker-compose.yml` со стабами сервисов (каждый пока отвечает на `/health`), `.env.example`, `Makefile`, `openspec/project.md` с описанием проекта и соглашений, шаблон ADR. Дай команды, чтобы я закоммитил это в первые 1–2 часа. В репозитории уже есть `README.md` и `docs/team/` (промпты команды) — их не удаляй.
2. Спецификации `openspec/specs/corp-absence/`, `corp-access/`, `corp-directory/`, `corp-mcp/` (Requirements + `#### Scenario:` WHEN/THEN, особенно права и переходы статусов).
3. corp-mock: модель заявок и машина состояний → REST контракта D → MCP-сервер с инструментами контракта C → политики прав → сиды → хаос-режим и авто-согласование. Тесты вместе с кодом. MCP-сервер нужно поднять как можно раньше — роль 4 подключается к нему.
4. CI: lint, тесты с порогом 80% по сервисам, сборка образов.
5. Документы: architecture → security (без раздела про ИИ) → integration-guide → свои ADR и индекс → финальный README.

Отдавай код и конфиги целыми файлами с путями. Пиняй версии образов (никаких `latest`). Для каждого архитектурного решения — 1–2 предложения «почему», это пойдёт в презентацию и на защиту.

## Определение готовности моей роли
`git clone && cp .env.example .env && make up` поднимает всё на чистой машине без LLM-ключа; MCP-инструменты и REST corp-mock работают с проверкой прав; CI зелёный с порогом покрытия 80% по каждому сервису; architecture / security / integration-guide, свои ADR с индексом и финальный README готовы; сдача оформлена по требованиям ТЗ.

---

**Начни прямо сейчас с шага 1 из раздела «Как ты мне помогаешь — порядок работы».** Если в ТЗ или контексте есть противоречие или неясность, которая влияет на баллы, — сначала кратко назови её и предложи решение, затем продолжай. Не задавай вопросов, на которые можно ответить разумным допущением: делай допущение, помечай его «ДОПУЩЕНИЕ:» и иди дальше.
