"""Проверка контрактов, примеров и тестовых данных: `python -m devkit.validate`.

Что проверяется:
1. Все ссылки `$ref` в контрактах ведут на существующие схемы.
2. Каждый пример из `fixtures/` относится к операции контракта и проходит её схемы.
3. У каждого контракта есть обязательные виды примеров (успех, пусто, отказ, недоступность).
4. Идентификаторы в примерах существуют в тестовых данных `data/`.
5. Тестовые данные согласованы между собой.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from .contracts import (
    CONTRACT_FILES,
    ERROR_KINDS,
    ERROR_SCHEMA,
    KIND_STATUSES,
    REQUIRED_KINDS,
    Contracts,
    Operation,
    SeedData,
    id_like_strings,
    load_operations,
    load_seed,
    repo_root,
)

VISIBILITY_SCHEMA = "e_knowledge.yaml#/components/schemas/Visibility"
REQUEST_SCHEMA = "common.yaml#/components/schemas/CorpRequest"


def check_operation(contracts: Contracts, op: Operation) -> list[str]:
    problems: list[str] = []
    where = f"{op.source}"

    if op.contract not in CONTRACT_FILES:
        return [f"{where}: неизвестный контракт {op.contract!r}"]

    if op.is_mcp:
        tools = {t["name"] for t in contracts.mcp_tools()}
        if op.tool not in tools:
            problems.append(f"{where}: инструмента {op.tool!r} нет в контракте C")
    else:
        declared = contracts.rest_operations(op.contract).get(op.operation)
        if declared is None:
            problems.append(f"{where}: операции {op.operation!r} нет в контракте {op.contract}")
        elif declared != (op.method, op.path):
            problems.append(f"{where}: в контракте {declared[0]} {declared[1]}, в примере {op.method} {op.path}")

    names = Counter(case.name for case in op.cases)
    problems += [f"{where}: имя примера {name!r} повторяется" for name, n in names.items() if n > 1]
    if not any(case.kind == "success" for case in op.cases):
        problems.append(f"{where}: нет ни одного успешного примера")

    for case in op.cases:
        label = f"{where} [{case.name}]"
        if case.kind not in KIND_STATUSES:
            problems.append(f"{label}: неизвестный вид {case.kind!r}")
            continue

        body = case.response.get("body")
        if op.is_mcp:
            if bool(case.response.get("is_error")) != (case.kind in ERROR_KINDS):
                problems.append(f"{label}: is_error не соответствует виду {case.kind!r}")
            request_value = case.request.get("arguments", {})
            is_error = bool(case.response.get("is_error"))
        else:
            status = case.response.get("status")
            if status not in KIND_STATUSES[case.kind]:
                problems.append(f"{label}: статус {status} не подходит виду {case.kind!r}")
            request_value = case.request.get("body")
            is_error = isinstance(status, int) and status >= 400

        # Запрос проверяем по схеме, кроме примеров с намеренно неверным запросом.
        if op.request_schema and case.kind != "validation":
            problems += [f"{label}: запрос: {e}" for e in contracts.errors(request_value, op.request_schema)]

        schema = case.response_schema or (ERROR_SCHEMA if is_error else None)
        if schema is None:
            problems.append(f"{label}: не указана схема ответа (response_schema)")
        else:
            problems += [f"{label}: ответ: {e}" for e in contracts.errors(body, schema)]
    return problems


def check_required_kinds(operations: list[Operation]) -> list[str]:
    problems = []
    for contract, required in REQUIRED_KINDS.items():
        present = {case.kind for op in operations if op.contract == contract for case in op.cases}
        for kind in sorted(required - present):
            problems.append(f"контракт {contract}: нет примера вида {kind!r}")
    return problems


def check_fixture_ids(contracts: Contracts, operations: list[Operation], seed: SeedData) -> list[str]:
    known = seed.known_ids() | contracts.enum_values()
    problems = []
    for op in operations:
        for case in op.cases:
            for value in sorted(set(id_like_strings([case.request, case.response]))):
                if value not in known:
                    problems.append(f"{op.source} [{case.name}]: идентификатора {value!r} нет в тестовых данных")
    return problems


def check_seed(contracts: Contracts, seed: SeedData) -> list[str]:
    problems: list[str] = []
    users = {u["id"]: u for u in seed.users}
    teams = {t["id"] for t in seed.teams}
    stages = {s["id"] for s in seed.checklist["stages"]}
    tasks = {t["id"] for t in seed.checklist["tasks"]}
    systems = {s["system"] for s in seed.accesses["systems"]}

    for name, ids in (("пользователей", [u["id"] for u in seed.users]), ("задач", [t["id"] for t in seed.checklist["tasks"]]),
                      ("заявок", [r["id"] for r in seed.requests]), ("документов", [d["id"] for d in seed.documents])):
        problems += [f"data: повторяется идентификатор {i!r} в списке {name}" for i, n in Counter(ids).items() if n > 1]

    for user in seed.users:
        if user["team_id"] is not None and user["team_id"] not in teams:
            problems.append(f"users.json: у {user['id']} неизвестная команда {user['team_id']!r}")
        for key in ("mentor_id", "manager_id"):
            if user[key] is not None and user[key] not in users:
                problems.append(f"users.json: у {user['id']} неизвестный {key} {user[key]!r}")

    for task in seed.checklist["tasks"]:
        if task["stage_id"] not in stages:
            problems.append(f"checklist.json: у задачи {task['id']} неизвестный этап {task['stage_id']!r}")

    for user_id, state in seed.onboarding_state.items():
        if user_id not in users:
            problems.append(f"onboarding_state.json: неизвестный пользователь {user_id!r}")
        problems += [f"onboarding_state.json: у {user_id} неизвестная задача {t!r}" for t in state if t not in tasks]

    for team_id, required in seed.accesses["required_by_team"].items():
        if team_id not in teams:
            problems.append(f"accesses.json: неизвестная команда {team_id!r}")
        problems += [f"accesses.json: неизвестная система {s!r}" for s in required if s not in systems]
    for user_id, granted in seed.accesses["user_accesses"].items():
        if user_id not in users:
            problems.append(f"accesses.json: неизвестный пользователь {user_id!r}")
        problems += [f"accesses.json: неизвестная система {s!r}" for s in granted if s not in systems]

    for contact in seed.contacts:
        if contact["id"] is not None and contact["id"] not in users:
            problems.append(f"contacts.json: неизвестный пользователь {contact['id']!r}")
        if contact["team_id"] is not None and contact["team_id"] not in teams:
            problems.append(f"contacts.json: неизвестная команда {contact['team_id']!r}")

    for request in seed.requests:
        problems += [f"requests.json [{request.get('id')}]: {e}" for e in contracts.errors(request, REQUEST_SCHEMA)]
        if request.get("owner_id") not in users:
            problems.append(f"requests.json [{request.get('id')}]: неизвестный владелец")

    for doc in seed.documents:
        for field in ("id", "title", "visibility", "tags", "updated_at", "disclaimer"):
            if field not in doc:
                problems.append(f"{doc['path']}: в шапке нет поля {field!r}")
        if Path(doc["path"]).stem != doc.get("id"):
            problems.append(f"{doc['path']}: имя файла не совпадает с id")
        for item in doc.get("visibility") or []:
            problems += [f"{doc['path']}: visibility {item!r}: {e}" for e in contracts.errors(item, VISIBILITY_SCHEMA)]
            if item.startswith("team:") and item.split(":", 1)[1] not in teams:
                problems.append(f"{doc['path']}: неизвестная команда в visibility {item!r}")
        if not doc["anchors"]:
            problems.append(f"{doc['path']}: у разделов нет якорей вида {{#anchor}}")
        if "не является регламентом" not in str(doc.get("disclaimer", "")):
            problems.append(f"{doc['path']}: нет пометки тестовой инструкции")
    return problems


def run(root: Path | None = None) -> tuple[list[str], str]:
    """Все проверки. Возвращает список проблем и краткую сводку."""
    root = root or repo_root()
    contracts = Contracts.load(root)
    operations = load_operations(root)
    seed = load_seed(root)

    problems = contracts.unresolved_refs()
    for op in operations:
        problems += check_operation(contracts, op)
    problems += check_required_kinds(operations)
    problems += check_fixture_ids(contracts, operations, seed)
    problems += check_seed(contracts, seed)

    lines = []
    for contract in CONTRACT_FILES:
        ops = [op for op in operations if op.contract == contract]
        kinds = Counter(case.kind for op in ops for case in op.cases)
        detail = ", ".join(f"{kind}: {n}" for kind, n in sorted(kinds.items()))
        lines.append(f"  {contract}: операций {len(ops)}, примеров {sum(kinds.values())} ({detail})")
    lines.append(f"  данные: пользователей {len(seed.users)}, задач {len(seed.checklist['tasks'])}, "
                 f"документов {len(seed.documents)}, заявок {len(seed.requests)}")
    return problems, "\n".join(lines)


def main() -> int:
    problems, summary = run()
    print("Контракты и примеры:")
    print(summary)
    if problems:
        print(f"\nНайдено проблем: {len(problems)}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nВсё согласовано.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
