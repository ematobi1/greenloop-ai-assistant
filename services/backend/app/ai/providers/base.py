from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from app.ai.errors import AiError

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class GenerationRequest:
    system: str
    messages: list[ChatMessage]
    max_output_tokens: int
    temperature: float | None = None


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Done:
    finish_reason: str = "stop"


StreamEvent = TextDelta | Done


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    location: Literal["local", "cloud"]
    timeout_seconds: float
    max_retries: int
    max_output_tokens: int
    temperature: float | None = None
    credential_env: str | None = None


@dataclass(frozen=True)
class ProviderStatus:
    available: bool
    detail: str = ""


class ModelProvider(Protocol):
    config: ProviderConfig

    def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]: ...

    async def status(self) -> ProviderStatus: ...

    async def list_models(self) -> list[str]: ...


async def collect_text(provider: ModelProvider, request: GenerationRequest) -> str:
    parts: list[str] = []
    async for event in provider.stream(request):
        if isinstance(event, TextDelta):
            parts.append(event.text)
    text = "".join(parts)
    if not text.strip():
        raise AiError("invalid_response")
    return text
