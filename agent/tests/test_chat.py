"""A1, A3 и A5 через HTTP: каждый ответ проверяется по схеме контракта B."""

import copy
import json

import pytest
from conftest import FIXTURES_DIR

from app import contract
from app.tools import ToolError

CHAT = json.loads((FIXTURES_DIR / "b_agent" / "chat.json").read_text(encoding="utf-8"))
AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture()
def body():
    return copy.deepcopy(CHAT["cases"][0]["request"]["body"])


def post(client, body, headers=AUTH):
    response = client.post("/v1/chat", json=body, headers=headers)
    payload = response.get_json()
    if response.status_code == 200:
        assert contract.errors(payload, "ChatResponse") == []
    else:
        assert payload["error"]["code"] and payload["error"]["message"]
    return response.status_code, payload


@pytest.mark.parametrize("case", CHAT["cases"], ids=lambda c: c["name"])
def test_contract_examples(client, case):
    """Запросы из примеров контракта: агент отвечает по схеме. Кейсы недоступности агент сам не воспроизводит."""
    status, _ = post(client, case["request"]["body"], case["request"]["headers"])
    expected = {"forbidden": 401, "validation": 422}.get(case["kind"], 200)
    assert status == expected


def test_next_steps(client, body):
    _, data = post(client, body)
    assert data["status"] == "ok" and data["state"] is None
    text = data["text"]
    assert text.startswith("Сейчас у тебя 1-я неделя")
    order = [text.index(s["title"]) for s in body["onboarding"]["next_steps"]]
    assert order == sorted(order)
    assert all(s["reason"] in text for s in body["onboarding"]["next_steps"])


def test_next_steps_when_all_done(client, body):
    body["onboarding"]["next_steps"] = []
    body["user"]["internship_week"] = None
    _, data = post(client, body)
    assert data["text"].startswith("Все ближайшие задачи")


def test_absence_dialogue(client, body, made_tools):
    body["message"] = "Как оформить отгул?"
    _, first = post(client, body)
    assert first["missing_fields"] == ["date_from", "date_to"]
    assert first["state"] == {"intent": "absence_request", "kind": "day_off"}
    assert "На какую дату" in first["text"]
    assert [s["chunk_id"] for s in first["sources"]] == ["kb_absence_rules#day-off", "kb_absence_rules#vacation"]

    body.update(message="в пятницу", state=first["state"], history=[
        {"role": "user", "text": "Как оформить отгул?"}, {"role": "assistant", "text": first["text"]}])
    _, second = post(client, body)
    assert second["status"] == "ok" and second["state"] is None
    assert second["proposed_actions"] == [{
        "type": "absence_request", "title": "Отгул 13.11.2026", "external_id": "req_anna_dayoff_1",
        "fields": {"Тип": "Отгул", "Даты": "13.11.2026", "Согласует": "Ольга Крылова"},
    }]
    assert "подтверди" in second["text"] and "Игорь Белов" in second["text"]
    assert [step["tool"] for step in second["trace"]] == ["knowledge_search", "absence_create_draft"]
    draft_call = made_tools[-1].calls[-1]
    assert draft_call == ("absence_create_draft", {
        "kind": "day_off", "date_from": "2026-11-13", "date_to": "2026-11-13",
        "idempotency_key": f"{body['request_id']}:absence_create_draft"})


def test_vacation_range(client, body):
    body["message"] = "Хочу в отпуск с 28 по 31 декабря"
    _, data = post(client, body)
    assert "отпуск с 28.12.2026 по 31.12.2026" in data["text"]
    assert data["proposed_actions"][0]["fields"]["Даты"] == "с 28.12.2026 по 31.12.2026"


def test_absence_past_date(client, body):
    body["message"] = "Отгул на 02.11.2026"
    _, data = post(client, body)
    assert data["text"].startswith("Эта дата уже прошла") and data["missing_fields"] == ["date_from", "date_to"]


def test_absence_without_mentor_and_manager(client, body):
    body["message"] = "отгул завтра"
    body["user"].update(mentor=None, manager=None)
    _, data = post(client, body)
    assert "предупредить" not in data["text"]


def test_unknown_question_gives_contact(client, body, tools_responses):
    tools_responses["knowledge_search"] = []
    body["message"] = "Где у нас парковка?"
    _, data = post(client, body)
    assert data["status"] == "ok" and "Что мне делать дальше?" in data["suggestions"]
    assert data["escalation"] == {"needed": True, "contact": {
        "id": "u_olga", "name": "Ольга Крылова", "role_title": "Руководитель команды, согласует отгулы и отпуска",
        "channel": "личные сообщения"}}
    assert "Ольга Крылова" in data["text"]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}])
