# Все команды работают через Docker: локально нужны только Docker и make.
COMPOSE := docker compose
SERVICES := agent knowledge-service core-api corp-mock

.PHONY: help up down logs ps health stubs-up stubs-down contracts smoke test test-devkit $(addprefix test-,$(SERVICES))

help: ## Показать команды
	@grep -E '^[a-zA-Z_%-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  make %-22s %s\n", $$1, $$2}'

up: ## Собрать и запустить четыре сервиса и PostgreSQL, дождаться готовности
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

smoke: up stubs-up ## Сквозная проверка: /health сервисов и все примеры контрактов через заглушки
	$(COMPOSE) --profile tools run --rm --no-deps devkit python -m devkit.smoke

test: $(addprefix test-,$(SERVICES)) test-devkit ## Тесты всех сервисов и инструментов

$(addprefix test-,$(SERVICES)): test-%: ## Тесты одного сервиса: make test-agent
	docker build -q --target test --build-context contracts=./contracts --build-context fixtures=./fixtures -t ai-buddy-$*-test ./$* >/dev/null
	docker run --rm ai-buddy-$*-test

test-devkit: ## Тесты проверки контрактов и заглушек
	docker build -q -f devkit/Dockerfile --target test -t ai-buddy-devkit-test . >/dev/null
	docker run --rm ai-buddy-devkit-test
