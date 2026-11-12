"""A6: режим с моделью и откат на правила. Модель — сценарий заранее заданных ответов."""

import copy
import json

import pytest
from conftest import FIXTURES_DIR, FakeTools, default_responses

from app import contract, create_app
from app.chat import answer
from app.llm import LlmError
from app.llm_agent import tool_definitions
from app.tools import ToolError

CHAT = json.loads((FIXTURES_DIR / "b_agent" / "chat.json").read_text(encoding="utf-8"))


class ScriptedModel:
    """Отвечает по очереди элементами `script`; исключение в сценарии — сбой модели."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[tuple[list, list | None]] = []

    def complete(self, messages, tools, timeout):
        self.requests.append((copy.deepcopy(messages), tools))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def say(text):
    return {"role": "assistant", "content": text}


def call(*calls):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}
        for i, (name, args) in enumerate(calls)]}


DRAFT_ARGS = {"kind": "day_off", "date_from": "2026-11-13", "date_to": "2026-11-13"}


@pytest.fixture()
def body():
    return copy.deepcopy(CHAT["cases"][0]["request"]["body"])


@pytest.fixture()
def tools():
    return FakeTools(default_responses(), token="user-secret-jwt", request_id="rq-llm-0001")


def run(body, tools, model, **kw):
    result = answer(body, tools, model, **kw)
    assert contract.errors(result, "ChatResponse") == []
    return result


def tool_results(model, round_index):
    return [json.loads(m["content"]) for m in model.requests[round_index][0] if m["role"] == "tool"]


def test_tool_definitions_come_from_contracts():
    definitions = {d["function"]["name"]: d["function"] for d in tool_definitions()}
    assert set(definitions) == {"knowledge_search", "directory_find_contact", "absence_get_rules", "absence_create_draft"}
    draft = definitions["absence_create_draft"]["parameters"]
    assert "idempotency_key" not in draft["properties"] and draft["required"] == ["kind", "date_from", "date_to"]
    assert draft["properties"]["kind"]["enum"] == ["day_off", "vacation"]
    assert "$ref" not in json.dumps(definitions)
    assert definitions["knowledge_search"]["parameters"]["required"] == ["query"]


def test_plain_answer(body, tools):
    model = ScriptedModel(say("Сначала попроси добавить тебя в каналы команды."))
    result = run(body, tools, model)
    assert result["text"] == "Сначала попроси добавить тебя в каналы команды." and result["status"] == "ok"
    assert [s["tool"] for s in result["trace"]] == ["llm"]
    messages, offered = model.requests[0]
    assert messages[0]["role"] == "system" and "AI-buddy" in messages[0]["content"]
    assert "Анна Соколова" in messages[1]["content"] and messages[-1] == {"role": "user", "content": body["message"]}
    assert len(offered) == 4


def test_token_never_reaches_the_model(body, tools):
    body["history"] = [{"role": "user", "text": "Привет"}, {"role": "assistant", "text": "Привет! Чем помочь?"}]
    model = ScriptedModel(call(("knowledge_search", {"query": "отгул"})), say("Готово."))
    run(body, tools, model)
    sent = json.dumps([m for m, _ in model.requests], ensure_ascii=False)
    assert "user-secret-jwt" not in sent and "Привет! Чем помочь?" in sent


def test_search_gives_sources(body, tools):
    model = ScriptedModel(call(("knowledge_search", {"query": "как оформить отгул"})), say("Отгул оформляется так: ..."))
    result = run(body, tools, model)
    assert [s["chunk_id"] for s in result["sources"]] == ["kb_absence_rules#day-off", "kb_absence_rules#vacation"]
    (found,) = tool_results(model, 1)
    assert found["results"][0]["text"].startswith("Отгул — это")


def test_model_creates_draft_with_agent_idempotency_key(body, tools):
    model = ScriptedModel(call(("absence_create_draft", DRAFT_ARGS)), say("Черновик готов, подтверди его в карточке."))
    result = run(body, tools, model)
    key = f"{body['request_id']}:absence_create_draft"
    assert tools.calls == [("absence_create_draft", {**DRAFT_ARGS, "idempotency_key": key})]
    assert result["proposed_actions"] == [{
        "type": "absence_request", "title": "Отгул 13.11.2026", "external_id": "req_anna_dayoff_1",
        "fields": {"Тип": "Отгул", "Даты": "13.11.2026", "Согласует": "Ольга Крылова"}}]
    assert result["text"] == "Черновик готов, подтверди его в карточке."


def test_bad_arguments_are_returned_to_model(body, tools):
    model = ScriptedModel(
        call(("absence_create_draft", {"kind": "holiday", "date_from": "13.11"}), ("knowledge_search", "не json"),
             ("knowledge_search", "[1]"), ("send_request", {})),
        say("Уточни, пожалуйста, даты."))
    result = run(body, tools, model)
    codes = [r["error"]["code"] for r in tool_results(model, 1)]
    assert codes == ["validation", "validation", "validation", "not_found"]
    assert tools.calls == [] and result["proposed_actions"] == []


def test_tool_error_goes_to_model(body, tools):
    tools.responses["absence_create_draft"] = ToolError("forbidden", "Оформить отсутствие может только сотрудник команды.")
    model = ScriptedModel(call(("absence_create_draft", DRAFT_ARGS)), say("Тебе нельзя оформить отсутствие."))
    result = run(body, tools, model)
    assert tool_results(model, 1) == [{"error": {"code": "forbidden", "message": "Оформить отсутствие может только сотрудник команды."}}]
    assert result["proposed_actions"] == [] and result["status"] == "ok"


def test_contact_becomes_escalation(body, tools):
    tools.responses["absence_get_rules"] = {"rules": [], "disclaimer": "тест"}
    model = ScriptedModel(call(("directory_find_contact", {"topic": "absence"}), ("absence_get_rules", {})),
                          say("Напиши Ольге Крыловой."))
    result = run(body, tools, model)
    assert result["escalation"]["needed"] is True and result["escalation"]["contact"]["name"] == "Ольга Крылова"


def test_tool_call_limit(body, tools):
    model = ScriptedModel(
        call(("knowledge_search", {"query": "отгул"}), ("knowledge_search", {"query": "отпуск"})),
        say("Вот что я нашёл."))
    result = run(body, tools, model, max_tool_calls=1)
    assert [r.get("error", {}).get("code") for r in tool_results(model, 1)] == [None, "rate_limited"]
    assert model.requests[1][1] is None  # предел исчерпан — инструменты больше не предлагаются
    assert result["text"] == "Вот что я нашёл."
    assert tools.calls == [("knowledge_search", {"query": "отгул", "top_k": 3})]  # второй поиск не выполнен


def test_model_ignoring_limit_without_text_falls_back(body, tools):
    model = ScriptedModel(call(("knowledge_search", {"query": "отгул"})), call(("knowledge_search", {"query": "ещё"})))
    result = run(body, tools, model, max_tool_calls=1)
    assert result["status"] == "degraded" and result["text"].startswith("Сейчас у тебя 1-я неделя")


@pytest.mark.parametrize("failure", [LlmError("модель недоступна"), say("   ")])
def test_model_failure_falls_back_to_rules(body, tools, failure):
    model = ScriptedModel(failure)
    result = run(body, tools, model)
    assert result["status"] == "degraded" and result["text"].startswith("Сейчас у тебя 1-я неделя")
    assert {"tool": "llm", "ok": False} == {k: result["trace"][-1][k] for k in ("tool", "ok")}


def test_timeout_falls_back_without_calling_model(body, tools):
    model = ScriptedModel()
    result = run(body, tools, model, timeout=0)
    assert model.requests == [] and result["status"] == "degraded"


def test_draft_survives_model_failure_without_second_call(body, tools):
    body["message"] = "Хочу взять отгул в пятницу"
    model = ScriptedModel(call(("absence_create_draft", DRAFT_ARGS)), LlmError("упала"))
    result = run(body, tools, model)
    # правила взяли черновик из этого запроса, а не создали второй
    assert [name for name, _ in tools.calls if name == "absence_create_draft"] == ["absence_create_draft"]
    assert [a["external_id"] for a in result["proposed_actions"]] == ["req_anna_dayoff_1"]
    assert result["status"] == "degraded" and "Я подготовил черновик" in result["text"]


def test_draft_survives_when_rules_do_not_understand(body, tools):
    body["message"] = "Оформи мне свободный денёк в пятницу"
    model = ScriptedModel(call(("absence_create_draft", DRAFT_ARGS)), LlmError("упала"))
    result = run(body, tools, model)
    assert [a["external_id"] for a in result["proposed_actions"]] == ["req_anna_dayoff_1"]
    assert result["text"].endswith("в карточке. Проверь его и подтверди.")
    assert [name for name, _ in tools.calls] == ["absence_create_draft", "directory_find_contact"]


def test_http_with_model(body):
    model = ScriptedModel(call(("absence_create_draft", DRAFT_ARGS)), say("Черновик готов."))
    client = create_app(lambda token, request_id: FakeTools(default_responses(), token, request_id), lambda: model).test_client()
    response = client.post("/v1/chat", json=body, headers={"Authorization": "Bearer t"})
    data = response.get_json()
    assert response.status_code == 200 and contract.errors(data, "ChatResponse") == []
    assert data["text"] == "Черновик готов." and data["proposed_actions"][0]["external_id"] == "req_anna_dayoff_1"
