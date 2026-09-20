import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security.hosts import is_allowed_host
from app.security.token import generate_token, hash_token, token_matches
from tests.conftest import LOCAL_BASE_URL, TEST_TOKEN

PROTECTED_REQUESTS = [
    ("GET", "/v1/conversations"),
    ("POST", "/v1/conversations"),
    ("GET", "/v1/conversations/abc"),
    ("DELETE", "/v1/conversations/abc"),
    ("GET", "/v1/approvals"),
    ("POST", "/v1/approvals"),
    ("GET", "/v1/approvals/abc"),
    ("POST", "/v1/approvals/abc/decision"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED_REQUESTS)
def test_protected_routes_reject_missing_token(client, contract, method, path):
    response = client.request(method, path)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    contract(response.json(), "error")
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(
    "header",
    [
        "Bearer wrong-token",
        "Bearer ",
        f"Basic {TEST_TOKEN}",
        TEST_TOKEN,
    ],
)
def test_protected_routes_reject_bad_credentials(client, header):
    response = client.get("/v1/conversations", headers={"Authorization": header})

    assert response.status_code == 401


def test_valid_token_is_accepted(client, auth):
    assert client.get("/v1/conversations", headers=auth).status_code == 200


def test_fails_closed_when_no_token_is_configured(tmp_path):
    unconfigured = Settings(database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    client = TestClient(create_app(unconfigured), base_url=LOCAL_BASE_URL)

    for candidate in ("", TEST_TOKEN, "anything"):
        response = client.get("/v1/conversations", headers={"Authorization": f"Bearer {candidate}"})
        assert response.status_code == 401


def test_token_is_never_logged(client, auth, capsys):
    client.get("/v1/conversations", headers=auth)
    client.get("/v1/conversations", headers={"Authorization": "Bearer wrong-secret-value"})

    output = capsys.readouterr().out
    assert TEST_TOKEN not in output
    assert "wrong-secret-value" not in output


def test_foreign_host_is_rejected(client, contract):
    response = client.get("/v1/health", headers={"Host": "evil.example.com"})

    assert response.status_code == 400
    contract(response.json(), "error")
    assert response.json()["error"]["code"] == "INVALID_HOST"


def test_foreign_host_is_rejected_even_with_valid_token(client, auth):
    response = client.get("/v1/conversations", headers={**auth, "Host": "rebind.example.com"})

    assert response.status_code == 400


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.0.0.1:8787", True),
        ("localhost:5173", True),
        ("evil.com", False),
        ("127.0.0.1.evil.com", False),
        ("evil.com:127.0.0.1", False),
        ("", False),
        ("[::1]:8787", False),
        ("127.0.0.1:notaport", False),
    ],
)
def test_is_allowed_host(host, expected):
    assert is_allowed_host(host, ["127.0.0.1", "localhost"]) is expected


def test_generated_tokens_are_unique_and_long():
    tokens = {generate_token() for _ in range(50)}

    assert len(tokens) == 50
    assert all(len(token) >= 43 for token in tokens)


def test_token_hash_round_trip():
    token = generate_token()
    stored = hash_token(token)

    assert token not in stored
    assert token_matches(token, stored)
    assert not token_matches(token + "x", stored)


def test_malformed_stored_hash_never_matches():
    assert not token_matches("token", "not-a-real-hash")
    assert not token_matches("token", "é")
