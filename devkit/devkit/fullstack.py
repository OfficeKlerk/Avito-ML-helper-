"""I1: контракты A–E на настоящих сервисах вместе — `make integration`.

Стенд поднимается с чистой базой (миграции и демоданные с нуля), без заглушек и без LLM.
Проверка входит по-настоящему (JWT от core-api), проходит пути пользователя через core-api
и обращается к каждому сервису напрямую. Каждый ответ сверяется со схемой контракта,
у каждого вызова есть предел времени. На stdin — `docker compose config --format json`:
по нему проверяется, что ни один рабочий адрес не указывает на заглушку.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .contracts import ERROR_SCHEMA, Contracts, load_operations
from .smoke import MCP_HEADERS, SERVICES, check_health

MONTHS = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]
# Ответ в чате ждёт агента и инструменты; остальным вызовам хватает пары секунд.
CHAT_LIMIT, CALL_LIMIT = 30.0, 5.0


class Run:
    def __init__(self, contracts: Contracts):
        self.contracts = contracts
        self.ops = {(op.contract, op.operation): op for op in load_operations()}
        self.problems: list[str] = []
        self.calls = 0
        self.http = httpx.Client(timeout=CHAT_LIMIT + 10)

    def schema(self, contract: str, operation: str, status: int) -> str | None:
        op = self.ops[(contract, operation)]
        for case in op.cases:
            if case.response["status"] == status:
                return case.response_schema or (ERROR_SCHEMA if status >= 400 else None)
        return ERROR_SCHEMA if status >= 400 else op.default_case().response_schema

    def call(self, contract: str, operation: str, method: str, url: str, *, status: int = 200, token: str | None = None,
             body: object = None, headers: dict[str, str] | None = None, limit: float = CALL_LIMIT) -> object:
        """Вызов с проверкой статуса, схемы ответа и времени. Возвращает тело или None."""
        label = f"{contract}/{operation} {method} {url.split('/', 3)[-1]}"
        all_headers = {**(headers or {})}
        if token:
            all_headers["Authorization"] = f"Bearer {token}"
        started = time.monotonic()
        try:
            response = self.http.request(method, url, json=body, headers=all_headers)
        except httpx.HTTPError as exc:
            self.problems.append(f"{label}: нет ответа ({exc.__class__.__name__})")
            return None
        elapsed = time.monotonic() - started
        self.calls += 1
        if elapsed > limit:
            self.problems.append(f"{label}: {elapsed:.1f} с, предел {limit:.0f} с")
        if response.status_code != status:
            self.problems.append(f"{label}: статус {response.status_code}, ожидался {status}: {response.text[:200]}")
            return None
        try:
            data = response.json()
        except ValueError:
            self.problems.append(f"{label}: ответ не JSON: {response.text[:200]}")
            return None
        schema = self.schema(contract, operation, status)
        if schema:
            self.problems += [f"{label}: {error}" for error in self.contracts.errors(data, schema)]
        return data

    def mcp(self, base: str, tool: str, arguments: dict, token: str | None) -> dict:
        headers = {**MCP_HEADERS, **({"Authorization": f"Bearer {token}"} if token else {})}
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        self.calls += 1
        try:
            response = self.http.post(f"{base}/mcp", json=payload, headers=headers)
            if response.status_code != 200:
                return {"isError": True, "http": response.status_code}
            return response.json().get("result") or {"isError": True}
        except (httpx.HTTPError, ValueError) as exc:
            return {"isError": True, "error": exc.__class__.__name__}

    def expect(self, ok: bool, problem: str) -> None:
        if not ok:
            self.problems.append(problem)


def no_stubs(config: dict) -> list[str]:
    """Ни один рабочий сервис не смотрит на заглушку."""
    problems = []
    for name, service in (config.get("services") or {}).items():
        if name.startswith("stub-") or name == "devkit":
            continue
        for key, value in (service.get("environment") or {}).items():
            if isinstance(value, str) and "stub-" in value:
                problems.append(f"{name}: {key} указывает на заглушку ({value})")
    return problems


def absence_day(today: date) -> date:
    """Ближайший будний день не раньше чем через два дня: отгул на него точно допустим."""
    day = today + timedelta(days=2)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def main(env: dict[str, str], config: dict | None) -> int:
    run = Run(Contracts.load())
    core, agent, kb, corp = (env[SERVICES[s][0]].rstrip("/") for s in ("core-api", "agent", "knowledge-service", "corp-mock"))
    if config is None:
        run.problems.append("не передан docker compose config: проверка заглушек невозможна")
    else:
        run.problems += no_stubs(config)
    for service, (var, _, _) in SERVICES.items():
        run.problems += check_health(run.http, env[var].rstrip("/"), service, run.contracts)

    # A: вход и профиль.
    login = run.call("A", "auth_login", "POST", f"{core}/api/auth/login", body={"login": "intern_anna", "password": "buddy2026"})
    other = run.call("A", "auth_login", "POST", f"{core}/api/auth/login", body={"login": "intern_max", "password": "buddy2026"})
    if not login or not other:
        return report(run)
    anna, max_token = login["token"], other["token"]
    run.call("A", "auth_login", "POST", f"{core}/api/auth/login", status=401, body={"login": "intern_anna", "password": "wrong"})
    run.call("A", "me", "GET", f"{core}/api/me", token=anna)
    run.call("A", "me", "GET", f"{core}/api/me", status=401)
    run.call("A", "onboarding_get", "GET", f"{core}/api/onboarding", token=anna)
    run.call("A", "onboarding_task_patch", "PATCH", f"{core}/api/onboarding/tasks/t_join_channels", token=anna, body={"status": "done"})
    run.call("A", "onboarding_task_patch", "PATCH", f"{core}/api/onboarding/tasks/t_join_channels", status=422, token=anna, body={"status": "finished"})

    # A + B + E: вопрос с источником, повтор с ключом, источник открывается через core-api.
    key = {"Idempotency-Key": f"it-{uuid.uuid4()}"}
    question = {"text": "Во сколько у нас стендап?"}
    answer = run.call("A", "chat_message_post", "POST", f"{core}/api/chat/messages", token=anna, body=question, headers=key, limit=CHAT_LIMIT)
    if answer:
        sources = answer["assistant_message"]["sources"]
        run.expect(bool(sources), "ответ на вопрос о стендапе без источников")
        for doc_id in sorted({s["doc_id"] for s in sources}):
            run.call("A", "knowledge_document_get", "GET", f"{core}/api/knowledge/documents/{doc_id}", token=anna)
        again = run.call("A", "chat_message_post", "POST", f"{core}/api/chat/messages", token=anna, body=question, headers=key)
        run.expect(again == answer, "повтор с тем же Idempotency-Key вернул другой ответ")
    run.call("A", "chat_message_post", "POST", f"{core}/api/chat/messages", status=409, token=anna, body={"text": "Другое"}, headers=key)
    run.call("A", "chat_messages_list", "GET", f"{core}/api/chat/messages?limit=10", token=anna)
    run.call("A", "knowledge_document_get", "GET", f"{core}/api/knowledge/documents/kb_auto_access", status=403, token=anna)
    run.call("A", "knowledge_document_get", "GET", f"{core}/api/knowledge/documents/kb_missing", status=404, token=anna)

    # A + B + C + D: отгул — агент через MCP создаёт черновик в corp-mock, core-api отправляет его по REST.
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    day = absence_day(today)
    draft = run.call("A", "chat_message_post", "POST", f"{core}/api/chat/messages", token=anna,
                     body={"text": f"Хочу взять отгул {day.day} {MONTHS[day.month]}"}, limit=CHAT_LIMIT)
    cards = draft["assistant_message"]["actions"] if draft else []
    run.expect(len(cards) == 1, f"ожидалась одна карточка отгула, получено {len(cards)}")
    if cards:
        card = cards[0]
        confirm = {"Idempotency-Key": f"it-confirm-{uuid.uuid4()}"}
        sent = run.call("A", "action_confirm", "POST", f"{core}/api/actions/{card['id']}/confirm", token=anna, headers=confirm)
        repeat = run.call("A", "action_confirm", "POST", f"{core}/api/actions/{card['id']}/confirm", token=anna, headers=confirm)
        run.expect(bool(sent) and sent.get("status") == "submitted", f"после подтверждения статус {sent and sent.get('status')}")
        run.expect(sent == repeat, "повтор подтверждения с тем же ключом вернул другой ответ")
        run.call("A", "action_get", "GET", f"{core}/api/actions/{card['id']}", token=anna)
        run.call("A", "action_get", "GET", f"{core}/api/actions/{card['id']}", status=404, token=max_token)
        stored = run.call("D", "request_get", "GET", f"{corp}/api/v1/requests/{card['external_id']}", token=anna)
        run.expect(bool(stored) and stored.get("status") == "submitted", "corp-mock не сохранил отправку заявки")
        run.call("D", "request_get", "GET", f"{corp}/api/v1/requests/{card['external_id']}", status=403, token=max_token)
    run.call("A", "actions_list", "GET", f"{core}/api/actions", token=anna)

    # A: уведомления и события метрик.
    notices = run.call("A", "notifications_list", "GET", f"{core}/api/notifications", token=anna)
    items = (notices or {}).get("items") or []
    run.expect(bool(items), "после отправки заявки нет уведомления")
    if items:
        path = f"{core}/api/notifications/{items[0]['id']}"
        run.call("A", "notification_mark_read", "PATCH", path, token=anna, body={"read": True})
        run.call("A", "notification_mark_read", "PATCH", path, status=404, token=max_token, body={"read": True})
    run.call("A", "product_event_create", "POST", f"{core}/api/metrics/events", token=anna, body={
        "event_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()), "scenario_id": str(uuid.uuid4()),
        "scenario": "knowledge", "event": "source_opened"})

    # B напрямую: пример запроса из fixtures с настоящим JWT.
    example = run.ops[("B", "chat")].default_case().request["body"]
    reply = run.call("B", "chat", "POST", f"{agent}/v1/chat", token=anna, limit=CHAT_LIMIT,
                     body={**example, "request_id": f"it-{uuid.uuid4().hex}", "now": datetime.now(ZoneInfo("Europe/Moscow")).isoformat()})
    run.expect(bool(reply) and reply.get("status") == "ok", f"агент ответил со статусом {reply and reply.get('status')}")

    # C напрямую: инструменты чтения по MCP с JWT; без JWT — отказ.
    for tool in ("directory_get_me", "absence_get_rules", "absence_list_my", "access_list_my"):
        result = run.mcp(corp, tool, run.ops[("C", tool)].default_case().request.get("arguments") or {}, anna)
        if result.get("isError"):
            run.problems.append(f"C/{tool}: ошибка {result}")
            continue
        schema = run.ops[("C", tool)].default_case().response_schema
        run.problems += [f"C/{tool}: {e}" for e in run.contracts.errors(result.get("structuredContent"), schema)]
    run.expect(bool(run.mcp(corp, "directory_get_me", {}, None).get("isError")), "C: MCP без JWT не отказал")

    # E напрямую.
    run.call("E", "search", "POST", f"{kb}/v1/search", token=anna, body={"query": "во сколько стендап"})
    run.call("E", "search", "POST", f"{kb}/v1/search", status=401, body={"query": "во сколько стендап"})
    run.call("E", "document_get", "GET", f"{kb}/v1/documents/kb_delivery_rituals", token=anna)
    return report(run)


def report(run: Run) -> int:
    print(f"Общая сборка: вызовов {run.calls}, проблем {len(run.problems)}")
    for problem in run.problems:
        print(f"  - {problem}")
    print("Все проверки пройдены." if not run.problems else "")
    return 1 if run.problems else 0


if __name__ == "__main__":
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    sys.exit(main(dict(os.environ), json.loads(raw) if raw.strip() else None))
