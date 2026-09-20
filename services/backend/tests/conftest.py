import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from app.config import Settings
from app.main import create_app
from app.security.token import hash_token

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
TEST_TOKEN = "test-token-for-gate-tests"
LOCAL_BASE_URL = "http://127.0.0.1"


def load_contracts() -> dict[str, dict]:
    schemas = {}
    for path in CONTRACTS_DIR.glob("*.schema.json"):
        schemas[path.name.removesuffix(".schema.json")] = json.loads(
            path.read_text(encoding="utf-8")
        )
    return schemas


@pytest.fixture(scope="session")
def contract() -> Callable[[object, str], None]:
    schemas = load_contracts()
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )

    def assert_matches(instance: object, name: str) -> None:
        Draft202012Validator(schemas[name], registry=registry).validate(instance)

    return assert_matches


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        api_token_hash=hash_token(TEST_TOKEN),
    )


@pytest.fixture
def app(settings):
    from alembic import command

    from tests.migration_helpers import alembic_config

    command.upgrade(alembic_config(settings.database_url), "head")
    return create_app(settings)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, base_url=LOCAL_BASE_URL)


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
