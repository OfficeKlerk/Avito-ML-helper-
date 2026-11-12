"""Общий формат ответа агента (контракт B) для режима с моделью и без неё."""

from __future__ import annotations

from datetime import date
from typing import Any

KIND_WORD = {"day_off": "отгул", "vacation": "отпуск"}
KIND_TITLE = {"day_off": "Отгул", "vacation": "Отпуск"}
SYSTEM_TITLE = {"confluence": "Confluence", "jira": "Jira", "gitlab": "GitLab", "vpn": "VPN", "team_space": "Пространство команды"}


def response(text: str, **fields: Any) -> dict[str, Any]:
    return {
        "text": text,
        "sources": [],
        "proposed_actions": [],
        "task_updates": [],
        "suggestions": [],
        "missing_fields": [],
        "escalation": {"needed": False, "contact": None},
        "state": None,
        "status": "ok",
        "trace": [],
        **fields,
    }


def period(start: date, end: date) -> str:
    return f"на {start:%d.%m.%Y}" if start == end else f"с {start:%d.%m.%Y} по {end:%d.%m.%Y}"


def draft_action(draft: dict[str, Any]) -> dict[str, Any]:
    """Карточка черновика по тому, что corp-mock действительно сохранил."""
    payload = draft["payload"]
    approver = (draft.get("approver") or {}).get("name") or "руководитель команды"
    if draft.get("type") == "access_request":
        system = SYSTEM_TITLE.get(payload["system"], payload["system"])
        return {
            "type": "access_request",
            "title": draft.get("summary") or f"Доступ к {system}",
            "external_id": draft["id"],
            "fields": {"Система": system, "Зачем": payload["reason"], "Согласует": approver},
        }
    kind = payload["kind"]
    dates = period(date.fromisoformat(payload["date_from"]), date.fromisoformat(payload["date_to"]))
    return {
        "type": "absence_request",
        "title": draft.get("summary") or f"{KIND_TITLE[kind]} {dates}",
        "external_id": draft["id"],
        "fields": {"Тип": KIND_TITLE[kind], "Даты": dates.removeprefix("на "), "Согласует": approver},
    }
