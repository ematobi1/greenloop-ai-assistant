from app.ai.errors import AiError
from app.ai.providers.base import ModelProvider, ProviderConfig
from app.ai.providers.claude_cli import ClaudeCliProvider
from app.ai.providers.mock import MockProvider
from app.ai.providers.ollama import OllamaProvider
from app.config import Settings


class ProviderRegistry:
    def __init__(self, providers: dict[str, ModelProvider], default: str):
        if default not in providers:
            raise ValueError(f"default provider '{default}' is not registered")
        self._providers = providers
        self.default_name = default

    @property
    def names(self) -> list[str]:
        return list(self._providers)

    def get(self, name: str | None) -> ModelProvider:
        provider = self._providers.get(name or self.default_name)
        if provider is None:
            raise AiError("unknown_provider")
        return provider


def _config(settings: Settings, name: str, model: str, location: str) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        model=model,
        location=location,
        timeout_seconds=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
        max_output_tokens=settings.ai_max_output_tokens,
        temperature=settings.ai_temperature,
    )


def build_registry(settings: Settings) -> ProviderRegistry:
    providers: dict[str, ModelProvider] = {
        "claude_cli": ClaudeCliProvider(
            _config(settings, "claude_cli", settings.claude_cli_model, "cloud"),
            command=settings.claude_cli_command,
            env_passthrough=settings.claude_cli_env_passthrough,
        ),
        "ollama": OllamaProvider(
            _config(settings, "ollama", settings.ollama_model, "local"),
            base_url=settings.ollama_base_url,
        ),
    }
    if settings.ai_enable_mock:
        providers["mock"] = MockProvider(_config(settings, "mock", "mock-1", "local"))
    return ProviderRegistry(providers, settings.ai_default_provider)
