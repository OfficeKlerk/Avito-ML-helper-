"""Сквозная проверка каркаса: `python -m devkit.smoke`.

1. Настоящие сервисы: у каждого отвечает `/health` по общей схеме.
2. Заглушки: каждый пример из `fixtures/` запрашивается по сети и сверяется со схемой контракта.
   Для контракта C примеры проходят через настоящий протокол MCP.

Адреса берутся из окружения. Не заданный адрес пропускается:
    CORE_API_URL, AGENT_URL, KNOWLEDGE_URL, CORP_MOCK_URL — настоящие сервисы;
    STUB_CORE_API_URL, STUB_AGENT_URL, STUB_KNOWLEDGE_URL, STUB_CORP_MOCK_URL — заглушки.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import httpx

from .contracts import ERROR_SCHEMA, Contracts, Operation, load_operations

HEALTH_SCHEMA = "common.yaml#/components/schemas/Health"
SERVICES = {
    "core-api": ("CORE_API_URL", "STUB_CORE_API_URL", ["A"]),
    "agent": ("AGENT_URL", "STUB_AGENT_URL", ["B"]),
    "knowledge-service": ("KNOWLEDGE_URL", "STUB_KNOWLEDGE_URL", ["E"]),
    "corp-mock": ("CORP_MOCK_URL", "STUB_CORP_MOCK_URL", ["C", "D"]),
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def check_health(client: httpx.Client, base_url: str, service: str, contracts: Contracts) -> list[str]:
    try:
        response = client.get(f"{base_url}/health")
    except httpx.HTTPError as exc:
        return [f"{service}: /health не отвечает ({exc.__class__.__name__})"]
    if response.status_code != 200:
        return [f"{service}: /health вернул {response.status_code}"]
    body = response.json()
    problems = [f"{service}: /health: {e}" for e in contracts.errors(body, HEALTH_SCHEMA)]
    if not problems and body["service"] != service:
        problems.append(f"{service}: /health назвался {body['service']!r}")
    return problems


def replay_rest(client: httpx.Client, base_url: str, operations: list[Operation], contracts: Contracts) -> tuple[int, list[str]]:
    """Запросить у заглушки каждый REST-пример и сверить ответ с примером и схемой."""
    checked, problems = 0, []
    for op in operations:
        if op.is_mcp or op.operation == "health":  # /health проверяется отдельно
            continue
        for case in op.cases:
            label = f"{op.source} [{case.name}]"
            path = op.path or ""
            for key, value in (case.request.get("path_params") or {}).items():
                path = path.replace("{" + key + "}", value)
            response = client.request(
                op.method or "GET",
                f"{base_url}{path}",
                params=case.request.get("query"),
                json=case.request.get("body"),
                headers={**(case.request.get("headers") or {}), "X-Stub-Case": case.name},
            )
            checked += 1
            if response.status_code != case.response["status"]:
                problems.append(f"{label}: статус {response.status_code}, ожидался {case.response['status']}")
                continue
            body = response.json()
            if body != case.response.get("body"):
                problems.append(f"{label}: тело ответа отличается от примера")
            schema = case.response_schema or ERROR_SCHEMA
            problems += [f"{label}: {e}" for e in contracts.errors(body, schema)]
    return checked, problems


def _rpc(client: httpx.Client, url: str, method: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = client.post(
        url,
        headers={**MCP_HEADERS, **(headers or {})},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"{method}: {payload['error']}")
    return payload["result"]


def replay_mcp(client: httpx.Client, base_url: str, operations: list[Operation], contracts: Contracts) -> tuple[int, list[str]]:
    """Вызвать у заглушки каждый пример инструмента по протоколу MCP."""
    url = f"{base_url}/mcp"
    checked, problems = 0, []
    listed = {tool["name"] for tool in _rpc(client, url, "tools/list", {})["tools"]}
    for tool in contracts.mcp_tools():
        if tool["name"] not in listed:
            problems.append(f"MCP: инструмента {tool['name']} нет в списке сервера")
    for op in operations:
        if not op.is_mcp:
            continue
        for case in op.cases:
            label = f"{op.source} [{case.name}]"
            result = _rpc(
                client,
                url,
                "tools/call",
                {"name": op.tool, "arguments": case.request.get("arguments") or {}},
                {**(case.request.get("headers") or {}), "X-Stub-Case": case.name},
            )
            checked += 1
            if bool(result.get("isError")) != bool(case.response.get("is_error")):
                problems.append(f"{label}: isError не совпал с примером")
                continue
            body = result.get("structuredContent")
            if body != case.response.get("body"):
                problems.append(f"{label}: результат отличается от примера")
            schema = case.response_schema or ERROR_SCHEMA
            problems += [f"{label}: {e}" for e in contracts.errors(body, schema)]
    return checked, problems


async def sdk_roundtrip(base_url: str) -> list[str]:
    """Тот же сервер через официальный MCP-клиент — им будет пользоваться agent."""
    from mcp import Client

    try:
        async with Client(f"{base_url}/mcp") as client:
            tools = await client.list_tools()
            result = await client.call_tool("directory_get_me", {})
    except Exception as exc:  # noqa: BLE001 — любая ошибка клиента означает несовместимость
        return [f"MCP SDK: {exc.__class__.__name__}: {exc}"]
    problems = []
    if not tools.tools:
        problems.append("MCP SDK: сервер не вернул инструменты")
    if result.is_error or not result.structured_content:
        problems.append("MCP SDK: directory_get_me не вернул профиль")
    return problems


def run(env: dict[str, str] | None = None) -> int:
    env = dict(os.environ if env is None else env)
    contracts = Contracts.load()
    operations = load_operations()
    problems: list[str] = []
    lines: list[str] = []

    with httpx.Client(timeout=10.0) as client:
        for service, (real_var, stub_var, letters) in SERVICES.items():
            real_url, stub_url = env.get(real_var), env.get(stub_var)
            if real_url:
                found = check_health(client, real_url.rstrip("/"), service, contracts)
                problems += found
                lines.append(f"  {service}: /health {'ок' if not found else 'ОШИБКА'} ({real_url})")
            if stub_url:
                base = stub_url.rstrip("/")
                mine = [op for op in operations if op.contract in letters]
                found = check_health(client, base, service, contracts)
                n_rest, rest_problems = replay_rest(client, base, mine, contracts)
                found += rest_problems
                n_mcp = 0
                if "C" in letters:
                    n_mcp, mcp_problems = replay_mcp(client, base, mine, contracts)
                    found += mcp_problems + asyncio.run(sdk_roundtrip(base))
                problems += found
                suffix = f", MCP {n_mcp}" if n_mcp else ""
                lines.append(f"  заглушка {service}: примеров REST {n_rest}{suffix} — {'ок' if not found else 'ОШИБКА'}")

    if not lines:
        print("Не задан ни один адрес — проверять нечего. См. описание в devkit/devkit/smoke.py.")
        return 2
    print("Сквозная проверка:")
    print("\n".join(lines))
    if problems:
        print(f"\nНайдено проблем: {len(problems)}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nВсе проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
