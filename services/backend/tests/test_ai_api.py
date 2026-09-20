import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security.token import hash_token
from tests.conftest import LOCAL_BASE_URL, TEST_TOKEN

FAKE_CLAUDE = Path(__file__).with_name("fake_claude.py")


def test_providers_list_matches_the_contract(client, auth, contract):
    response = client.get("/v1/ai/providers", headers=auth)

    assert response.status_code == 200
    body = response.json()
    contract(body, "provider-list")
    assert body["data"] == [
        {
            "name": "mock",
            "location": "local",
            "model": "mock-1",
            "available": True,
            "detail": "mock",
            "default": True,
        }
    ]


def test_an_unavailable_provider_is_reported_not_raised(client, auth, mock_provider):
    mock_provider.available = False

    body = client.get("/v1/ai/providers", headers=auth).json()

    assert body["data"][0]["available"] is False


def test_models_list_matches_the_contract(client, auth, contract):
    response = client.get("/v1/ai/models", headers=auth)

    body = response.json()
    contract(body, "model-list")
    assert body["data"] == [{"provider": "mock", "model": "mock-1", "default": True}]


def test_models_can_be_filtered_by_provider(client, auth):
    body = client.get("/v1/ai/models?provider=mock", headers=auth).json()

    assert body["meta"]["total"] == 1


def test_models_for_an_unknown_provider_are_422(client, auth):
    response = client.get("/v1/ai/models?provider=nope", headers=auth)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_UNKNOWN_PROVIDER"


@pytest.mark.parametrize("path", ["/v1/ai/providers", "/v1/ai/models"])
def test_ai_endpoints_require_the_token(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_real_providers_report_status_without_exposing_credentials(tmp_path, monkeypatch, contract):
    secret = "sk-ant-api03-verysecretvalue0123456789abcdef"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'p.db').as_posix()}",
        api_token_hash=hash_token(TEST_TOKEN),
        claude_cli_command=[sys.executable, str(FAKE_CLAUDE)],
        claude_cli_env_passthrough=["ANTHROPIC_API_KEY", "FAKE_CLAUDE_MODE"],
        ollama_base_url="http://127.0.0.1:9",
        ollama_model="tiny:1b",
    )
    client = TestClient(create_app(settings), base_url=LOCAL_BASE_URL)
    auth = {"Authorization": f"Bearer {TEST_TOKEN}"}

    response = client.get("/v1/ai/providers", headers=auth)
    models = client.get("/v1/ai/models", headers=auth)

    body = response.json()
    contract(body, "provider-list")
    by_name = {item["name"]: item for item in body["data"]}
    assert by_name["claude_cli"]["available"] is True
    assert by_name["claude_cli"]["default"] is True
    assert by_name["claude_cli"]["location"] == "cloud"
    assert by_name["ollama"]["available"] is False
    assert by_name["ollama"]["location"] == "local"
    for text in (response.text, models.text):
        assert secret not in text
        assert "ANTHROPIC_API_KEY" not in text
