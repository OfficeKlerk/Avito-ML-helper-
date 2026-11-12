import json

import pytest

from app import create_app
from conftest import DATA, FIXTURES, validate


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def fixture_cases():
    for path in sorted((FIXTURES / "e_knowledge").glob("*.json")):
        fixture = json.loads(path.read_text())
        for case in fixture["cases"]:
            yield pytest.param(fixture, case, id=f"{fixture['operation']}-{case['name']}")


@pytest.mark.parametrize("fixture,case", list(fixture_cases()))
def test_existing_contract_examples_against_real_http_handlers(app, client, token, registry, fixture, case):
    headers = dict(case["request"]["headers"])
    if "Authorization" in headers:
        user_id = headers["Authorization"].split("jwt:")[1].rstrip(">")
        user = next(u for u in json.loads((DATA / "seed" / "users.json").read_text()) if u["id"] == user_id)
        headers["Authorization"] = "Bearer " + token(sub=user_id, login=user["login"], role=user["role"], team_id=user["team_id"])
    if case["kind"] == "unavailable":
        app.extensions["knowledge_base"] = None
    path = fixture["path"]
    for name, value in case["request"].get("path_params", {}).items():
        path = path.replace("{" + name + "}", value)
    response = client.open(path, method=fixture["method"], headers=headers, json=case["request"]["body"])
    expected = case["response"]
    assert response.status_code == expected["status"]
    if path.startswith("/v1/"):
        assert response.headers["Cache-Control"] == "no-store"
    if response.status_code != 200:
        validate(response.json, "common.yaml#/components/schemas/ErrorResponse", registry)
        assert response.json["error"]["code"] == expected["body"]["error"]["code"]
    elif fixture["operation"] == "health":
        validate(response.json, "common.yaml#/components/schemas/Health", registry)
    elif fixture["operation"] == "document_get":
        validate(response.json, "e_knowledge.yaml#/components/schemas/Document", registry)
        assert response.json == expected["body"]
    else:
        validate(response.json, "e_knowledge.yaml#/components/schemas/SearchResponse", registry)
        if case["kind"] == "empty":
            assert response.json == {"results": []}
        else:
            assert response.json["results"][0]["source"] == expected["body"]["results"][0]["source"]


@pytest.mark.parametrize("body", [
    {}, None, [], True, "query", {"query": 123}, {"query": None}, {"query": " "}, {"query": "x" * 1001},
    {"query": "отгул", "top_k": 0}, {"query": "отгул", "top_k": 11},
    {"query": "отгул", "top_k": True}, {"query": "отгул", "top_k": 2.5},
    {"query": "отгул", "top_k": "3"}, {"query": "отгул", "top_k": None},
    {"query": "отгул", "role": "mentor"}, {"query": "отгул", "team_id": "team_auto"},
])
def test_invalid_json_shape_and_values(client, token, body):
    response = client.post("/v1/search", json=body, headers={"Authorization": "Bearer " + token()})
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation"


@pytest.mark.parametrize("raw,content_type", [
    ('{"query":', "application/json"), ('{"query":"отгул"}', "text/plain"),
    ("x" * 65537, "application/json"),
])
def test_bad_encoding_content_type_and_body_limit(client, token, raw, content_type):
    response = client.post("/v1/search", data=raw, content_type=content_type, headers={"Authorization": "Bearer " + token()})
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation"


def test_boundaries_and_json_schema_integer(client, token):
    headers = {"Authorization": "Bearer " + token()}
    assert client.post("/v1/search", json={"query": "x" * 1000}, headers=headers).status_code == 200
    for k in [1, 3.0, 10]:
        response = client.post("/v1/search", json={"query": "доступ", "top_k": k}, headers=headers)
        assert response.status_code == 200
        assert 0 < len(response.json["results"]) <= k
    assert len(client.post("/v1/search", json={"query": "доступ"}, headers=headers).json["results"]) == 5


@pytest.mark.parametrize("header", [None, "Bearer test-token", "Basic anything"])
def test_authentication_precedes_validation(client, header):
    response = client.post("/v1/search", data="{", headers={"Authorization": header} if header else {}, content_type="application/json")
    assert response.status_code == 401


def test_expired_token_is_rejected_by_both_routes(client, token):
    headers = {"Authorization": "Bearer " + token(exp=1)}
    assert client.post("/v1/search", json={"query": "отгул"}, headers=headers).status_code == 401
    assert client.get("/v1/documents/kb_absence_rules", headers=headers).status_code == 401


def test_access_matrix_for_every_document_and_seed_user(app, client, token, registry):
    for user in json.loads((DATA / "seed" / "users.json").read_text()):
        headers = {"Authorization": "Bearer " + token(sub=user["id"], login=user["login"], role=user["role"], team_id=user["team_id"])}
        for doc in app.extensions["knowledge_base"]._documents:
            expected = "public" in doc.visibility or f"role:{user['role']}" in doc.visibility or f"team:{user['team_id']}" in doc.visibility
            response = client.get("/v1/documents/" + doc.doc_id, headers=headers)
            assert response.status_code == (200 if expected else 403)
            if expected:
                validate(response.json, "e_knowledge.yaml#/components/schemas/Document", registry)
            else:
                assert doc.doc_id not in response.text and doc.title not in response.text
        assert client.get("/v1/documents/kb_missing", headers=headers).status_code == 404


def test_unavailable_does_not_skip_authentication(app, client):
    app.extensions["knowledge_base"] = None
    assert client.post("/v1/search", json={"query": "отгул"}).status_code == 401
