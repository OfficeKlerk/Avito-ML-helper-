"""Загрузка контрактов, примеров (fixtures) и тестовых данных; проверка примеров по схемам.

Этим модулем пользуются проверка контрактов (`devkit.validate`), заглушки (`devkit.stub_server`)
и сквозная проверка (`devkit.smoke`), поэтому примеры в `fixtures/` — единственный источник
и для заглушек, и для проверок настоящих сервисов.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

BASE_URI = "file:///contracts/"
ERROR_SCHEMA = "common.yaml#/components/schemas/ErrorResponse"

# Вид примера → допустимые HTTP-статусы. Для MCP: ошибка это или нет.
KIND_STATUSES: dict[str, tuple[int, ...]] = {
    "success": (200,),
    "empty": (200,),
    "degraded": (200,),
    "forbidden": (401, 403),
    "not_found": (404,),
    "conflict": (409,),
    "validation": (422,),
    "unavailable": (503,),
}
ERROR_KINDS = {"forbidden", "not_found", "conflict", "validation", "unavailable"}

# Какие виды примеров обязаны быть у каждого контракта (требование G0.1).
REQUIRED_KINDS: dict[str, set[str]] = {
    "A": {"success", "empty", "forbidden", "unavailable"},
    "B": {"success", "empty", "forbidden", "unavailable"},
    "C": {"success", "empty", "forbidden", "unavailable"},
    "D": {"success", "forbidden", "unavailable"},
    "E": {"success", "empty", "forbidden", "unavailable"},
}

CONTRACT_FILES = {
    "A": "a_core_api.yaml",
    "B": "b_agent.yaml",
    "C": "c_mcp_tools.yaml",
    "D": "d_corp_rest.yaml",
    "E": "e_knowledge.yaml",
}

ID_PATTERNS = {
    "user": re.compile(r"^u_[a-z0-9_]+$"),
    "team": re.compile(r"^team_[a-z0-9_]+$"),
    "stage": re.compile(r"^st_[a-z0-9_]+$"),
    "task": re.compile(r"^t_[a-z0-9_]+$"),
    "doc": re.compile(r"^kb_[a-z0-9_]+$"),
    "chunk": re.compile(r"^kb_[a-z0-9_]+#[a-z0-9_-]+$"),
    "request": re.compile(r"^req_[a-z0-9_]+$"),
}
ANCHOR_RE = re.compile(r"^#{1,6}\s+.*\{#([a-z0-9_-]+)\}\s*$", re.MULTILINE)


def repo_root() -> Path:
    env = os.environ.get("REPO_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- контракты


class Contracts:
    """Все файлы `contracts/*.yaml` и проверка значений по их схемам."""

    def __init__(self, docs: dict[str, dict[str, Any]]):
        self.docs = docs
        resources = [
            (BASE_URI + name, Resource(contents=doc, specification=DRAFT202012))
            for name, doc in docs.items()
        ]
        self.registry = Registry().with_resources(resources)
        self._validators: dict[str, Draft202012Validator] = {}

    @classmethod
    def load(cls, root: Path | None = None) -> "Contracts":
        root = root or repo_root()
        docs = {
            path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted((root / "contracts").glob("*.yaml"))
        }
        return cls(docs)

    def validator(self, ref: str) -> Draft202012Validator:
        if ref not in self._validators:
            self._validators[ref] = Draft202012Validator(
                {"$ref": BASE_URI + ref},
                registry=self.registry,
                format_checker=FormatChecker(),
            )
        return self._validators[ref]

    def errors(self, instance: Any, ref: str) -> list[str]:
        """Человекочитаемые нарушения схемы `ref` (например `common.yaml#/components/schemas/Error`)."""
        found = []
        for err in sorted(self.validator(ref).iter_errors(instance), key=lambda e: list(e.absolute_path)):
            where = "/".join(str(p) for p in err.absolute_path) or "<корень>"
            found.append(f"{where}: {err.message}")
        return found

    def unresolved_refs(self) -> list[str]:
        """Ссылки `$ref`, которые никуда не ведут."""
        problems = []
        for name, doc in self.docs.items():
            resolver = self.registry.resolver(base_uri=BASE_URI + name)
            for ref in _iter_refs(doc):
                try:
                    resolver.lookup(ref)
                except Unresolvable:
                    problems.append(f"{name}: ссылка {ref} никуда не ведёт")
        return problems

    def deref(self, ref: str) -> Any:
        """Схема по ссылке со всеми вложенными `$ref`, развёрнутыми на месте (для MCP inputSchema)."""
        resolver = self.registry.resolver(base_uri=BASE_URI)
        return _inline(self.registry, resolver, {"$ref": ref})

    def enum_values(self) -> set[str]:
        """Все значения перечислений — они похожи на идентификаторы, но ими не являются."""
        values: set[str] = set()
        for doc in self.docs.values():
            for node in _walk(doc):
                if isinstance(node, dict) and isinstance(node.get("enum"), list):
                    values.update(v for v in node["enum"] if isinstance(v, str))
        return values

    def rest_operations(self, contract: str) -> dict[str, tuple[str, str]]:
        """operationId → (метод, путь) для REST-контракта."""
        doc = self.docs[CONTRACT_FILES[contract]]
        result = {}
        for path, item in (doc.get("paths") or {}).items():
            for method, op in item.items():
                if isinstance(op, dict) and "operationId" in op:
                    result[op["operationId"]] = (method.upper(), path)
        return result

    def mcp_tools(self) -> list[dict[str, Any]]:
        return list(self.docs[CONTRACT_FILES["C"]].get("tools") or [])


def _walk(node: Any) -> Iterator[Any]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _iter_refs(node: Any) -> Iterator[str]:
    for item in _walk(node):
        if isinstance(item, dict) and isinstance(item.get("$ref"), str):
            yield item["$ref"]


def _inline(registry: Registry, resolver: Any, node: Any) -> Any:
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            resolved = resolver.lookup(node["$ref"])
            merged = _inline(registry, resolved.resolver, resolved.contents)
            extra = {k: _inline(registry, resolver, v) for k, v in node.items() if k != "$ref"}
            return {**merged, **extra} if isinstance(merged, dict) else merged
        return {k: _inline(registry, resolver, v) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(registry, resolver, v) for v in node]
    return node


# ---------------------------------------------------------------- примеры


@dataclass(frozen=True)
class Case:
    name: str
    kind: str
    description: str
    request: dict[str, Any]
    response: dict[str, Any]
    response_schema: str | None
    match: dict[str, Any] | None
    delay_ms: int

    @property
    def is_error(self) -> bool:
        return self.kind in ERROR_KINDS


@dataclass(frozen=True)
class Operation:
    contract: str
    operation: str
    method: str | None  # REST
    path: str | None  # REST, шаблон с {параметрами}
    tool: str | None  # MCP
    request_schema: str | None
    cases: tuple[Case, ...]
    source: str

    @property
    def is_mcp(self) -> bool:
        return self.tool is not None

    def path_regex(self) -> re.Pattern[str]:
        assert self.path is not None
        pattern = re.sub(r"\{([a-z_]+)\}", r"(?P<\1>[^/]+)", self.path)
        return re.compile(f"^{pattern}$")

    def case(self, name_or_kind: str) -> Case | None:
        for case in self.cases:
            if case.name == name_or_kind:
                return case
        for case in self.cases:
            if case.kind == name_or_kind:
                return case
        return None

    def default_case(self) -> Case:
        for case in self.cases:
            if case.kind == "success" and not case.match:
                return case
        for case in self.cases:
            if case.kind == "success":
                return case
        return self.cases[0]


def load_operations(root: Path | None = None) -> list[Operation]:
    root = root or repo_root()
    operations = []
    for path in sorted((root / "fixtures").rglob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        cases = tuple(
            Case(
                name=c["name"],
                kind=c["kind"],
                description=c.get("description", ""),
                request=c.get("request") or {},
                response=c["response"],
                response_schema=c.get("response_schema"),
                match=c.get("match"),
                delay_ms=int(c.get("delay_ms", 0)),
            )
            for c in raw["cases"]
        )
        operations.append(
            Operation(
                contract=raw["contract"],
                operation=raw["operation"],
                method=raw.get("method"),
                path=raw.get("path"),
                tool=raw.get("tool"),
                request_schema=raw.get("request_schema"),
                cases=cases,
                source=str(path.relative_to(root)),
            )
        )
    return operations


def select_case(
    op: Operation,
    requested: str | None,
    *,
    path_params: dict[str, str] | None = None,
    body: Any = None,
) -> Case | None:
    """Какой пример вернуть заглушке.

    `requested` — имя или вид примера (заголовок `X-Stub-Case` или общий режим заглушки).
    Без него — первый пример, чьё правило `match` подошло, иначе успешный пример по умолчанию.
    None означает «у операции такого примера нет» — заглушка решает сама, что отдать.
    """
    if requested:
        return op.case(requested)
    for case in op.cases:
        if case.match and _matches(case.match, path_params or {}, body):
            return case
    return op.default_case()


def _matches(rule: dict[str, Any], path_params: dict[str, str], body: Any) -> bool:
    """Правило `match`: `path_params` — точное совпадение параметров пути; `body` — подстрока
    (без учёта регистра) в поле тела запроса или в аргументе инструмента."""
    for key, expected in (rule.get("path_params") or {}).items():
        if path_params.get(key) != expected:
            return False
    fields = body if isinstance(body, dict) else {}
    for key, needle in (rule.get("body") or {}).items():
        if str(needle).lower() not in str(fields.get(key, "")).lower():
            return False
    return True


# ---------------------------------------------------------------- тестовые данные


@dataclass(frozen=True)
class SeedData:
    users: list[dict[str, Any]]
    teams: list[dict[str, Any]]
    checklist: dict[str, Any]
    onboarding_state: dict[str, dict[str, str]]
    accesses: dict[str, Any]
    contacts: list[dict[str, Any]]
    absence_rules: dict[str, Any]
    requests: list[dict[str, Any]]
    documents: list[dict[str, Any]]  # шапка документа + "anchors" + "path"

    def known_ids(self) -> set[str]:
        ids = {u["id"] for u in self.users} | {t["id"] for t in self.teams}
        ids |= {s["id"] for s in self.checklist["stages"]} | {t["id"] for t in self.checklist["tasks"]}
        ids |= {r["id"] for r in self.requests}
        for doc in self.documents:
            ids.add(doc["id"])
            ids |= {f"{doc['id']}#{anchor}" for anchor in doc["anchors"]}
        return ids


def load_seed(root: Path | None = None) -> SeedData:
    root = root or repo_root()
    seed = root / "data" / "seed"

    def read(name: str) -> Any:
        return json.loads((seed / name).read_text(encoding="utf-8"))

    documents = []
    for path in sorted((root / "data" / "kb").glob("*.md")):
        meta, body = split_front_matter(path.read_text(encoding="utf-8"))
        documents.append({**meta, "anchors": ANCHOR_RE.findall(body), "path": str(path.relative_to(root))})
    # preloaded — заявки, которые corp-mock загружает при старте; examples — результаты операций
    # из примеров контрактов (появляются в ходе сценария, при старте их нет).
    requests = read("requests.json")
    return SeedData(
        users=read("users.json"),
        teams=read("teams.json"),
        checklist=read("checklist.json"),
        onboarding_state=read("onboarding_state.json"),
        accesses=read("accesses.json"),
        contacts=read("contacts.json"),
        absence_rules=read("absence_rules.json"),
        requests=requests["preloaded"] + requests["examples"],
        documents=documents,
    )


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Шапка документа базы знаний (YAML между `---`) и его текст."""
    if not text.startswith("---\n"):
        raise ValueError("документ должен начинаться с шапки между строками ---")
    _, front, body = text.split("---\n", 2)
    meta = yaml.safe_load(front)
    if not isinstance(meta, dict):
        raise ValueError("шапка документа должна быть набором полей")
    return meta, body


def id_like_strings(node: Any) -> Iterator[str]:
    """Строки, которые выглядят как идентификаторы из тестовых данных."""
    for item in _walk(node):
        if isinstance(item, str) and any(p.match(item) for p in ID_PATTERNS.values()):
            yield item
