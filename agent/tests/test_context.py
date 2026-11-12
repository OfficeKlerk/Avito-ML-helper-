"""A2: контекст пользователя."""

import copy
import json
import os
from datetime import date
from pathlib import Path

import pytest

from app.context import InvalidRequest, build_context, to_prompt

FIXTURES_DIR = Path(os.environ.get("FIXTURES_DIR") or Path(__file__).resolve().parents[2] / "fixtures")


@pytest.fixture()
def body():
    chat = json.loads((FIXTURES_DIR / "b_agent" / "chat.json").read_text(encoding="utf-8"))
    return copy.deepcopy(chat["cases"][0]["request"]["body"])


def test_context_from_request(body):
    ctx = build_context(body)
    assert (ctx.name, ctx.role, ctx.team_name, ctx.week) == ("Анна Соколова", "intern", "Авито Доставка", 1)
    assert (ctx.mentor, ctx.manager) == ("Игорь Белов", "Ольга Крылова")
    assert ctx.today == date(2026, 11, 11)
    assert [s["task_id"] for s in ctx.next_steps] == ["t_join_channels", "t_request_accesses", "t_team_space"]


def test_today_is_in_user_timezone(body):
    body["now"] = "2026-11-11T22:30:00Z"
    assert build_context(body).today == date(2026, 11, 12)
    body["timezone"] = "UTC"
    assert build_context(body).today == date(2026, 11, 11)


def test_overdue_tasks(body):
    body["onboarding"]["tasks"] = [
        {"id": "t_a", "stage_id": "st_week1", "title": "Просрочена", "status": "todo", "due_date": "2026-11-10"},
        {"id": "t_b", "stage_id": "st_week1", "title": "Сделана давно", "status": "done", "due_date": "2026-11-01"},
        {"id": "t_c", "stage_id": "st_week1", "title": "Срок сегодня", "status": "in_progress", "due_date": "2026-11-11"},
        {"id": "t_d", "stage_id": "st_week1", "title": "Без срока", "status": "todo", "due_date": None},
    ]
    ctx = build_context(body)
    assert [t["id"] for t in ctx.overdue] == ["t_a"]
    assert [t["id"] for t in ctx.open_tasks] == ["t_a", "t_c", "t_d"]


def test_unknown_timezone(body):
    for tz in ("Mars/Base", "../etc/passwd"):
        body["timezone"] = tz
        with pytest.raises(InvalidRequest):
            build_context(body)


def test_prompt_has_context_and_no_token(body):
    body["onboarding"]["tasks"][0]["due_date"] = "2026-11-01"
    prompt = to_prompt(build_context(body))
    for expected in ("Анна Соколова", "Авито Доставка", "Неделя стажировки: 1", "Игорь Белов", "2026-11-11 10:00",
                     "среда", "Europe/Moscow", "Просрочены:", "Следующие шаги:"):
        assert expected in prompt, expected
    assert "Bearer" not in prompt and "jwt" not in prompt.lower()


def test_prompt_for_user_without_team(body):
    body["user"].update(team_id=None, team_name=None, internship_week=None, mentor=None, manager=None, role="hr")
    body["onboarding"] = {"progress": 0, "tasks": [], "next_steps": []}
    prompt = to_prompt(build_context(body))
    assert "команда: нет" in prompt and "Наставник: нет" in prompt and "Следующие шаги" not in prompt
