import json

import pytest

from devkit import validate
from devkit.contracts import (
    Contracts,
    Operation,
    id_like_strings,
    load_operations,
    load_seed,
    select_case,
    split_front_matter,
)


@pytest.fixture(scope="module")
def contracts() -> Contracts:
    return Contracts.load()


@pytest.fixture(scope="module")
def operations() -> list[Operation]:
    return load_operations()


def op_named(operations: list[Operation], contract: str, name: str) -> Operation:
    return next(op for op in operations if op.contract == contract and op.operation == name)


def test_repository_is_consistent():
    problems, summary = validate.run()
    assert problems == []
    assert "A: операций" in summary


def test_schema_rejects_wrong_value(contracts):
    good = {"error": {"code": "forbidden", "message": "Нет доступа."}}
    assert contracts.errors(good, "common.yaml#/components/schemas/ErrorResponse") == []
    bad = {"error": {"code": "nope", "message": ""}}
    errors = contracts.errors(bad, "common.yaml#/components/schemas/ErrorResponse")
    assert len(errors) == 2
    assert any("error/code" in e for e in errors)


def test_date_format_is_checked(contracts):
    payload = {"kind": "day_off", "date_from": "13.11.2026", "date_to": "2026-11-13"}
    errors = contracts.errors(payload, "common.yaml#/components/schemas/AbsencePayload")
    assert len(errors) == 1 and "date_from" in errors[0]


def test_deref_inlines_nested_refs(contracts):
    schema = contracts.deref("c_mcp_tools.yaml#/components/schemas/AccessCreateDraftInput")
    assert "$ref" not in json.dumps(schema)
    assert "gitlab" in schema["properties"]["system"]["enum"]


def test_broken_ref_is_reported():
    broken = Contracts({"x.yaml": {"components": {"schemas": {"A": {"$ref": "#/components/schemas/Missing"}}}}})
    assert broken.unresolved_refs() == ["x.yaml: ссылка #/components/schemas/Missing никуда не ведёт"]


def test_rest_operations_and_tools_are_listed(contracts):
    assert contracts.rest_operations("D")["request_submit"] == ("POST", "/api/v1/requests/{request_id}/submit")
    assert "absence_create_draft" in {t["name"] for t in contracts.mcp_tools()}


def test_select_case_by_name_kind_match_and_default(operations):
    chat = op_named(operations, "B", "chat")
    assert select_case(chat, None, body={"message": "Что дальше?", "onboarding": "Запроси доступы"}).name == "next_steps"
    assert select_case(chat, None, body={"message": "Отгул в ПЯТНИЦУ"}).name == "absence_draft"
    assert select_case(chat, None, body={"message": "как оформить отгул"}).name == "absence_clarify"
    assert select_case(chat, "llm_degraded").name == "llm_degraded"
    assert select_case(chat, "unavailable").kind == "unavailable"
    assert select_case(chat, "no_such_case") is None


def test_select_case_by_path_params(operations):
    get = op_named(operations, "D", "request_get")
    assert select_case(get, None, path_params={"request_id": "req_max_vacation_1"}).name == "foreign"
    assert select_case(get, None, path_params={"request_id": "req_anna_dayoff_1"}).name == "draft"


def test_path_regex(operations):
    submit = op_named(operations, "D", "request_submit")
    assert submit.path_regex().match("/api/v1/requests/req_x/submit").groupdict() == {"request_id": "req_x"}
    assert submit.path_regex().match("/api/v1/requests/req_x") is None


def test_seed_knows_ids_and_chunks():
    seed = load_seed()
    known = seed.known_ids()
    assert {"u_anna", "team_auto", "st_week1", "t_first_task", "req_anna_gitlab_1", "kb_absence_rules#day-off"} <= known


def test_id_like_strings_ignores_plain_text():
    found = set(id_like_strings({"a": ["u_anna", "Анна", "kb_x#y"], "b": {"c": "team_space", "d": 5}}))
    assert found == {"u_anna", "kb_x#y", "team_space"}


def test_front_matter_requires_header():
    meta, body = split_front_matter('---\nid: kb_x\ntags: ["1:1"]\n---\n\n# Текст\n')
    assert meta == {"id": "kb_x", "tags": ["1:1"]} and body.strip() == "# Текст"
    with pytest.raises(ValueError):
        split_front_matter("# Без шапки")
    with pytest.raises(ValueError):
        split_front_matter("---\n- список\n---\nтекст")
