import asyncio
import dataclasses

import pytest
from mcp import Client
from starlette.testclient import TestClient

from devkit import smoke, stub_server
from devkit.contracts import Contracts, load_operations
from devkit.stub_server import build_mcp_server, build_state, create_app

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
DRAFT_ARGS = {"kind": "day_off", "date_from": "2026-11-13", "date_to": "2026-11-13", "idempotency_key": "rq-1:draft"}


@pytest.fixture()
def corp():
    state = build_state("corp-mock", ["C", "D"])
    with TestClient(create_app(state)) as client:
        yield client, state


@pytest.fixture()
def agent():
    state = build_state("agent", ["B"])
    with TestClient(create_app(state)) as client:
        yield client, state


def call_tool(client, name, arguments, headers=None):
    response = client.post(
        "/mcp",
        headers={**MCP_HEADERS, **(headers or {})},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
    )
    assert response.status_code == 200
    return response.json()["result"]


def test_health_names_the_service(corp):
    client, _ = corp
    assert client.get("/health").json() == {"status": "ok", "service": "corp-mock", "version": "stub"}


def test_default_success_and_match_by_path(corp):
    client, _ = corp
    ok = client.post("/api/v1/requests/req_anna_dayoff_1/submit")
    assert (ok.status_code, ok.headers["x-stub-case"], ok.json()["status"]) == (200, "submitted", "submitted")
    foreign = client.post("/api/v1/requests/req_max_vacation_1/submit")
    assert (foreign.status_code, foreign.json()["error"]["code"]) == (403, "forbidden")


def test_match_by_body(agent):
    client, _ = agent
    request = next(op for op in load_operations() if op.contract == "B" and op.operation == "chat").cases[0].request["body"]
    draft = client.post("/v1/chat", json={**request, "message": "Хочу отгул в пятницу"})
    assert draft.json()["proposed_actions"][0]["external_id"] == "req_anna_dayoff_1"
    plain = client.post("/v1/chat", json=request)
    assert plain.headers["x-stub-case"] == "next_steps" and plain.json()["proposed_actions"] == []


def test_header_selects_case_by_name_or_kind(corp):
    client, _ = corp
    by_name = client.post("/api/v1/requests/req_anna_dayoff_1/submit", headers={"X-Stub-Case": "already_cancelled"})
    assert by_name.status_code == 409
    by_kind = client.get("/api/v1/requests/req_anna_dayoff_1", headers={"X-Stub-Case": "unavailable"})
    assert (by_kind.status_code, by_kind.headers["x-stub-case"]) == (503, "unavailable")


def test_generic_error_when_operation_has_no_such_case(corp):
    client, _ = corp
    response = client.post("/api/v1/requests/req_anna_dayoff_1/cancel", headers={"X-Stub-Case": "unavailable"})
    assert (response.status_code, response.headers["x-stub-case"]) == (503, "generic_unavailable")
    assert response.json()["error"]["code"] == "unavailable"


def test_forced_case_applies_to_all_operations_and_resets(corp):
    client, state = corp
    assert client.post("/__stub/case", json={"case": "forbidden"}).json() == {"forced_case": "forbidden"}
    assert client.get("/api/v1/requests/req_anna_dayoff_1").status_code == 403
    assert client.post("/api/v1/requests/req_anna_dayoff_1/cancel").status_code == 403
    assert client.get("/health").status_code == 200
    client.post("/__stub/case", json={"case": None})
    assert state.forced_case is None
    assert client.get("/api/v1/requests/req_anna_dayoff_1").status_code == 200


def test_case_name_of_another_operation_is_ignored(corp):
    client, _ = corp
    client.post("/__stub/case", json={"case": "already_cancelled"})
    assert client.post("/api/v1/requests/req_anna_dayoff_1/submit").status_code == 409
    assert client.get("/api/v1/requests/req_anna_dayoff_1").status_code == 200


def test_unknown_route_and_introspection(corp):
    client, _ = corp
    missing = client.get("/api/v1/unknown")
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "not_found")
    listing = client.get("/__stub/fixtures").json()
    assert listing["service"] == "corp-mock"
    assert {"request_submit", "absence_create_draft"} <= {op["operation"] for op in listing["operations"]}


def test_calls_are_recorded_and_cleared(corp):
    client, _ = corp
    client.post("/api/v1/requests/req_anna_dayoff_1/submit")
    call_tool(client, "absence_get_rules", {})
    calls = client.get("/__stub/calls").json()["calls"]
    assert [c["operation"] for c in calls] == ["request_submit", "absence_get_rules"]
    assert calls[0]["status"] == 200 and calls[1]["is_error"] is False
    assert client.delete("/__stub/calls").json() == {"calls": []}


