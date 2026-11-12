"""Клиенты инструментов (задача A4).

Поиск — knowledge-service по REST (контракт E), справочник и черновики — corp-mock по MCP (контракт C).
Адреса приходят из окружения, поэтому один и тот же клиент работает и с заглушкой, и с настоящим сервисом.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

ERROR_CODES = {"unauthorized", "forbidden", "not_found", "validation", "conflict", "rate_limited", "unavailable", "internal"}
UNAVAILABLE = "Сервис временно недоступен."


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code if code in ERROR_CODES else "unavailable"
        self.message = message


@dataclass
class Tools:
    """Инструменты одного запроса: общий токен пользователя, X-Request-Id и журнал вызовов для `trace`."""

    knowledge_url: str
    mcp_url: str
    token: str
    request_id: str
    timeout: float = 5.0
    trace: list[dict[str, Any]] = field(default_factory=list)
    # Созданные черновики по ключу идемпотентности: запасной режим после сбоя модели берёт их отсюда,
    # а не создаёт заново (A6).
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Общий срок ответа (time.monotonic()). Вызовы не ждут дольше него: иначе core-api не дождётся ответа,
    # а созданный черновик останется без карточки.
    deadline: float | None = None

    def time_left(self) -> float:
        if self.deadline is None:
            return self.timeout
        return min(self.timeout, max(0.5, self.deadline - time.monotonic()))

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        return self.traced("knowledge_search", lambda: self._post(f"{self.knowledge_url}/v1/search", {"query": query, "top_k": top_k})["results"])

    def mcp(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        key = (arguments or {}).get("idempotency_key")
        if key in self.drafts:
            return self.drafts[key]
        result = self.traced(tool, lambda: self._mcp(tool, arguments or {}))
        if key:
            self.drafts[key] = result
        return result

    def _mcp(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(asyncio.wait_for(self._call_tool(tool, arguments), self.time_left()))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Request-Id": self.request_id}

    def traced(self, name: str, call: Callable[[], Any]) -> Any:
        """Выполнить вызов и записать его в `trace`. Любой сбой, кроме ошибки контракта, — `unavailable`."""
        started, code = time.monotonic(), None
        try:
            return call()
        except ToolError as exc:
            code = exc.code
            raise
        except Exception as exc:  # сеть, таймаут, неожиданный ответ — для пользователя это одно и то же
            code = "unavailable"
            raise ToolError("unavailable", UNAVAILABLE) from exc
        finally:
            self.trace.append({"tool": name, "ok": code is None, "ms": int((time.monotonic() - started) * 1000), "error_code": code})

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={**self._headers(), "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.time_left()) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise _error(_json(exc.read())) from exc

    async def _call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with httpx2.AsyncClient(headers=self._headers(), timeout=self.time_left()) as http:
            async with Client(streamable_http_client(self.mcp_url, http_client=http)) as client:
                result = await client.call_tool(tool, arguments)
        body = result.structured_content or {}
        if result.is_error:
            raise _error(body)
        return body


def _json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _error(body: dict[str, Any]) -> ToolError:
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    return ToolError(str(error.get("code", "unavailable")), str(error.get("message") or UNAVAILABLE))


def tools_from_env(token: str, request_id: str) -> Tools:
    return Tools(
        knowledge_url=os.environ.get("KNOWLEDGE_URL", "http://localhost:8060").rstrip("/"),
        mcp_url=os.environ.get("MCP_URL", "http://localhost:8070/mcp"),
        token=token,
        request_id=request_id,
        timeout=float(os.environ.get("TOOL_TIMEOUT_SECONDS", "5")),
    )
