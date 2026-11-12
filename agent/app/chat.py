"""Ответ на сообщение: с моделью (A6) или по правилам (A3–A5), в формате контракта B."""

from __future__ import annotations

import re
import time
from typing import Any

from .context import Context, build_context
from .intents import Understanding, understand
from .llm import ChatModel, LlmError
from .llm_agent import answer_with_model
from .reply import KIND_WORD, SYSTEM_TITLE, draft_action, looks_like_instructions, period, response
from .tools import Tools, ToolError

ASK_DATE_SUGGESTIONS = ["Завтра", "В пятницу"]
# Утверждения о готовом черновике в двух порядках слов: «черновик … создан» и «подготовил … черновик».
# Отрицание и будущее время («не создан», «будет отправлена», «после того как») утверждением не считаются.
_NOUN = r"(?:черновик|заявк)\w*"
CLAIMED_DRAFT = [
    re.compile(_NOUN + r"\b(?P<gap>(?:[^.!?\n]|(?<=\d)\.(?=\d)){0,60}?)\b(?:создан|подготовлен|отправлен|оформлен|согласован)\w*", re.IGNORECASE),
    re.compile(r"\b(?:созда|подготови|отправи|оформи|согласова)ла?\b(?P<gap>(?:[^.!?\n]|(?<=\d)\.(?=\d)){0,30}?)\b" + _NOUN, re.IGNORECASE),
]
NOT_DONE = re.compile(r"\b(?:не|будет|будут|после|когда|чтобы|можно|могу|нужно|если|пока|ли|бы)\b", re.IGNORECASE)
# «Заявка уже отправлена и ждёт согласования» — правда о прежней заявке, а не о новом черновике.
# А черновик создаёт только этот ответ, поэтому «черновик уже создан» без карточки — всегда неправда.
EXISTING = re.compile(r"\bждёт\b|\bждет\b|ожида\w*", re.IGNORECASE)
ALREADY = re.compile(r"\bуже\b", re.IGNORECASE)
CREATED = re.compile(r"созда|подготов|оформ", re.IGNORECASE)
NO_DRAFT_TEXT = ("Черновик заявки не создан: сервис заявок не подтвердил создание. "
                 "Попробуй ещё раз чуть позже — я помогу оформить заново.")


def answer(body: dict[str, Any], tools: Tools, model: ChatModel | None = None,
           max_tool_calls: int = 5, timeout: float = 25.0) -> dict[str, Any]:
    ctx = build_context(body)
    tools.deadline = time.monotonic() + timeout
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
    elif not tools.drafts:
        result = check_model_answer(result, body, ctx)
    # Черновики, созданные в этом запросе, всегда видны пользователю — даже если модель упала после создания.
    shown = {action["external_id"] for action in result["proposed_actions"]}
    missed = [draft_action(d) for d in {d["id"]: d for d in tools.drafts.values()}.values() if d["id"] not in shown]
    if missed:
        result["proposed_actions"] += missed
        if fell_back:
            result["text"] += "\n\nЧерновик заявки, который я успел подготовить, — в карточке. Проверь его и подтверди."
    result["trace"] = tools.trace
    # Отказ по правам или неверные даты — нормальный ответ. Упрощённый режим — только когда сервис не ответил.
    if any(step["error_code"] == "unavailable" for step in tools.trace):
        result["status"] = "degraded"
    return result


