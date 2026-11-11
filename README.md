# AI-buddy — ИИ-наставник для стажёров

Проект команды на хакатоне Hack&Change 2026, кейс Авито «AI-buddy: ИИ-наставник для стажёров».

> README будет дополнен инструкцией запуска, тестовыми учётками и порядком проверки по мере разработки (отвечает роль 5 «Платформа и интеграции»).

## С чего начать команде

1. Открой [`docs/team/roles.html`](docs/team/roles.html) (скачай файл и открой в браузере). Там пять ролей и кнопки «Скопировать промпт».
2. Возьми свою роль, скопируй промпт в новый чат нейросети и приложи PDF с ТЗ кейса.
3. Нейросеть начнёт с шага 1 плана работы твоей роли.

Если удобнее работать с Markdown:

| Роль | Промпт |
|---|---|
| 1. Product Lead: продукт, контент, QA | [docs/team/prompts/1_product_lead.md](docs/team/prompts/1_product_lead.md) |
| 2. Frontend (React + TypeScript) | [docs/team/prompts/2_frontend.md](docs/team/prompts/2_frontend.md) |
| 3. Backend core-api (Go) | [docs/team/prompts/3_backend_core_api.md](docs/team/prompts/3_backend_core_api.md) |
| 4. AI-инженер (Python + Flask, LLM, MCP) | [docs/team/prompts/4_ai_engineer.md](docs/team/prompts/4_ai_engineer.md) |
| 5. Платформа и интеграции (corp-mock, MCP, DevOps) | [docs/team/prompts/5_platform_integrations.md](docs/team/prompts/5_platform_integrations.md) |

Полный разбор ТЗ, распределение ролей и план по времени: [docs/team/00_РАЗБОР_ТЗ_и_РОЛИ.md](docs/team/00_РАЗБОР_ТЗ_и_РОЛИ.md).

## Общий контекст — это договор команды

Все пять промптов начинаются с одинакового блока «Общий контекст команды»: сценарии, стек, тестовые учётки, структура репозитория и контракты API (A — фронтенд ↔ core-api, B — core-api ↔ агент, C — MCP-инструменты, D — core-api ↔ corp-mock). Меняете контракт — обновите его во всех пяти промптах и на странице `roles.html` и предупредите команду.

Все данные в проекте синтетические. Тестовые инструкции не являются регламентами Авито.
