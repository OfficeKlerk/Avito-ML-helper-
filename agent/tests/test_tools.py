"""A4: клиенты инструментов против настоящего HTTP- и MCP-сервера, поднятого в тесте.

Сервер отвечает примерами контрактов C и E — так проверяется, что клиент работает с любым сервисом по контракту.
"""

import json
import socket
import threading
import time

import pytest
import uvicorn
from conftest import default_responses
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from app.tools import ToolError, Tools, tools_from_env


class Backend:
    """Что сервер ответит и какие заголовки он увидел."""

    def __init__(self):
        self.search = (200, {"results": default_responses()["knowledge_search"]})
        self.tools = {name: (False, body) for name, body in default_responses().items() if name != "knowledge_search"}
        self.delay = 0.0
        self.seen: list[tuple[str, str | None, str | None]] = []

    def remember(self, name, headers):
        self.seen.append((name, headers.get("authorization"), headers.get("x-request-id")))


def build_app(backend: Backend):
    async def search(request: Request):
        backend.remember("knowledge_search", request.headers)
        status, body = backend.search
        if isinstance(body, str):
            return PlainTextResponse(body, status_code=status)
        return JSONResponse(body, status_code=status)

    async def list_tools(_ctx, _params):
        return types.ListToolsResult(tools=[
            types.Tool(name=name, input_schema={"type": "object"}) for name in backend.tools])

    async def call_tool(ctx, params: types.CallToolRequestParams):
        backend.remember(params.name, ctx.request.headers)
        if backend.delay:
            time.sleep(backend.delay)
        is_error, body = backend.tools[params.name]
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(body, ensure_ascii=False))],
            structured_content=body, is_error=is_error)

    app = Server("test-corp", on_list_tools=list_tools, on_call_tool=call_tool).streamable_http_app(
        json_response=True, stateless_http=True, host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    app.router.routes.append(Route("/v1/search", search, methods=["POST"]))
    return app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    backend = Backend()
    port = free_port()
    instance = uvicorn.Server(uvicorn.Config(build_app(backend), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    while not instance.started:
        time.sleep(0.02)
    yield backend, f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def backend(server):
    backend, _ = server
    fresh = Backend()
    backend.search, backend.tools, backend.delay, backend.seen = fresh.search, fresh.tools, 0.0, []
    return backend


@pytest.fixture()
def tools(server, backend):
    _, url = server
    return Tools(knowledge_url=url, mcp_url=f"{url}/mcp", token="user-jwt", request_id="rq-42-abcdef", timeout=2)


def test_search_returns_results_and_forwards_headers(tools, backend):
    results = tools.search("как оформить отгул")
    assert results[0]["source"]["chunk_id"] == "kb_absence_rules#day-off"
    assert backend.seen == [("knowledge_search", "Bearer user-jwt", "rq-42-abcdef")]
    assert tools.trace[0]["tool"] == "knowledge_search" and tools.trace[0]["ok"] is True


def test_mcp_call_returns_structured_result_and_forwards_headers(tools, backend):
    draft = tools.mcp("absence_create_draft", {"kind": "day_off"})
    assert draft["id"] == "req_anna_dayoff_1"
    assert backend.seen == [("absence_create_draft", "Bearer user-jwt", "rq-42-abcdef")]
    assert tools.trace == [{"tool": "absence_create_draft", "ok": True, "ms": tools.trace[0]["ms"], "error_code": None}]


def test_mcp_tool_error_keeps_code_and_message(tools, backend):
    backend.tools["absence_create_draft"] = (True, {"error": {"code": "forbidden", "message": "Нельзя."}})
    with pytest.raises(ToolError) as error:
        tools.mcp("absence_create_draft", {})
    assert (error.value.code, error.value.message) == ("forbidden", "Нельзя.")
    assert tools.trace[-1]["error_code"] == "forbidden"


def test_search_error_keeps_code_and_message(tools, backend):
    backend.search = (403, {"error": {"code": "forbidden", "message": "Нет доступа к документу."}})
    with pytest.raises(ToolError) as error:
        tools.search("отгул")
    assert (error.value.code, error.value.message) == ("forbidden", "Нет доступа к документу.")


@pytest.mark.parametrize("reply", [(500, "Internal Server Error"), (502, {"error": {"code": "teapot"}}), (503, ["не объект"])])
def test_broken_search_answer_is_unavailable(tools, backend, reply):
    backend.search = reply
    with pytest.raises(ToolError) as error:
        tools.search("отгул")
    assert error.value.code == "unavailable" and error.value.message


def test_unreachable_services_are_unavailable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{s.getsockname()[1]}"
    tools = Tools(knowledge_url=dead, mcp_url=f"{dead}/mcp", token="t", request_id="rq-dead-001", timeout=1)
    for call in (lambda: tools.search("отгул"), lambda: tools.mcp("directory_get_me")):
        with pytest.raises(ToolError) as error:
            call()
        assert error.value.code == "unavailable"
    assert [step["ok"] for step in tools.trace] == [False, False]


def test_slow_tool_times_out(tools, backend):
    tools.timeout = 0.3
    backend.delay = 1.0
    with pytest.raises(ToolError) as error:
        tools.mcp("directory_find_contact", {"topic": "onboarding"})
    assert error.value.code == "unavailable"


def test_tools_from_env(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_URL", "http://kb:8060/")
    monkeypatch.setenv("MCP_URL", "http://corp:8070/mcp")
    monkeypatch.setenv("TOOL_TIMEOUT_SECONDS", "7")
    tools = tools_from_env("tok", "rq-env-0001")
    assert (tools.knowledge_url, tools.mcp_url, tools.timeout, tools.token) == ("http://kb:8060", "http://corp:8070/mcp", 7.0, "tok")
