"""Ответ на сообщение: с моделью (A6) или по правилам (A3–A5), в формате контракта B."""

from __future__ import annotations

from typing import Any

from .context import Context, build_context
from .intents import Understanding, understand
from .llm import ChatModel, LlmError
from .llm_agent import answer_with_model
from .reply import KIND_WORD, draft_action, period, response
from .tools import Tools, ToolError

ASK_DATE_SUGGESTIONS = ["Завтра", "В пятницу"]


def answer(body: dict[str, Any], tools: Tools, model: ChatModel | None = None,
           max_tool_calls: int = 5, timeout: float = 25.0) -> dict[str, Any]:
    ctx = build_context(body)
    result = None
    if model is not None:
        try:
            result = answer_with_model(body, ctx, tools, model, max_tool_calls, timeout)
        except ToolError:
            pass  # модель не ответила — неудачный шаг llm уже в trace
        except LlmError:
            tools.trace.append({"tool": "llm", "ok": False, "ms": 0, "error_code": "unavailable"})
    fell_back = result is None and model is not None
    if result is None:
        result = answer_by_rules(body, ctx, tools)
    # Черновики, созданные в этом запросе, всегда видны пользователю — даже если модель упала после создания.
    shown = {action["external_id"] for action in result["proposed_actions"]}
    missed = [draft_action(d) for d in tools.drafts.values() if d["id"] not in shown]
    if missed:
        result["proposed_actions"] += missed
        if fell_back:
            result["text"] += "\n\nЧерновик заявки, который я успел подготовить, — в карточке. Проверь его и подтверди."
    result["trace"] = tools.trace
    # Отказ по правам или неверные даты — нормальный ответ. Упрощённый режим — только когда сервис не ответил.
    if any(step["error_code"] == "unavailable" for step in tools.trace):
        result["status"] = "degraded"
    return result


def answer_by_rules(body: dict[str, Any], ctx: Context, tools: Tools) -> dict[str, Any]:
    nlu = understand(body["message"], ctx.today, body["state"])
    if nlu.intent == "next_steps":
        return next_steps(ctx)
    if nlu.intent == "absence":
        return absence(ctx, nlu, tools, body["request_id"])
    return unknown(tools)


def next_steps(ctx: Context) -> dict[str, Any]:
    if not ctx.next_steps:
        return response("Все ближайшие задачи адаптации выполнены. Когда появятся новые, я подскажу.",
                        suggestions=["Как оформить отгул?"])
    week = f"Сейчас у тебя {ctx.week}-я неделя стажировки. " if ctx.week else ""
    steps = "\n".join(f"{i}. **{s['title']}** — {s['reason']}" for i, s in enumerate(ctx.next_steps, 1))
    return response(f"{week}Вот что стоит сделать в первую очередь:\n\n{steps}",
                    suggestions=["Как оформить отгул?"])


def absence(ctx: Context, nlu: Understanding, tools: Tools, request_id: str) -> dict[str, Any]:
    word = KIND_WORD[nlu.kind]
    asking = {"intent": "absence_request", "kind": nlu.kind}
    sources = find_sources(tools, f"как оформить {word}")
    if nlu.date_from is None:
        question = (f"Эта дата уже прошла. На какой день оформить {word}?" if nlu.past
                    else f"Помогу оформить {word}. На какую дату он нужен?")
        return ask_date(question, asking, sources)

    dates = period(nlu.date_from, nlu.date_to)
    try:
        draft = tools.mcp("absence_create_draft", {
            "kind": nlu.kind,
            "date_from": nlu.date_from.isoformat(),
            "date_to": nlu.date_to.isoformat(),
            "idempotency_key": f"{request_id}:absence_create_draft",
        })
    except ToolError as exc:
        if exc.code == "validation":
            return ask_date(f"{exc.message} На какую дату оформить {word}?", asking, sources)
        if exc.code == "unavailable":
            return response(f"Понял: {word} {dates}. Создать черновик заявки сейчас не получилось — сервис заявок "
                            "недоступен. Попробуй ещё раз чуть позже.", sources=sources,
                            state={**asking, "date_from": nlu.date_from.isoformat(), "date_to": nlu.date_to.isoformat()})
        return response(exc.message, sources=sources)

    action = draft_action(draft)
    warn = [name for name in (ctx.mentor, ctx.manager) if name]
    reminder = f" И не забудь заранее предупредить: {', '.join(warn)}." if warn else ""
    return response(
        f"Я подготовил черновик заявки: {word} {dates}. Проверь его и подтверди — только тогда заявка уйдёт "
        f"на согласование ({action['fields']['Согласует']}).{reminder}",
        sources=sources, proposed_actions=[action], suggestions=["Что ещё сделать на этой неделе?"],
    )


def unknown(tools: Tools) -> dict[str, Any]:
    text = "Пока я умею подсказать следующие шаги адаптации и помочь оформить отгул или отпуск."
    contact = None
    try:
        contacts = tools.mcp("directory_find_contact", {"topic": "onboarding"})["contacts"]
    except (ToolError, KeyError):
        contacts = []
    if contacts:
        c = contacts[0]
        contact = {"id": c.get("id"), "name": c["name"], "role_title": c["role_title"], "channel": c.get("channel")}
        where = f", {c['channel']}" if c.get("channel") else ""
        text += f" С другими вопросами лучше к человеку: {c['name']} ({c['role_title'].lower()}{where})."
    return response(text, suggestions=["Что мне делать дальше?", "Как оформить отгул?"],
                    escalation={"needed": contact is not None, "contact": contact})


def find_sources(tools: Tools, query: str) -> list[dict[str, Any]]:
    """Источники ровно такие, какие вернул поиск: без повторов, ничего не добавляем от себя."""
    try:
        chunks = tools.search(query)
    except ToolError:
        return []
    seen, sources = set(), []
    for chunk in chunks:
        source = chunk["source"]
        if source["chunk_id"] not in seen:
            seen.add(source["chunk_id"])
            sources.append(source)
    return sources


def ask_date(question: str, state: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    return response(f"{question} Если дней несколько, напиши первый и последний.", sources=sources,
                    missing_fields=["date_from", "date_to"], state=state, suggestions=ASK_DATE_SUGGESTIONS)
