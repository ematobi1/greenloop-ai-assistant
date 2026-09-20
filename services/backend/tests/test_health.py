import json
from pathlib import Path

import jsonschema
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "health.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_health_ok_matches_contract(client):
    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    jsonschema.validate(body, SCHEMA)
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_health_degraded_when_database_unavailable(tmp_path):
    unreachable = Settings(database_url=f"sqlite:///{tmp_path.as_posix()}")

    response = TestClient(create_app(unreachable)).get("/v1/health")

    assert response.status_code == 503
    body = response.json()
    jsonschema.validate(body, SCHEMA)
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

    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.text


def test_cors_allows_dashboard_origin(client):
    response = client.get("/v1/health", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
