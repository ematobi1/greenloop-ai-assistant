import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import structlog
from sqlalchemy.orm import Session, sessionmaker

from app.ai.context import CHARS_PER_TOKEN, ContextBuilder
from app.ai.conversation import ConversationManager
from app.ai.errors import AiError
from app.ai.providers.base import Done, GenerationRequest, ModelProvider, TextDelta
from app.ai.providers.registry import ProviderRegistry
from app.config import Settings
from app.errors import ApiError
from app.models import Message
from app.redaction import Redactor

logger = structlog.get_logger()


@dataclass(frozen=True)
class PreparedTurn:
    owner: str
    conversation_id: str
    request_id: str
    provider: ModelProvider
    request: GenerationRequest
    user_message: Message


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class Finished:
    message: Message


@dataclass(frozen=True)
class Failed:
    error: AiError
    partial_message: Message | None


EngineEvent = Delta | Finished | Failed


class AIEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        registry: ProviderRegistry,
        context_builder: ContextBuilder,
        redactor: Redactor,
        settings: Settings,
    ):
        self._session_factory = session_factory
        self._registry = registry
        self._context_builder = context_builder
        self._redactor = redactor
        self._settings = settings

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    def prepare(
        self,
        owner: str,
        conversation_id: str,
        content: str,
        provider_name: str | None,
        request_id: str,
    ) -> PreparedTurn:
        """Validate, build the context, and store the user message. Nothing is sent yet."""
        if len(content) > self._settings.ai_max_message_chars:
            raise ApiError(
                422,
                "VALIDATION_FAILED",
                "Request validation failed",
                fields={"content": "Message is too long"},
            )
        try:
            provider = self._registry.get(provider_name)
            with self._session_factory() as session:
                manager = ConversationManager(session, owner)
                conversation = manager.get(conversation_id)
                history = manager.history(
                    conversation_id, self._settings.ai_history_message_limit
                )
                request = self._context_builder.build(history, content, conversation.instructions)
                user_message = manager.append_message(
                    conversation_id, "user", content, request_id
                )
        except AiError as err:
            raise err.to_api_error() from err
        return PreparedTurn(owner, conversation_id, request_id, provider, request, user_message)

    async def run(self, turn: PreparedTurn) -> AsyncIterator[EngineEvent]:
        provider = turn.provider
        stream = self._redactor.stream()
        emitted: list[str] = []
        emitted_chars = 0
        cap = turn.request.max_output_tokens * CHARS_PER_TOKEN
        deadline = asyncio.get_running_loop().time() + provider.config.timeout_seconds
        events = provider.stream(turn.request).__aiter__()
        failure: AiError | None = None
        try:
            while True:
                event = await self._next_event(events, deadline)
                if event is None or isinstance(event, Done):
                    break
                if isinstance(event, TextDelta):
                    safe = stream.feed(event.text)
                    if safe:
                        emitted.append(safe)
                        emitted_chars += len(safe)
                        yield Delta(safe)
                    if emitted_chars >= cap:
                        break
            tail = stream.flush()
            if tail:
                emitted.append(tail)
                yield Delta(tail)
        except AiError as err:
            failure = err
        except (asyncio.CancelledError, GeneratorExit):
            emitted.append(stream.flush())
            self._store_reply(turn, "".join(emitted), "incomplete")
            raise
        except Exception:
            logger.error("ai_engine_unexpected_error", provider=provider.config.name, exc_info=True)
            failure = AiError("unavailable")
        finally:
            await _close(events)

        emitted.append(stream.flush())
        text = "".join(emitted)
        if failure is None and not text.strip():
            failure = AiError("invalid_response")
        if failure is not None:
            logger.warning("ai_provider_failed", provider=provider.config.name, code=failure.code)
            partial = self._store_reply(turn, text, "incomplete") if text.strip() else None
            yield Failed(failure, partial)
            return
        yield Finished(self._store_reply(turn, text, "complete"))

    async def run_to_completion(self, turn: PreparedTurn) -> Message:
        async for event in self.run(turn):
            if isinstance(event, Finished):
                return event.message
            if isinstance(event, Failed):
                raise event.error.to_api_error()
        raise AiError("invalid_response").to_api_error()

    async def _next_event(self, events, deadline: float):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AiError("timeout")
        try:
            return await asyncio.wait_for(events.__anext__(), remaining)
        except StopAsyncIteration:
            return None
        except TimeoutError as err:
            raise AiError("timeout") from err

    def _store_reply(self, turn: PreparedTurn, text: str, status: str) -> Message | None:
        if not text.strip():
            return None
        config = turn.provider.config
        with self._session_factory() as session:
            return ConversationManager(session, turn.owner).append_message(
                turn.conversation_id,
                "assistant",
                text,
                turn.request_id,
                status=status,
                provider=config.name,
                model=config.model or None,
            )


async def _close(events) -> None:
    try:
        await events.aclose()
    except Exception:
        logger.warning("ai_provider_close_failed", exc_info=True)
