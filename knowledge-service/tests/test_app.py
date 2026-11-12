import pytest

from app import SERVICE, create_app, error_response


@pytest.fixture()
def app():
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("сломалось")

    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": SERVICE, "version": "0.1.0"}
    assert SERVICE == "knowledge-service"


def test_unknown_route_uses_contract_error_format(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.get_json() == {"error": {"code": "not_found", "message": "Не найдено."}}


def test_wrong_method_is_not_found(client):
    assert client.post("/health").get_json()["error"]["code"] == "not_found"


def test_unexpected_error_hides_details(client):
    response = client.get("/boom")
    assert response.status_code == 500
    body = response.get_json()
    assert body["error"]["code"] == "internal"
    assert "сломалось" not in body["error"]["message"]


def test_error_response_with_custom_message(app):
    with app.app_context():
        response, status = error_response(403, "Этот документ тебе недоступен.")
    assert status == 403
    assert response.get_json() == {"error": {"code": "forbidden", "message": "Этот документ тебе недоступен."}}