def test_requires_bearer_token(client, body, headers):
    assert post(client, body, headers)[0] == 401


def test_rejects_not_json(client):
    response = client.post("/v1/chat", data="не json", headers={**AUTH, "Content-Type": "application/json"})
    assert response.status_code == 422 and response.get_json()["error"]["code"] == "validation"


@pytest.mark.parametrize("change", [
    lambda b: b.pop("now"),
    lambda b: b.update(message=""),
    lambda b: b.update(now="вчера"),
    lambda b: b["user"].update(role="admin"),
    lambda b: b.update(extra=1),
])
def test_rejects_requests_outside_contract(client, body, change):
    change(body)
    assert post(client, body)[0] == 422


def test_unknown_timezone_is_validation_error(client, body):
    body["timezone"] = "Mars/Base"
    status, data = post(client, body)
    assert status == 422 and data["error"]["message"] == "Неизвестный часовой пояс."


def test_draft_rejected_by_corp_asks_again(client, body, tools_responses):
    tools_responses["absence_create_draft"] = ToolError("validation", "Отгул можно взять не больше чем на 2 дня.")
    body["message"] = "отгул с 13 по 20 ноября"
    _, data = post(client, body)
    assert data["text"].startswith("Отгул можно взять не больше чем на 2 дня. На какую дату")
    assert data["proposed_actions"] == [] and data["missing_fields"] == ["date_from", "date_to"]
    assert data["status"] == "ok" and data["trace"][-1]["error_code"] == "validation"


def test_draft_forbidden_ends_dialogue(client, body, tools_responses):
    tools_responses["absence_create_draft"] = ToolError("forbidden", "Оформить отсутствие может только сотрудник команды.")
    body["message"] = "отгул завтра"
    _, data = post(client, body)
    assert data["text"] == "Оформить отсутствие может только сотрудник команды."
    assert data["proposed_actions"] == [] and data["state"] is None and data["status"] == "ok"


def test_draft_unavailable_is_degraded_and_keeps_dates(client, body, tools_responses):
    tools_responses["absence_create_draft"] = ToolError("unavailable", "Сервис временно недоступен.")
    body["message"] = "Хочу взять отгул в пятницу"
    _, data = post(client, body)
    assert data["status"] == "degraded" and data["proposed_actions"] == []
    assert "не получилось" in data["text"] and "подтверди" not in data["text"]
    assert data["state"] == {"intent": "absence_request", "kind": "day_off", "date_from": "2026-11-13", "date_to": "2026-11-13"}


def test_search_unavailable_still_creates_draft(client, body, tools_responses):
    tools_responses["knowledge_search"] = ToolError("unavailable", "Сервис временно недоступен.")
    body["message"] = "Хочу взять отгул в пятницу"
    _, data = post(client, body)
    assert data["status"] == "degraded" and data["sources"] == []
    assert data["proposed_actions"][0]["external_id"] == "req_anna_dayoff_1"


def test_sources_are_deduplicated(client, body, tools_responses):
    results = tools_responses["knowledge_search"]
    tools_responses["knowledge_search"] = results + results
    body["message"] = "как оформить отгул"
    _, data = post(client, body)
    assert len(data["sources"]) == len(results)


def test_draft_without_approver_and_summary(client, body, tools_responses):
    tools_responses["absence_create_draft"].update(approver=None, summary="")
    body["message"] = "Хочу в отпуск 1 декабря"
    _, data = post(client, body)
    action = data["proposed_actions"][0]
    assert action["title"] == "Отпуск на 01.12.2026" and action["fields"]["Согласует"] == "руководитель команды"


def test_unknown_question_without_contact(client, body, tools_responses):
    tools_responses["knowledge_search"] = []
    tools_responses["directory_find_contact"] = ToolError("unavailable", "Сервис временно недоступен.")
    body["message"] = "Где у нас парковка?"
    _, data = post(client, body)
    assert data["status"] == "degraded" and data["escalation"] == {"needed": False, "contact": None}
    tools_responses["directory_find_contact"] = {"topic": "onboarding", "contacts": [
        {"id": None, "name": "Куратор", "role_title": "Куратор стажировки", "channel": None}]}
    _, data = post(client, body)
    assert data["status"] == "ok" and data["escalation"]["contact"]["name"] == "Куратор"


def test_tools_get_user_token_and_request_id(client, body, made_tools):
    post(client, body, {"Authorization": "Bearer user-jwt"})
    assert (made_tools[-1].token, made_tools[-1].request_id) == ("user-jwt", body["request_id"])
