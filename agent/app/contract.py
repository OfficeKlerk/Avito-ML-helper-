"""Схемы контрактов прямо из `contracts/` — единственного источника схем."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

BASE_URI = "file:///contracts/"
CONTRACTS_DIR = Path(os.environ.get("CONTRACTS_DIR") or Path(__file__).resolve().parents[2] / "contracts")


@cache
def _documents() -> dict[str, Any]:
    return {path.name: yaml.safe_load(path.read_text(encoding="utf-8")) for path in CONTRACTS_DIR.glob("*.yaml")}


@cache
def _registry() -> Registry:
    return Registry().with_resources(
        (BASE_URI + name, Resource(contents=doc, specification=DRAFT202012)) for name, doc in _documents().items()
    )


@cache
def _validator(ref: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": BASE_URI + ref}, registry=_registry(), format_checker=FormatChecker())


def errors(instance: Any, schema: str, file: str = "b_agent.yaml") -> list[str]:
    """Нарушения схемы `<file>#/components/schemas/<schema>`; пустой список — всё в порядке."""
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<корень>'}: {e.message}"
        for e in _validator(f"{file}#/components/schemas/{schema}").iter_errors(instance)
    ]


def tool_definition(name: str, hidden: tuple[str, ...] = ("idempotency_key",)) -> dict[str, Any]:
    """Инструмент corp-mock из контракта C в формате function calling. Скрытые параметры заполняет агент."""
    tool = next(t for t in _documents()["c_mcp_tools.yaml"]["tools"] if t["name"] == name)
    schema = _inline("c_mcp_tools.yaml", tool["input"])
    schema["properties"] = {k: v for k, v in schema.get("properties", {}).items() if k not in hidden}
    schema["required"] = [k for k in schema.get("required", []) if k not in hidden]
    return function(name, " ".join(tool["description"].split()), schema)


def tool_input_schema(name: str) -> str:
    """Имя схемы аргументов инструмента corp-mock в контракте C."""
    tool = next(t for t in _documents()["c_mcp_tools.yaml"]["tools"] if t["name"] == name)
    return tool["input"]["$ref"].rsplit("/", 1)[-1]


def search_definition() -> dict[str, Any]:
    return function("knowledge_search", "Найти фрагменты базы знаний команды, доступные пользователю. Возвращает текст и источник.",
                    _inline("e_knowledge.yaml", {"$ref": "#/components/schemas/SearchRequest"}))


def function(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def _inline(file: str, node: Any) -> Any:
    """Схема со всеми `$ref`, развёрнутыми на месте: модели ссылки не понимают."""
    def walk(resolver: Any, value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                resolved = resolver.lookup(value["$ref"])
                return walk(resolved.resolver, resolved.contents)
            return {k: walk(resolver, v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(resolver, v) for v in value]
        return value

    return walk(_registry().resolver(base_uri=BASE_URI + file), node)
