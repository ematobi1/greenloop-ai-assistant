import pytest
from pydantic import ValidationError

from app.ai.errors import HTTP_STATUS, PUBLIC_MESSAGES, AiError
from app.ai.providers.base import GenerationRequest, collect_text
from app.ai.providers.claude_cli import ClaudeCliProvider
from app.ai.providers.mock import MockBehavior
from app.ai.providers.ollama import OllamaProvider
from app.ai.providers.registry import ProviderRegistry, build_registry
from app.config import Settings
from tests.conftest import make_mock_provider


def request(text="hello"):
    from app.ai.providers.base import ChatMessage

    return GenerationRequest("system", [ChatMessage("user", text)], 64)


def test_registry_requires_the_default_provider_to_exist():
    with pytest.raises(ValueError):
        ProviderRegistry({"mock": make_mock_provider()}, "missing")


def test_unknown_provider_is_an_ai_error():
    registry = ProviderRegistry({"mock": make_mock_provider()}, "mock")

    with pytest.raises(AiError) as caught:
        registry.get("nope")

    assert caught.value.code == "unknown_provider"


def test_none_selects_the_default_provider():
    provider = make_mock_provider()

    assert ProviderRegistry({"mock": provider}, "mock").get(None) is provider


def test_build_registry_registers_both_real_providers_and_no_mock_by_default():
    registry = build_registry(Settings())

    assert registry.names == ["claude_cli", "ollama"]
    assert registry.default_name == "claude_cli"
    assert isinstance(registry.get("claude_cli"), ClaudeCliProvider)
    assert isinstance(registry.get("ollama"), OllamaProvider)


def test_mock_provider_is_only_registered_when_enabled():
    registry = build_registry(Settings(ai_enable_mock=True, ai_default_provider="mock"))

    assert "mock" in registry.names


def test_a_default_provider_that_is_not_registered_fails_startup():
    with pytest.raises(ValueError):
        build_registry(Settings(ai_default_provider="mock"))


def test_provider_config_carries_the_configured_limits():
    settings = Settings(
        ai_timeout_seconds=42,
        ai_max_retries=2,
        ai_max_output_tokens=777,
        ai_temperature=0.4,
        claude_cli_model="some-model",
        ollama_model="tiny:1b",
    )

    registry = build_registry(settings)

    for name, model, location in [
        ("claude_cli", "some-model", "cloud"),
        ("ollama", "tiny:1b", "local"),
    ]:
        config = registry.get(name).config
        assert (config.name, config.model, config.location) == (name, model, location)
        assert config.timeout_seconds == 42
        assert config.max_retries == 2
        assert config.max_output_tokens == 777
        assert config.temperature == 0.4


@pytest.mark.parametrize(
    "url", ["http://example.com:11434", "http://127.0.0.1.evil.com", "file:///etc/passwd", "ftp://127.0.0.1"]
)
def test_ollama_url_must_be_local(url):
    with pytest.raises(ValidationError):
        Settings(ollama_base_url=url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434"])
def test_local_ollama_urls_are_accepted(url):
    assert Settings(ollama_base_url=url).ollama_base_url == url.rstrip("/")


@pytest.mark.parametrize(
    "override",
    [
        {"ai_max_retries": 4},
        {"ai_max_retries": -1},
        {"ai_timeout_seconds": 0},
        {"ai_max_output_tokens": 1},
        {"ai_temperature": 3},
        {"ai_context_token_limit": 10},
        {"claude_cli_command": []},
        {"claude_cli_command": [" "]},
    ],
)
def test_invalid_ai_settings_are_rejected(override):
    with pytest.raises(ValidationError):
        Settings(**override)


def test_every_error_code_has_a_public_message_and_status():
    assert set(PUBLIC_MESSAGES) == set(HTTP_STATUS)


def test_settings_never_hold_provider_credentials():
    assert not [name for name in Settings.model_fields if "key" in name or "secret" in name]


async def test_mock_provider_echoes_by_default():
    text = await collect_text(make_mock_provider(), request("ping"))

    assert text == "Mock reply to: ping"


async def test_mock_provider_follows_scripted_chunks_and_records_requests():
    provider = make_mock_provider()
    provider.behaviors.append(MockBehavior(chunks=["a", "b", "c"]))

    assert await collect_text(provider, request()) == "abc"
    assert len(provider.requests) == 1


async def test_mock_provider_can_fail_on_demand():
    provider = make_mock_provider()
    provider.behaviors.append(MockBehavior(error=AiError("unavailable")))

    with pytest.raises(AiError) as caught:
        await collect_text(provider, request())

    assert caught.value.code == "unavailable"


async def test_empty_provider_output_is_an_invalid_response():
    provider = make_mock_provider()
    provider.behaviors.append(MockBehavior(chunks=["   "]))

    with pytest.raises(AiError) as caught:
        await collect_text(provider, request())

    assert caught.value.code == "invalid_response"
