"""Заглушка сервиса по примерам из `fixtures/`: `python -m devkit.stub_server`.

Один и тот же сервер изображает любой из четырёх сервисов — какой именно, задают переменные окружения:

    STUB_SERVICE    имя сервиса для /health (core-api | agent | knowledge-service | corp-mock)
    STUB_CONTRACTS  контракты, которые он отдаёт, через запятую (A | B | C,D | E)
    STUB_CASE       пример по умолчанию для всех операций (необязательно)
    PORT            порт, по умолчанию 8000

Как выбрать ответ:
  1. заголовок `X-Stub-Case: <имя или вид примера>` в запросе;
  2. общий режим: `POST /__stub/case {"case": "unavailable"}` (сброс — `{"case": null}`);
  3. правило `match` в примере (подстрока в поле тела запроса или значение параметра пути);
  4. иначе — успешный пример по умолчанию.

Виды `forbidden` и `unavailable` работают для любой операции: если своего примера нет,
заглушка отдаёт типовой отказ. Так любой сервис может получить от соседа успех, отказ и сбой.

Служебные адреса: `GET /__stub/fixtures` — что умеет заглушка, `GET|DELETE /__stub/calls` — журнал вызовов.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .contracts import CONTRACT_FILES, Case, Contracts, Operation, load_operations, select_case

GENERIC_ERRORS = {
    "forbidden": (403, "forbidden", "Заглушка: доступ запрещён."),
    "unavailable": (503, "unavailable", "Заглушка: сервис недоступен."),
}
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@dataclass
class StubState:
    service: str
    contracts: Contracts
    operations: list[Operation]
    forced_case: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def rest_operations(self) -> list[Operation]:
        return [op for op in self.operations if not op.is_mcp and op.operation != "health"]

    @property
    def mcp_operations(self) -> dict[str, Operation]:
        return {op.tool: op for op in self.operations if op.tool}

    def pick(self, op: Operation, requested: str | None, **context: Any) -> tuple[Case | None, str | None]:
        """Пример для ответа. Второй элемент — вид типового отказа, если своего примера нет."""
        wanted = requested or self.forced_case
        case = select_case(op, wanted, **context)
        if case is None and wanted in GENERIC_ERRORS:
            return None, wanted
        if case is None:
            # Имя примера относится к другой операции — отвечаем как обычно.
            case = select_case(op, None, **context)
        return case, None

    def record(self, **entry: Any) -> None:
        self.calls.append(entry)
        del self.calls[:-200]


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def build_state(service: str, contract_letters: list[str], forced_case: str | None = None) -> StubState:
    unknown = [c for c in contract_letters if c not in CONTRACT_FILES]
    if unknown:
        raise ValueError(f"неизвестные контракты: {', '.join(unknown)}")
    operations = [op for op in load_operations() if op.contract in contract_letters]
    return StubState(service=service, contracts=Contracts.load(), operations=operations, forced_case=forced_case)


# ---------------------------------------------------------------- REST


def rest_routes(state: StubState) -> list[Route]:
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok", "service": state.service, "version": "stub"})

    async def fixtures(_: Request) -> Response:
        return JSONResponse(
            {
                "service": state.service,
                "forced_case": state.forced_case,
                "operations": [
                    {
                        "contract": op.contract,
                        "operation": op.operation,
                        "method": op.method,
                        "path": op.path,
                        "tool": op.tool,
                        "cases": [{"name": c.name, "kind": c.kind, "description": c.description} for c in op.cases],
                    }
                    for op in state.operations
                ],
            }
        )

    async def set_case(request: Request) -> Response:
        payload = await request.json()
        state.forced_case = payload.get("case") or None
        return JSONResponse({"forced_case": state.forced_case})

    async def calls(request: Request) -> Response:
        if request.method == "DELETE":
            state.calls.clear()
        return JSONResponse({"calls": state.calls})

    async def dispatch(request: Request) -> Response:
        path = request.url.path
        try:
            body = json.loads(await request.body() or b"null")
        except ValueError:
            body = None
        for op in state.rest_operations:
            found = op.path_regex().match(path)
            if op.method != request.method or not found:
                continue
            case, generic = state.pick(
                op, request.headers.get("x-stub-case"), path_params=found.groupdict(), body=body
            )
            if case is None:
                status, code, message = GENERIC_ERRORS[generic or "unavailable"]
                name, body = f"generic_{generic}", error_body(code, message)
            else:
                if case.delay_ms:
                    await asyncio.sleep(case.delay_ms / 1000)
                status, name, body = case.response["status"], case.name, case.response.get("body")
            state.record(operation=op.operation, method=request.method, path=path, case=name, status=status)
            return JSONResponse(body, status_code=status, headers={"X-Stub-Case": name})
        return JSONResponse(
            error_body("not_found", f"Заглушка: в примерах нет операции {request.method} {path}."), status_code=404
        )

    return [
        Route("/health", health, methods=["GET"]),
        Route("/__stub/fixtures", fixtures, methods=["GET"]),
        Route("/__stub/case", set_case, methods=["POST"]),
        Route("/__stub/calls", calls, methods=["GET", "DELETE"]),
        Route("/{path:path}", dispatch, methods=METHODS),
    ]


# ---------------------------------------------------------------- MCP


def build_mcp_server(state: StubState) -> Server[Any]:
    """MCP-сервер с инструментами контракта C, отвечающий примерами."""
    declared = {tool["name"]: tool for tool in state.contracts.mcp_tools()}
    c_file = CONTRACT_FILES["C"]

    def absolute(ref: str) -> str:
        return ref if not ref.startswith("#") else c_file + ref

    async def list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
        tools = [
            types.Tool(
                name=name,
                description=" ".join(str(declared[name].get("description", "")).split()),
                input_schema=state.contracts.deref(absolute(declared[name]["input"]["$ref"])),
            )
            for name in state.mcp_operations
            if name in declared
        ]
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        op = state.mcp_operations.get(params.name)
        if op is None:
            body, is_error, name = error_body("not_found", f"Заглушка: инструмента {params.name} нет."), True, "unknown_tool"
        else:
            http_request = getattr(ctx, "request", None)
            requested = http_request.headers.get("x-stub-case") if http_request is not None else None
            case, generic = state.pick(op, requested, body=params.arguments or {})
            if case is None:
                _, code, message = GENERIC_ERRORS[generic or "unavailable"]
                body, is_error, name = error_body(code, message), True, f"generic_{generic}"
            else:
                if case.delay_ms:
                    await asyncio.sleep(case.delay_ms / 1000)
                body, is_error, name = case.response.get("body"), bool(case.response.get("is_error")), case.name
        state.record(operation=params.name, tool=params.name, case=name, is_error=is_error)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(body, ensure_ascii=False))],
            structured_content=body,
            is_error=is_error,
        )

    return Server("corp-mock-stub", version="stub", on_list_tools=list_tools, on_call_tool=call_tool)


# ---------------------------------------------------------------- приложение


def create_app(state: StubState) -> Starlette:
    routes = rest_routes(state)
    if not state.mcp_operations:
        return Starlette(routes=routes)
    # Маршрут /mcp добавляет сам SDK; он должен идти раньше общего маршрута заглушки.
    app = build_mcp_server(state).streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app.router.routes.extend(routes)
    return app


def app_from_env() -> Starlette:
    service = os.environ.get("STUB_SERVICE", "core-api")
    letters = [c.strip().upper() for c in os.environ.get("STUB_CONTRACTS", "A").split(",") if c.strip()]
    return create_app(build_state(service, letters, os.environ.get("STUB_CASE") or None))


def main() -> None:
    import uvicorn

    uvicorn.run(app_from_env(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_level="info")


if __name__ == "__main__":
    main()
