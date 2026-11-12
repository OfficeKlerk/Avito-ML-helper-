"""Контекст пользователя для ответа (задача A2).

Строится только из тела запроса по контракту B. Заголовки, в том числе токен авторизации,
сюда не передаются — поэтому токен не может попасть в промпт модели.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


class InvalidRequest(ValueError):
    """Запрос прошёл схему, но его значения нельзя использовать."""


@dataclass(frozen=True)
class Context:
    name: str
    role: str
    team_name: str | None
    week: int | None
    mentor: str | None
    manager: str | None
    now: datetime  # в часовом поясе пользователя
    timezone: str
    progress: int
    open_tasks: list[dict[str, Any]]
    overdue: list[dict[str, Any]]
    next_steps: list[dict[str, Any]]

    @property
    def today(self) -> date:
        return self.now.date()


def build_context(body: dict[str, Any]) -> Context:
    try:
        tz = ZoneInfo(body["timezone"])
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidRequest("Неизвестный часовой пояс.") from exc
    now = datetime.fromisoformat(body["now"]).astimezone(tz)
    user, onboarding = body["user"], body["onboarding"]
    open_tasks = [t for t in onboarding["tasks"] if t["status"] != "done"]
    overdue = [t for t in open_tasks if t["due_date"] and date.fromisoformat(t["due_date"]) < now.date()]
    return Context(
        name=user["name"],
        role=user["role"],
        team_name=user["team_name"],
        week=user["internship_week"],
        mentor=(user["mentor"] or {}).get("name"),
        manager=(user["manager"] or {}).get("name"),
        now=now,
        timezone=body["timezone"],
        progress=onboarding["progress"],
        open_tasks=open_tasks,
        overdue=overdue,
        next_steps=onboarding["next_steps"],
    )


def to_prompt(ctx: Context) -> str:
    """Контекст текстом для системного промпта модели (понадобится в A6)."""
    lines = [
        f"Пользователь: {ctx.name}, роль: {ctx.role}, команда: {ctx.team_name or 'нет'}.",
        f"Неделя стажировки: {ctx.week or 'нет'}. Прогресс адаптации: {ctx.progress}%.",
        f"Наставник: {ctx.mentor or 'нет'}. Руководитель: {ctx.manager or 'нет'}.",
        f"Сейчас: {ctx.now:%Y-%m-%d %H:%M}, {WEEKDAYS[ctx.today.weekday()]}, часовой пояс {ctx.timezone}.",
    ]
    if ctx.overdue:
        lines.append("Просрочены: " + "; ".join(f"{t['title']} (срок {t['due_date']})" for t in ctx.overdue) + ".")
    if ctx.open_tasks:
        lines.append("Незавершённые задачи: " + "; ".join(f"{t['title']} ({t['status']})" for t in ctx.open_tasks) + ".")
    if ctx.next_steps:
        lines.append("Следующие шаги: " + "; ".join(f"{s['title']} — {s['reason']}" for s in ctx.next_steps) + ".")
    return "\n".join(lines)
