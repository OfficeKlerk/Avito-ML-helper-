import copy
import json
import os
from pathlib import Path

import pytest

from app import create_app
from app.tools import Tools

FIXTURES_DIR = Path(os.environ.get("FIXTURES_DIR") or Path(__file__).resolve().parents[2] / "fixtures")


def fixture_case(path: str, kind: str = "success") -> dict:
    """Первый пример нужного вида из `fixtures/<path>.json`."""
    data = json.loads((FIXTURES_DIR / f"{path}.json").read_text(encoding="utf-8"))
    return copy.deepcopy(next(c for c in data["cases"] if c["kind"] == kind))


def default_responses() -> dict:
    """Ответы инструментов по умолчанию — успешные примеры контрактов C и E."""
    return {
        "knowledge_search": fixture_case("e_knowledge/search")["response"]["body"]["results"],
        "absence_create_draft": fixture_case("c_mcp_tools/absence_create_draft")["response"]["body"],
        "directory_find_contact": fixture_case("c_mcp_tools/directory_find_contact")["response"]["body"],
    }


class FakeTools(Tools):
    """Инструменты без сети: ответ или исключение берётся из `responses`, trace ведётся как у настоящих."""

    def __init__(self, responses: dict, token: str = "test-token", request_id: str = "rq-test-0001"):
        super().__init__("http://kb.invalid", "http://mcp.invalid/mcp", token, request_id)
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def search(self, query, top_k=3):
        self.calls.append(("knowledge_search", {"query": query, "top_k": top_k}))
        return self.traced("knowledge_search", lambda: self._respond("knowledge_search"))

    def _mcp(self, tool, arguments):
        self.calls.append((tool, arguments))
        result = self._respond(tool)
        if tool == "absence_create_draft":  # как настоящий corp-mock: черновик хранит переданные даты
            result["payload"] = {"kind": arguments["kind"], "date_from": arguments["date_from"],
                                 "date_to": arguments["date_to"], "comment": None}
        return result

    def _respond(self, name):
        value = self.responses[name]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


@pytest.fixture()
def tools_responses():
    return default_responses()


@pytest.fixture()
def made_tools():
    return []


@pytest.fixture()
def client(tools_responses, made_tools):
    def factory(token, request_id):
        tools = FakeTools(tools_responses, token, request_id)
        made_tools.append(tools)
        return tools

    return create_app(factory, lambda: None).test_client()
