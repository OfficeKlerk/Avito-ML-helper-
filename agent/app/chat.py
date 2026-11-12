"""Ответ на сообщение без LLM: собирает контекст (A2), распознаёт запрос (A3), формирует ответ по контракту B."""

from __future__ import annotations

from datetime import date
from typing import Any

from .context import Context, build_context
from .intents import Understanding, understand

KIND_WORD = {"day_off": "отгул", "vacation": "отпуск"}
ASK_DATE_SUGGESTIONS = ["Завтра", "В пятницу"]


def answer(body: dict[str, Any]) -> dict[str, Any]:
    ctx = build_context(body)
    nlu = understand(body["message"], ctx.today, body["state"])
    if nlu.intent == "next_steps":
        return next_steps(ctx)
    if nlu.intent == "absence":
        return absence(ctx, nlu)
    return response(
        "Пока я умею подсказать следующие шаги адаптации и помочь оформить отгул или отпуск. "
        "Спроси, например: «Что мне делать дальше?»",
        suggestions=["Что мне делать дальше?", "Как оформить отгул?"],
    )


def next_steps(ctx: Context) -> dict[str, Any]:
    if not ctx.next_steps:
        return response("Все ближайшие задачи адаптации выполнены. Когда появятся новые, я подскажу.",
                        suggestions=["Как оформить отгул?"])
    week = f"Сейчас у тебя {ctx.week}-я неделя стажировки. " if ctx.week else ""
    steps = "\n".join(f"{i}. **{s['title']}** — {s['reason']}" for i, s in enumerate(ctx.next_steps, 1))
    return response(f"{week}Вот что стоит сделать в первую очередь:\n\n{steps}",
                    suggestions=["Как оформить отгул?"])


def absence(ctx: Context, nlu: Understanding) -> dict[str, Any]:
    word = KIND_WORD[nlu.kind]
    asking = {"intent": "absence_request", "kind": nlu.kind}
    if nlu.date_from is None:
        question = (f"Эта дата уже прошла. На какой день оформить {word}?" if nlu.past
                    else f"Помогу оформить {word}. На какую дату он нужен?")
        return response(f"{question} Если дней несколько, напиши первый и последний.",
                        missing_fields=["date_from", "date_to"], state=asking, suggestions=ASK_DATE_SUGGESTIONS)
    warn = [name for name in (ctx.mentor, ctx.manager) if name]
    reminder = f" Не забудь заранее предупредить: {', '.join(warn)}." if warn else ""
    # Черновик создаёт инструмент corp-mock (A4). Пока его нет — честно говорим, что заявки нет.
    return response(
        f"Понял: {word} {period(nlu.date_from, nlu.date_to)}. Создать черновик заявки сейчас не получилось — "
        f"сервис заявок недоступен. Попробуй ещё раз чуть позже.{reminder}",
        status="degraded",
        state={**asking, "date_from": nlu.date_from.isoformat(), "date_to": nlu.date_to.isoformat()},
    )


def period(start: date, end: date) -> str:
    return f"на {start:%d.%m.%Y}" if start == end else f"с {start:%d.%m.%Y} по {end:%d.%m.%Y}"


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
