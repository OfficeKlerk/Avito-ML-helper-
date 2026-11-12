"""Ответ с моделью (задача A6): модель вызывает те же инструменты, ответ собирается в формате контракта B."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from . import contract
from .context import Context, to_prompt
from .llm import ChatModel, LlmError
from .reply import response
from .tools import Tools, ToolError

PROMPTS_DIR = Path(os.environ.get("PROMPTS_DIR") or Path(__file__).resolve().parents[1] / "prompts")
CORP_TOOLS = ("directory_find_contact", "absence_get_rules", "absence_create_draft", "access_list_my", "access_create_draft")


def tool_definitions() -> list[dict[str, Any]]:
    return [contract.search_definition()] + [contract.tool_definition(name) for name in CORP_TOOLS]


def answer_with_model(body: dict[str, Any], ctx: Context, tools: Tools, model: ChatModel,
                      max_tool_calls: int, timeout: float) -> dict[str, Any]:
    """Ответ модели. LlmError или ToolError — модель недоступна или время вышло; тогда отвечаем по правилам.

    Карточки черновиков в ответ добавляет вызывающий — из `tools.drafts`, то есть ровно то, что создано.
    """
    deadline = time.monotonic() + timeout
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")},
        {"role": "system", "content": "Контекст пользователя:\n" + to_prompt(ctx)},
        *({"role": item["role"], "content": item["text"]} for item in body["history"]),
        {"role": "user", "content": body["message"]},
    ]
    definitions = tool_definitions()
    sources: dict[str, dict[str, Any]] = {}
    contacts: list[dict[str, Any]] = []
    calls = 0

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LlmError("время на ответ модели вышло")
        offer = definitions if calls < max_tool_calls else None  # предел исчерпан — только текст
        message = tools.traced("llm", lambda: model.complete(messages, offer, remaining))
        tool_calls = message.get("tool_calls") or []
        if not tool_calls or offer is None:
            text = (message.get("content") or "").strip()
            if not text:
                raise LlmError("модель вернула пустой ответ")
            contact = contacts[0] if contacts else None
            return response(text, sources=list(sources.values()), escalation={"needed": contact is not None, "contact": contact})
        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
        for call in tool_calls:
            calls += 1
            if calls > max_tool_calls:
                result = {"error": {"code": "rate_limited", "message": "Предел вызовов инструментов исчерпан. Ответь текстом."}}
            else:
                result = run_tool(call, body["request_id"], tools, sources, contacts)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result, ensure_ascii=False)})


def run_tool(call: dict[str, Any], request_id: str, tools: Tools, sources: dict[str, Any],
             contacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Выполнить вызов модели и собрать из результата источники и контакты для ответа."""
    function = call.get("function") or {}
    name = function.get("name", "")
    try:
        args = json.loads(function.get("arguments") or "{}")
    except ValueError:
        args = None
    if not isinstance(args, dict):
        return _error("validation", "Аргументы должны быть JSON-объектом.")
    if name not in ("knowledge_search", *CORP_TOOLS):
        return _error("not_found", f"Инструмента {name} нет.")

    if name == "absence_create_draft":
        args["idempotency_key"] = f"{request_id}:absence_create_draft"
    elif name == "access_create_draft":  # своя заявка на каждую систему
        args["idempotency_key"] = f"{request_id}:access_create_draft:{args.get('system')}"
    problems = (contract.errors(args, "SearchRequest", "e_knowledge.yaml") if name == "knowledge_search"
                else contract.errors(args, contract.tool_input_schema(name), "c_mcp_tools.yaml"))
    if problems:
        return _error("validation", "Аргументы не подходят: " + "; ".join(problems))

    if name == "access_create_draft":
        refusal = already_has_access(tools, args["system"])
        if refusal:
            return _error("conflict", refusal)
    try:
        if name == "knowledge_search":
            chunks = tools.search(args["query"], args.get("top_k", 3))
            for chunk in chunks:
                sources.setdefault(chunk["source"]["chunk_id"], chunk["source"])
            return {"results": [{"source": c["source"], "text": c["text"]} for c in chunks]}
        result = tools.mcp(name, args)
    except ToolError as exc:
        return _error(exc.code, exc.message)
    if name == "directory_find_contact":
        contacts.extend({"id": c.get("id"), "name": c["name"], "role_title": c["role_title"], "channel": c.get("channel")}
                        for c in result.get("contacts", []))
    return result


def already_has_access(tools: Tools, system: str) -> str | None:
    """Модели нельзя создать заявку на доступ, который уже есть или уже запрошен: проверяем, а не просим."""
    try:
        items = {a["system"]: a for a in tools.mcp("access_list_my")["accesses"]}
    except ToolError:
        return None  # список не получили — решит corp-mock
    item = items.get(system) or {}
    if item.get("status") == "granted":
        return f"Доступ к {item['title']} у пользователя уже есть. Черновик не нужен."
    if item.get("status") == "pending":
        return f"Заявка на доступ к {item['title']} уже отправлена и ждёт согласования. Черновик не нужен."
    return None


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}
