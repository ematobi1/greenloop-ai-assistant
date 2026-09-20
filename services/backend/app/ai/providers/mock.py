import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.ai.errors import AiError
from app.ai.providers.base import (
    Done,
    GenerationRequest,
    ProviderConfig,
    ProviderStatus,
    StreamEvent,
    TextDelta,
)


@dataclass
class MockBehavior:
    chunks: list[str] | None = None
    error: AiError | None = None
    error_after_chunks: int | None = None
    delay_seconds: float = 0.0
    hang: bool = False


@dataclass
class MockProvider:
    config: ProviderConfig
    behaviors: list[MockBehavior] = field(default_factory=list)
    requests: list[GenerationRequest] = field(default_factory=list)
    models: list[str] = field(default_factory=lambda: ["mock-1"])
    available: bool = True

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        behavior = self.behaviors.pop(0) if self.behaviors else self._echo(request)
        if behavior.delay_seconds:
            await asyncio.sleep(behavior.delay_seconds)
        if behavior.hang:
            await asyncio.Event().wait()
        if behavior.error and behavior.error_after_chunks is None:
            raise behavior.error
        for index, chunk in enumerate(behavior.chunks or []):
            if behavior.error and index == behavior.error_after_chunks:
                raise behavior.error
            yield TextDelta(chunk)
            await asyncio.sleep(0)
        if behavior.error:
            raise behavior.error
        yield Done()

    async def status(self) -> ProviderStatus:
        return ProviderStatus(available=self.available, detail="mock")

    async def list_models(self) -> list[str]:
        return list(self.models)

    def _echo(self, request: GenerationRequest) -> MockBehavior:
        last_user = next(
            (message.content for message in reversed(request.messages) if message.role == "user"),
            "",
        )
        return MockBehavior(chunks=["Mock reply to: ", last_user])
