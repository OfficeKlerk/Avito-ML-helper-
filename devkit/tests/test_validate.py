"""Проверка ловит типичные ошибки: берём рабочие данные, портим одно место и ждём находку."""

import copy
import dataclasses

import pytest

from devkit import validate
from devkit.contracts import Case, Contracts, Operation, load_operations, load_seed


@pytest.fixture(scope="module")
def contracts() -> Contracts:
    return Contracts.load()


@pytest.fixture()
def submit() -> Operation:
    return next(op for op in load_operations() if op.operation == "request_submit")


def with_case(op: Operation, index: int, **changes) -> Operation:
    cases = list(op.cases)
    cases[index] = dataclasses.replace(cases[index], **changes)
    return dataclasses.replace(op, cases=tuple(cases))


def test_valid_operation_has_no_problems(contracts, submit):
    assert validate.check_operation(contracts, submit) == []


def test_response_must_match_schema(contracts, submit):
    body = {**submit.cases[0].response["body"], "status": "sent"}
    broken = with_case(submit, 0, response={"status": 200, "body": body})
    problems = validate.check_operation(contracts, broken)
    assert len(problems) == 1 and "status" in problems[0]


def test_status_must_fit_kind(contracts, submit):
    broken = with_case(submit, 0, kind="unavailable")
    assert any("статус 200 не подходит виду 'unavailable'" in p for p in validate.check_operation(contracts, broken))


def test_unknown_kind_operation_and_contract(contracts, submit):
    assert any("неизвестный вид" in p for p in validate.check_operation(contracts, with_case(submit, 0, kind="weird")))
    renamed = dataclasses.replace(submit, operation="request_send")
    assert any("нет в контракте D" in p for p in validate.check_operation(contracts, renamed))
    moved = dataclasses.replace(submit, path="/api/v1/requests/{request_id}/send")
    assert any("в контракте POST" in p for p in validate.check_operation(contracts, moved))
    assert "неизвестный контракт" in validate.check_operation(contracts, dataclasses.replace(submit, contract="Z"))[0]


def test_duplicate_names_and_missing_success(contracts, submit):
    doubled = dataclasses.replace(submit, cases=submit.cases + (submit.cases[0],))
    assert any("повторяется" in p for p in validate.check_operation(contracts, doubled))
    only_errors = dataclasses.replace(submit, cases=submit.cases[1:])
    assert any("нет ни одного успешного" in p for p in validate.check_operation(contracts, only_errors))


def test_success_case_needs_response_schema(contracts, submit):
    broken = with_case(submit, 0, response_schema=None)
    assert any("не указана схема ответа" in p for p in validate.check_operation(contracts, broken))


def test_mcp_request_and_error_flag_are_checked(contracts):
    draft = next(op for op in load_operations() if op.tool == "absence_create_draft")
    assert validate.check_operation(contracts, draft) == []
    no_key = {"arguments": {"kind": "day_off", "date_from": "2026-11-13", "date_to": "2026-11-13"}}
    assert any("idempotency_key" in p for p in validate.check_operation(contracts, with_case(draft, 0, request=no_key)))
    flagged = with_case(draft, 0, response={"is_error": True, "body": draft.cases[0].response["body"]})
    assert any("is_error не соответствует" in p for p in validate.check_operation(contracts, flagged))
    unknown = dataclasses.replace(draft, tool="absence_delete")
    assert any("нет в контракте C" in p for p in validate.check_operation(contracts, unknown))


def test_required_kinds(submit):
    problems = validate.check_required_kinds([submit])
    assert "контракт A: нет примера вида 'success'" in problems
    assert not any(p.startswith("контракт D") for p in problems)
    assert validate.check_required_kinds(load_operations()) == []


def test_unknown_id_in_fixture_is_reported(contracts, submit):
    case: Case = submit.cases[0]
    request = {**case.request, "path_params": {"request_id": "req_nobody_1"}}
    problems = validate.check_fixture_ids(contracts, [with_case(submit, 0, request=request)], load_seed())
    assert problems == ["fixtures/d_corp_rest/request_submit.json [submitted]: идентификатора 'req_nobody_1' нет в тестовых данных"]


def test_seed_problems_are_reported(contracts):
    seed = load_seed()
    assert validate.check_seed(contracts, seed) == []

    users = copy.deepcopy(seed.users)
    users[0]["team_id"] = "team_ghost"
    users[1]["mentor_id"] = "u_ghost"
    checklist = copy.deepcopy(seed.checklist)
    checklist["tasks"][0]["stage_id"] = "st_ghost"
    checklist["tasks"].append(copy.deepcopy(checklist["tasks"][1]))
    accesses = copy.deepcopy(seed.accesses)
    accesses["required_by_team"]["team_ghost"] = ["fax"]
    accesses["user_accesses"]["u_ghost"] = {"fax": "granted"}
    contacts = copy.deepcopy(seed.contacts) + [{"topic": "absence", "team_id": "team_ghost", "id": "u_ghost", "name": "?", "role_title": "?", "channel": None}]
    requests = copy.deepcopy(seed.requests)
    requests[0]["status"] = "lost"
    requests[1]["owner_id"] = "u_ghost"
    documents = copy.deepcopy(seed.documents)
    documents[0]["visibility"] = ["team:team_ghost", "everyone"]
    documents[0]["disclaimer"] = "Регламент"
    documents[1]["anchors"] = []
    del documents[2]["title"]
    documents[3]["id"] = "kb_other"
    broken = dataclasses.replace(
        seed, users=users, checklist=checklist, accesses=accesses, contacts=contacts, requests=requests,
        documents=documents, onboarding_state={"u_ghost": {"t_ghost": "done"}},
    )
    text = "\n".join(validate.check_seed(contracts, broken))
    for expected in (
        "неизвестная команда 'team_ghost'", "неизвестный mentor_id 'u_ghost'", "неизвестный этап 'st_ghost'",
        "повторяется идентификатор", "onboarding_state.json: неизвестный пользователь 'u_ghost'", "неизвестная задача 't_ghost'",
        "неизвестная система 'fax'", "accesses.json: неизвестный пользователь 'u_ghost'", "contacts.json: неизвестный пользователь",
        "contacts.json: неизвестная команда", "'lost' is not one of", "неизвестный владелец", "visibility 'everyone'",
        "неизвестная команда в visibility", "нет пометки тестовой инструкции", "нет якорей", "нет поля 'title'",
        "имя файла не совпадает с id",
    ):
        assert expected in text, expected


def test_main_reports_result(capsys, monkeypatch):
    assert validate.main() == 0
    assert "Всё согласовано" in capsys.readouterr().out
    monkeypatch.setattr(validate, "run", lambda: (["что-то сломано"], "  сводка"))
    assert validate.main() == 1
    assert "что-то сломано" in capsys.readouterr().out
