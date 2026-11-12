import json
import time
from dataclasses import replace

import jwt
import pytest

from app import create_app
from app.access import KnowledgeAccessError, authenticate, can_read
from app.knowledge import KnowledgeBase, knowledge_for_request
from app.loader import CorpusLoadError
from conftest import DATA, SECRET


@pytest.fixture
def knowledge():
    return KnowledgeBase.load(DATA / "kb")


def test_signed_claims_match_contract(token):
    principal = authenticate("bearer " + token(), SECRET)
    assert (principal.user_id, principal.login, principal.role, principal.team_id) == ("u_anna", "intern_anna", "intern", "team_delivery")


@pytest.mark.parametrize("header", [None, "", "test-token", "Basic whatever", "Bearer", "Bearer token extra", "Bearer invalid"])
def test_invalid_header_fails_closed(header):
    with pytest.raises(KnowledgeAccessError) as error:
        authenticate(header, SECRET)
    assert error.value.status == 401


@pytest.mark.parametrize("claims", [
    {"exp": 1}, {"exp": True}, {"exp": "9999999999"}, {"exp": None},
    {"exp": float("inf")}, {"exp": float("nan")}, {"nbf": int(time.time()) + 7200},
    {"sub": "admin"}, {"sub": 12}, {"role": "admin"}, {"role": ["mentor"]},
    {"team_id": "delivery"}, {"team_id": []}, {"login": ""}, {"login": False},
])
def test_invalid_claims_are_unauthorized(token, claims):
    with pytest.raises(KnowledgeAccessError) as error:
        authenticate("Bearer " + token(**claims), SECRET)
    assert error.value.status == 401


@pytest.mark.parametrize("missing", ["sub", "login", "role", "team_id", "exp"])
def test_all_identity_claims_are_required(token, missing):
    with pytest.raises(KnowledgeAccessError):
        authenticate("Bearer " + token(omit=(missing,)), SECRET)


def test_forged_signature_and_algorithms_are_rejected(token):
    for value in [token(secret="different-secret-at-least-thirty-two-bytes"), token(secret=SECRET * 2, algorithm="HS512"), token(secret=None, algorithm="none")]:
        with pytest.raises(KnowledgeAccessError):
            authenticate("Bearer " + value, SECRET)
    original = token()
    header, payload, signature = original.split(".")
    claims = json.loads(jwt.utils.base64url_decode(payload))
    claims["role"] = "mentor"
    forged_payload = jwt.utils.base64url_encode(json.dumps(claims).encode()).decode()
    with pytest.raises(KnowledgeAccessError):
        authenticate(f"Bearer {header}.{forged_payload}.{signature}", SECRET)


@pytest.mark.parametrize("secret", ["", "   ", None])
def test_secret_must_be_configured(token, secret):
    with pytest.raises(ValueError, match="JWT_SECRET"):
        authenticate("Bearer " + token(), secret)


def test_each_seed_user_only_sees_permitted_documents(knowledge, token):
    users = json.loads((DATA / "seed" / "users.json").read_text())
    for user in users:
        view = knowledge.authorize("Bearer " + token(sub=user["id"], login=user["login"], role=user["role"], team_id=user["team_id"]), jwt_secret=SECRET)
        docs = {d.doc_id for d in view.documents()}
        expected = {"kb_absence_rules", "kb_access_howto", "kb_onboarding_first_weeks",
                    "kb_access_statuses", "kb_absence_handover", "kb_onboarding_blockers"}
        if user["team_id"] == "team_delivery":
            expected |= {"kb_delivery_dev_setup", "kb_delivery_rituals", "kb_who_is_who_delivery", "kb_delivery_access"}
        if user["team_id"] == "team_auto":
            expected |= {"kb_auto_frontend_setup", "kb_auto_release_process", "kb_auto_access"}
        if user["role"] == "mentor":
            expected.add("kb_mentor_guide")
        assert docs == expected
        assert {c.document.doc_id for c in view.chunks()} == expected


def test_access_rules_are_or_without_manager_override(token):
    principal = authenticate("Bearer " + token(), SECRET)
    assert can_read(("team:team_auto", "role:intern"), principal)
    assert not can_read(("role:mentor",), replace(principal, role="manager"))
    assert not can_read(("invalid",), principal)


def test_direct_access_and_separate_request_views(knowledge, token):
    anna = knowledge.authorize("Bearer " + token(), jwt_secret=SECRET)
    max_view = knowledge.authorize("Bearer " + token(sub="u_max", team_id="team_auto"), jwt_secret=SECRET)
    assert anna.document("kb_delivery_rituals").doc_id == "kb_delivery_rituals"
    for doc_id, expected_status in [("kb_delivery_rituals", 403), ("kb_missing", 404), ("../../etc/passwd", 404)]:
        with pytest.raises(KnowledgeAccessError) as error:
            max_view.document(doc_id)
        assert error.value.status == expected_status and doc_id not in str(error.value)
    assert "kb_delivery_rituals" not in {c.document.doc_id for c in max_view.chunks()}


def test_flask_adapter_ignores_body_and_headers_claiming_other_rights(token):
    app = create_app()
    # Test-only route exercises the production adapter/error mapping. K5 adds real routes.
    @app.post("/probe/<doc_id>")
    def probe(doc_id):
        return knowledge_for_request().document(doc_id).to_dict()
    client = app.test_client()
    headers = {"Authorization": "Bearer " + token(), "X-Role": "mentor", "X-Team-Id": "team_auto"}
    assert client.post("/probe/kb_absence_rules").status_code == 401
    response = client.post("/probe/kb_mentor_guide", headers=headers, json={"role": "mentor", "visibility": ["public"]})
    assert response.status_code == 403
    assert response.json == {"error": {"code": "forbidden", "message": "Нет доступа."}}
    assert client.post("/probe/kb_missing", headers=headers).status_code == 404
    assert client.post("/probe/kb_absence_rules", headers=headers).status_code == 200


def test_startup_requires_secret_and_valid_corpus(monkeypatch, tmp_path, raw_document):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(ValueError, match="JWT_SECRET"):
        create_app()
    monkeypatch.setenv("JWT_SECRET", SECRET)
    with pytest.raises(CorpusLoadError):
        create_app({"KB_DIR": str(tmp_path)})
    (tmp_path / "kb_absence_rules.md").write_text(raw_document.replace("{#day-off}", ""))
    with pytest.raises(CorpusLoadError, match="kb_absence_rules.md"):
        create_app({"KB_DIR": str(tmp_path)})


def test_all_sections_are_validated_before_corpus_is_published(tmp_path, raw_document):
    (tmp_path / "kb_absence_rules.md").write_text(raw_document.replace("{#day-off}", "{#vacation}"))
    (tmp_path / "kb_other.md").write_text(raw_document.replace("kb_absence_rules", "kb_other").replace("{#day-off}", ""))
    with pytest.raises(CorpusLoadError) as error:
        KnowledgeBase.load(tmp_path)
    assert len(error.value.issues) == 2