def test_mcp_over_http_lists_tools_and_returns_fixture(corp):
    client, _ = corp
    listed = client.post("/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    tools = {tool["name"]: tool for tool in listed.json()["result"]["tools"]}
    assert len(tools) == 7
    assert tools["absence_create_draft"]["inputSchema"]["required"] == ["kind", "date_from", "date_to", "idempotency_key"]
    result = call_tool(client, "absence_create_draft", DRAFT_ARGS)
    assert result["isError"] is False and result["structuredContent"]["status"] == "draft"


def test_mcp_cases_by_header_match_and_generic(corp):
    client, _ = corp
    past = call_tool(client, "absence_create_draft", {**DRAFT_ARGS, "date_from": "2026-11-02", "date_to": "2026-11-02"})
    assert past["isError"] is True and past["structuredContent"]["error"]["code"] == "validation"
    denied = call_tool(client, "absence_create_draft", DRAFT_ARGS, {"X-Stub-Case": "forbidden"})
    assert denied["structuredContent"]["error"]["code"] == "forbidden"
    generic = call_tool(client, "absence_get_rules", {}, {"X-Stub-Case": "unavailable"})
    assert generic["isError"] is True and generic["structuredContent"]["error"]["code"] == "unavailable"


def test_mcp_through_official_client():
    state = build_state("corp-mock", ["C"], forced_case="unavailable")

    async def scenario():
        async with Client(build_mcp_server(state)) as client:
            failed = await client.call_tool("directory_get_me", {})
            state.forced_case = None
            profile = await client.call_tool("directory_get_me", {})
            return failed, profile

    failed, profile = asyncio.run(scenario())
    assert failed.is_error and failed.structured_content["error"]["code"] == "unavailable"
    assert not profile.is_error and profile.structured_content["id"] == "u_anna"


def test_unknown_tool_is_an_error():
    state = build_state("corp-mock", ["C"])
    server = build_mcp_server(state)
    state.operations = [op for op in state.operations if op.tool != "absence_get_rules"]

    async def scenario():
        async with Client(server) as client:
            return await client.call_tool("absence_get_rules", {})

    result = asyncio.run(scenario())
    assert result.is_error and result.structured_content["error"]["code"] == "not_found"


def test_delay_is_applied(corp, monkeypatch):
    client, state = corp
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(stub_server.asyncio, "sleep", fake_sleep)
    state.operations = [
        dataclasses.replace(op, cases=tuple(dataclasses.replace(c, delay_ms=250) for c in op.cases)) for op in state.operations
    ]
    client.get("/api/v1/requests/req_anna_dayoff_1")
    call_tool(client, "absence_get_rules", {})
    assert slept == [0.25, 0.25]


def test_app_from_env(monkeypatch):
    monkeypatch.setenv("STUB_SERVICE", "knowledge-service")
    monkeypatch.setenv("STUB_CONTRACTS", "e")
    monkeypatch.setenv("STUB_CASE", "unavailable")
    with TestClient(stub_server.app_from_env()) as client:
        assert client.get("/health").json()["service"] == "knowledge-service"
        assert client.post("/v1/search", json={"query": "отгул"}).status_code == 503
    with pytest.raises(ValueError):
        build_state("x", ["Q"])


def test_main_starts_uvicorn(monkeypatch):
    started = {}
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setenv("STUB_CONTRACTS", "A")
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: started.update(kwargs))
    stub_server.main()
    assert started["port"] == 8123


# ---------------------------------------------------------------- сквозная проверка на заглушках


def test_smoke_replays_every_fixture(corp, agent):
    contracts, operations = Contracts.load(), load_operations()
    client, _ = corp
    mine = [op for op in operations if op.contract in ("C", "D")]
    assert smoke.check_health(client, "", "corp-mock", contracts) == []
    n_rest, rest_problems = smoke.replay_rest(client, "", mine, contracts)
    n_mcp, mcp_problems = smoke.replay_mcp(client, "", mine, contracts)
    assert (n_rest, rest_problems) == (13, [])
    assert (n_mcp, mcp_problems) == (15, [])

    agent_client, _ = agent
    n_agent, agent_problems = smoke.replay_rest(agent_client, "", [op for op in operations if op.contract == "B"], contracts)
    assert (n_agent, agent_problems) == (11, [])


def test_smoke_detects_wrong_service_and_drift(corp):
    contracts = Contracts.load()
    client, state = corp
    assert smoke.check_health(client, "", "agent", contracts) == ["agent: /health назвался 'corp-mock'"]

    submit = next(op for op in load_operations() if op.operation == "request_submit")
    case = submit.cases[0]
    drifted = dataclasses.replace(case, response={"status": 200, "body": {**case.response["body"], "status": "draft"}})
    wrong_status = dataclasses.replace(case, name="foreign")
    changed = dataclasses.replace(submit, cases=(drifted, wrong_status))
    _, problems = smoke.replay_rest(client, "", [changed], contracts)
    assert any("тело ответа отличается" in p for p in problems)
    assert any("статус 403, ожидался 200" in p for p in problems)

    draft = next(op for op in load_operations() if op.tool == "absence_create_draft")
    flipped = dataclasses.replace(draft.cases[0], response={"is_error": True, "body": {}})
    other = dataclasses.replace(draft.cases[0], name="date_in_past", response={"is_error": True, "body": {"error": {"code": "internal", "message": "x"}}})
    _, problems = smoke.replay_mcp(client, "", [dataclasses.replace(draft, cases=(flipped, other))], contracts)
    assert any("isError не совпал" in p for p in problems)
    assert any("результат отличается" in p for p in problems)


def test_smoke_health_failures(corp):
    contracts = Contracts.load()
    client, _ = corp
    assert smoke.check_health(client, "/api/v1/unknown?x=", "corp-mock", contracts) == ["corp-mock: /health вернул 404"]

    import httpx

    def refuse(request):
        raise httpx.ConnectError("нет соединения", request=request)

    with httpx.Client(transport=httpx.MockTransport(refuse)) as dead:
        assert smoke.check_health(dead, "http://nowhere", "agent", contracts) == ["agent: /health не отвечает (ConnectError)"]


def test_smoke_run_without_addresses(capsys):
    assert smoke.run({}) == 2
    assert "Не задан ни один адрес" in capsys.readouterr().out
