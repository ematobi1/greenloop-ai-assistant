from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import LOCAL_BASE_URL


def test_health_ok_matches_contract(client, contract):
    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    contract(body, "health")
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_health_needs_no_token(client):
    assert client.get("/v1/health").status_code == 200


def test_health_degraded_when_database_unavailable(tmp_path, contract):
    unreachable = Settings(database_url=f"sqlite:///{tmp_path.as_posix()}")

    response = TestClient(create_app(unreachable), base_url=LOCAL_BASE_URL).get("/v1/health")

    assert response.status_code == 503
    body = response.json()
    contract(body, "health")
    assert body["status"] == "degraded"
    assert body["database"] == "error"
    assert "Traceback" not in response.text


def test_response_carries_request_id(client):
    first = client.get("/v1/health").headers["X-Request-ID"]
    second = client.get("/v1/health").headers["X-Request-ID"]

    assert first and second and first != second


def test_unhandled_error_hides_internals(settings):
    app = create_app(settings)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    response = TestClient(app, base_url=LOCAL_BASE_URL, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.text


def test_cors_allows_dashboard_origin(client):
    response = client.get("/v1/health", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_unknown_route_uses_error_shape(client, contract):
    response = client.get("/v1/nope")

    assert response.status_code == 404
    contract(response.json(), "error")
