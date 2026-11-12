---
id: kb_delivery_dev_setup
title: "Локальное окружение backend-разработчика Доставки"
visibility: ["team:team_delivery"]
tags: ["окружение", "go", "postgresql", "redis", "docker"]
updated_at: "2026-10-30"
disclaimer: "Тестовая инструкция, не является регламентом Авито"
---

# Локальное окружение backend-разработчика Доставки

## Что понадобится {#requirements}

Доступ к GitLab и VPN, установленные Go, Docker и клиент PostgreSQL. Без доступа к GitLab репозиторий не склонировать — сначала запроси его.

## Первый запуск {#first-run}

1. Склонируй репозиторий сервиса команды.
2. Скопируй пример конфигурации: `cp .env.example .env`.
3. Подними зависимости: `docker compose up -d postgres redis`.
4. Примени миграции: `make migrate`.
5. Запусти сервис: `make run` и проверь `http://localhost:8080/health`.

## Частые проблемы {#troubleshooting}

- Сервис не видит базу — проверь, что контейнер PostgreSQL запущен и порт 5432 свободен.
- Тесты падают на стенде — проверь, что VPN включён.
- Не помогло — напиши в `#delivery-onboarding`, приложи текст ошибки.
