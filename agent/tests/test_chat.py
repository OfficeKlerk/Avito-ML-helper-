"""A1 и сценарии A3 через HTTP: каждый ответ проверяется по схеме контракта B."""

import copy
import json
import os
from pathlib import Path

import pytest

from app import contract, create_app

FIXTURES_DIR = Path(os.environ.get("FIXTURES_DIR") or Path(__file__).resolve().parents[2] / "fixtures")
CHAT = json.loads((FIXTURES_DIR / "b_agent" / "chat.json").read_text(encoding="utf-8"))
AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture()
def client():
    return create_app().test_client()


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


def test_absence_dialogue(client, body):
    body["message"] = "Как оформить отгул?"
    _, first = post(client, body)
    assert first["missing_fields"] == ["date_from", "date_to"]
    assert first["state"] == {"intent": "absence_request", "kind": "day_off"}
    assert "На какую дату" in first["text"]

    body.update(message="в пятницу", state=first["state"], history=[
        {"role": "user", "text": "Как оформить отгул?"}, {"role": "assistant", "text": first["text"]}])
    _, second = post(client, body)
    assert second["status"] == "degraded"
    assert second["proposed_actions"] == []  # черновик не создан — и агент об этом не врёт
    assert "не получилось" in second["text"] and "13.11.2026" in second["text"]
    assert "Игорь Белов" in second["text"] and "Ольга Крылова" in second["text"]
    assert second["state"] == {"intent": "absence_request", "kind": "day_off", "date_from": "2026-11-13", "date_to": "2026-11-13"}


def test_vacation_range(client, body):
    body["message"] = "Хочу в отпуск с 28 по 31 декабря"
    _, data = post(client, body)
    assert "отпуск с 28.12.2026 по 31.12.2026" in data["text"]
    assert data["state"]["kind"] == "vacation"


def test_absence_past_date(client, body):
    body["message"] = "Отгул на 02.11.2026"
    _, data = post(client, body)
    assert data["text"].startswith("Эта дата уже прошла") and data["missing_fields"] == ["date_from", "date_to"]


def test_absence_without_mentor_and_manager(client, body):
    body["message"] = "отгул завтра"
    body["user"].update(mentor=None, manager=None)
    _, data = post(client, body)
    assert "предупредить" not in data["text"]


def test_unknown_question(client, body):
    body["message"] = "Где у нас парковка?"
    _, data = post(client, body)
    assert data["status"] == "ok" and "Что мне делать дальше?" in data["suggestions"]


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
