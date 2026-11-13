# Все команды работают через Docker: локально нужны только Docker и make.
COMPOSE := docker compose
SERVICES := agent knowledge-service core-api corp-mock web-app

TEST_CONTEXTS := --build-context contracts=./contracts --build-context fixtures=./fixtures --build-context data=./data

.PHONY: help up down logs ps health stubs-up stubs-down contracts lint smoke integration test test-devkit eval eval-knowledge test-knowledge-agent test-core-api-db test-corp-mock-db $(addprefix test-,$(SERVICES))

help: ## Показать команды
	@grep -E '^[a-zA-Z_%-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  make %-22s %s\n", $$1, $$2}'

up: ## Собрать и запустить сервисы, интерфейс и PostgreSQL, дождаться готовности
	$(COMPOSE) up -d --build --wait

down: ## Остановить всё, включая заглушки (данные PostgreSQL сохраняются)
	$(COMPOSE) --profile stubs --profile tools down

logs: ## Логи сервисов
	$(COMPOSE) logs -f --tail=100

ps: ## Состояние контейнеров
	$(COMPOSE) --profile stubs ps

health: ## Проверить /health у запущенных сервисов
	$(COMPOSE) --profile tools run --rm --no-deps -e STUB_CORE_API_URL= -e STUB_AGENT_URL= -e STUB_KNOWLEDGE_URL= -e STUB_CORP_MOCK_URL= devkit python -m devkit.smoke

stubs-up: ## Запустить заглушки четырёх сервисов (порты 18060–18090)
	$(COMPOSE) --profile stubs up -d --build --wait stub-core-api stub-agent stub-corp-mock stub-knowledge-service

stubs-down: ## Остановить заглушки
	$(COMPOSE) --profile stubs rm -sf stub-core-api stub-agent stub-corp-mock stub-knowledge-service

contracts: ## Проверить контракты, примеры и тестовые данные
	$(COMPOSE) --profile tools run --rm --no-deps --build devkit python -m devkit.validate

lint: ## Проверка Python-кода ruff (Go — gofmt и vet, TypeScript — typecheck в тестах сервисов)
	docker run --rm -v "$(CURDIR):/repo:ro" -w /repo python:3.12-slim sh -c 'pip install -q --disable-pip-version-check --root-user-action=ignore ruff==0.8.6 && ruff check --no-cache agent knowledge-service devkit integration'

smoke: up stubs-up ## Сквозная проверка: /health сервисов и все примеры контрактов через заглушки
	$(COMPOSE) --profile tools run --rm --no-deps devkit python -m devkit.smoke

# Отдельный стенд для I1: свой проект, порты и чистая база, без LLM и без переопределений на заглушки из .env.
IT := COMPOSE_PROJECT_NAME=ai-buddy-it WEB_PORT=23000 CORE_API_PORT=28080 AGENT_PORT=28090 CORP_MOCK_PORT=28070 \
	KNOWLEDGE_PORT=28060 POSTGRES_PORT=25432 LLM_PROVIDER=mock AGENT_KNOWLEDGE_URL= AGENT_MCP_URL= \
	CORE_AGENT_URL= CORE_CORP_MOCK_URL= CORE_KNOWLEDGE_URL= WEB_CORE_API_URL= docker compose

integration: ## I1: контракты A–E на настоящих сервисах с чистой базой; лог стенда — reports/integration-compose.log
	@mkdir -p reports
	@# Один блок: при любом исходе, даже если стенд не поднялся, лог сохраняется, а стенд удаляется.
	@$(IT) up -d --build --wait && \
	$(IT) config --format json | $(IT) --profile tools run -T --rm --no-deps --build devkit python -m devkit.fullstack; \
	status=$$?; $(IT) logs --no-color > reports/integration-compose.log 2>&1; \
	$(IT) --profile tools down -v --remove-orphans >/dev/null 2>&1; exit $$status

test: $(addprefix test-,$(SERVICES)) test-core-api-db test-corp-mock-db test-devkit test-knowledge-agent ## Тесты всех сервисов и инструментов

$(addprefix test-,$(SERVICES)): test-%: ## Тесты одного сервиса: make test-agent
	docker build -q --target test $(TEST_CONTEXTS) -t ai-buddy-$*-test ./$* >/dev/null
	docker run --rm ai-buddy-$*-test

eval: ## Проверка качества агента: без модели и, если LLM настроена в .env, с моделью. Отчёт — agent/evals/reports/
	docker build -q --target test $(TEST_CONTEXTS) -t ai-buddy-agent-test ./agent >/dev/null
	docker run --rm $$( [ -f .env ] && echo --env-file .env ) -v "$(CURDIR)/agent/evals/reports:/srv/evals/reports" ai-buddy-agent-test python -m evals.run

test-devkit: ## Тесты проверки контрактов и заглушек
	docker build -q -f devkit/Dockerfile --target test -t ai-buddy-devkit-test . >/dev/null
	docker run --rm ai-buddy-devkit-test

eval-knowledge: ## Качество поиска: BM25 baseline и улучшенный поиск, dev и holdout
	docker build -q --target test $(TEST_CONTEXTS) -t ai-buddy-knowledge-service-test ./knowledge-service >/dev/null
	docker run --rm -v "$(CURDIR)/knowledge-service/evals/reports:/srv/evals/reports" ai-buddy-knowledge-service-test python -m evals.run --check

test-knowledge-agent: ## Настоящие agent и knowledge-service по HTTP, без LLM и заглушки поиска
	docker build -q -f integration/Dockerfile --build-context agent=./agent --build-context knowledge=./knowledge-service -t ai-buddy-knowledge-agent-test . >/dev/null
	docker run --rm ai-buddy-knowledge-agent-test

# Go-тесты сервиса $(1) на пустой базе $(2) из PostgreSQL в Compose; $(3) — переменная с адресом базы.
# Тесты с базой пропускаются только без этой переменной, поэтому здесь любой пропуск — ошибка.
define go-db-test
	$(COMPOSE) up -d --wait postgres
	$(COMPOSE) exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -qc "DROP DATABASE IF EXISTS $(2)" && psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -qc "CREATE DATABASE $(2)"'
	docker run --rm --network ai-buddy_default -v "$(CURDIR):/repo:ro" -w /repo/$(1) -e GOFLAGS=-buildvcs=false \
		-e $(3)="postgres://$${POSTGRES_USER:-buddy}:$${POSTGRES_PASSWORD:-buddy}@postgres:5432/$(2)?sslmode=disable" \
		golang:1.23-alpine sh -c 'go test ./... -count=1 -v -coverpkg=./internal/... -coverprofile=/tmp/cover.out > /tmp/test.log 2>&1; status=$$?; \
		grep -E "^(ok|FAIL|--- FAIL|--- SKIP)" /tmp/test.log; \
		if grep -q -- "--- SKIP" /tmp/test.log; then echo "Тесты с базой пропущены — так быть не должно"; exit 1; fi; \
		if [ $$status -ne 0 ]; then grep -B2 -A20 -- "--- FAIL" /tmp/test.log | head -80; exit $$status; fi; \
		go tool cover -func=/tmp/cover.out | tail -1'
endef

test-core-api-db: ## Тесты core-api с PostgreSQL и покрытие внутренних пакетов (тестовая база пересоздаётся)
	$(call go-db-test,core-api,buddy_core_test,CORE_TEST_DATABASE_URL)

test-corp-mock-db: ## Тесты corp-mock с PostgreSQL и покрытие внутренних пакетов (тестовая база пересоздаётся)
	$(call go-db-test,corp-mock,buddy_corp_test,CORP_TEST_DATABASE_URL)