def check_model_answer(result: dict[str, Any], body: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Ответ модели, если черновик не создан: текст не утверждает обратного, а уточнение даты переживёт сбой модели."""
    if claims_draft(result["text"]):
        result["text"] = NO_DRAFT_TEXT
    nlu = understand(body["message"], ctx.today, body["state"])
    if nlu.intent == "absence" and nlu.date_from is None:
        result["state"] = {"intent": "absence_request", "kind": nlu.kind}
        result["missing_fields"] = ["date_from", "date_to"]
    elif nlu.intent == "access" and nlu.wants and not nlu.systems:
        result["state"] = {"intent": "access_request"}
        result["missing_fields"] = ["system"]
    return result


def claims_draft(text: str) -> bool:
    for pattern in CLAIMED_DRAFT:
        for m in pattern.finditer(text):
            sentence_end = re.search(r"[.!?\n]", text[m.end():])
            after = text[m.end():m.end() + (sentence_end.start() if sentence_end else len(text))]
            before = text[max(0, m.start() - 30):m.start()] + " " + m["gap"]
            about_old_request = ALREADY.search(before) and not CREATED.search(m.group(0))
            if not NOT_DONE.search(before) and not EXISTING.search(after) and not about_old_request:
                return True
    return False


def answer_by_rules(body: dict[str, Any], ctx: Context, tools: Tools) -> dict[str, Any]:
    nlu = understand(body["message"], ctx.today, body["state"])
    if nlu.intent == "next_steps":
        return next_steps(ctx)
    if nlu.intent == "absence":
        return absence(ctx, nlu, tools, body["request_id"])
    if nlu.intent == "access":
        return access(ctx, nlu, tools, body["request_id"])
    return question(body["message"], tools)


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


def access(ctx: Context, nlu: Understanding, tools: Tools, request_id: str) -> dict[str, Any]:
    """Доступы (A7): какие есть, каких не хватает, черновики заявок на названные системы."""
    sources = find_sources(tools, "как запросить доступы")
    try:
        items = {a["system"]: a for a in tools.mcp("access_list_my")["accesses"]}
    except ToolError as exc:
        if not (nlu.wants and nlu.systems):
            return response(f"Не получилось узнать твои доступы: {exc.message}", sources=sources)
        items = {}  # список не получили, но заявку на названную систему всё равно попробуем оформить
    if nlu.wants and nlu.systems:
        return request_access(ctx, nlu.systems, items, tools, request_id, sources)
    missing = [a for a in items.values() if a["required"] and a["status"] == "missing"]
    suggestions = [f"Запроси доступ к {a['title']}" for a in missing]
    if nlu.wants and missing:
        return response(f"Не хватает доступов: {titles(missing)}. Какой запросить?", sources=sources,
                        state={"intent": "access_request"}, missing_fields=["system"], suggestions=suggestions)
    return response(overview(items), sources=sources, suggestions=suggestions)


def overview(items: dict[str, dict[str, Any]]) -> str:
    groups = [("Есть", "granted"), ("Запрошены и ждут согласования", "pending"), ("Не хватает", "missing")]
    lines = [f"{label}: {titles(a for a in items.values() if a['status'] == status)}."
             for label, status in groups if any(a["status"] == status for a in items.values())]
    if not lines:
        return "Обязательных доступов для твоей команды нет."
    if not any(a["status"] == "missing" and a["required"] for a in items.values()):
        lines.append("Все обязательные доступы у тебя есть или уже запрошены.")
    return "\n".join(lines)


def titles(items: Any) -> str:
    return ", ".join(a["title"] for a in items)


def request_access(ctx: Context, systems: tuple[str, ...], items: dict[str, dict[str, Any]], tools: Tools,
                   request_id: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    reason = f"Нужен для работы в команде «{ctx.team_name}»" if ctx.team_name else "Нужен для работы"
    created, notes = [], []
    for system in systems:
        name, status = SYSTEM_TITLE[system], (items.get(system) or {}).get("status")
        if status == "granted":
            notes.append(f"Доступ к {name} у тебя уже есть.")
            continue
        if status == "pending":
            notes.append(f"Заявка на доступ к {name} уже отправлена и ждёт согласования.")
            continue
        try:
            created.append(draft_action(tools.mcp("access_create_draft", {
                "system": system, "reason": reason, "idempotency_key": f"{request_id}:access_create_draft:{system}"})))
        except ToolError as exc:
            notes.append(f"Черновик заявки на доступ к {name} создать не получилось — сервис доступов недоступен."
                         if exc.code == "unavailable" else exc.message)
    parts = []
    if created:
        drafts = "черновики заявок" if len(created) > 1 else "черновик заявки"
        parts.append(f"Я подготовил {drafts}: {', '.join(c['fields']['Система'] for c in created)}. Проверь и подтверди — "
                     f"только тогда заявка уйдёт на согласование ({created[0]['fields']['Согласует']}).")
    return response(" ".join(parts + notes), sources=sources, proposed_actions=created,
                    suggestions=["Что ещё сделать на этой неделе?"])


def question(message: str, tools: Tools) -> dict[str, Any]:
    """Вопрос по базе знаний (A7): ответ — текст найденных фрагментов, источники — они же."""
    try:
        top = safe_chunks(tools.search(message))[:2]
    except ToolError:
        return unknown(tools, "Поиск по базе знаний сейчас недоступен.")
    if not top:
        return unknown(tools, "В базе знаний ответа не нашёл — попробуй переформулировать вопрос.")
    parts = [f"**{c['source']['title']}" + (f" — {c['source']['section']}" if c["source"].get("section") else "")
             + f"**\n{shorten(c['text'])}" for c in top]
    note = f"\n\n_{top[0]['disclaimer']}_" if top[0].get("disclaimer") else ""
    return response("Вот что нашёл в базе знаний:\n\n" + "\n\n".join(parts) + note,
                    sources=[c["source"] for c in top], suggestions=["Что мне делать дальше?"])


def shorten(text: str, limit: int = 700) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def unknown(tools: Tools, lead: str = "") -> dict[str, Any]:
    text = (lead + " " if lead else "") + "Я умею подсказать следующие шаги адаптации, ответить по базе знаний, " \
        "проверить доступы и помочь оформить отгул или отпуск."
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


def safe_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Фрагменты поиска без повторов и без обращений к ассистенту. Ничего не добавляем от себя."""
    return list({c["source"]["chunk_id"]: c for c in chunks if not looks_like_instructions(c["text"])}.values())


def find_sources(tools: Tools, query: str) -> list[dict[str, Any]]:
    try:
        return [c["source"] for c in safe_chunks(tools.search(query))]
    except ToolError:
        return []


def ask_date(question: str, state: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    return response(f"{question} Если дней несколько, напиши первый и последний.", sources=sources,
                    missing_fields=["date_from", "date_to"], state=state, suggestions=ASK_DATE_SUGGESTIONS)
