import asyncio
import json
import random
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx
import structlog

from app.ai.errors import AiError
from app.ai.providers.base import (
    Done,
    GenerationRequest,
    ProviderConfig,
    ProviderStatus,
    StreamEvent,
    TextDelta,
)

logger = structlog.get_logger()

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_BACKOFF_SECONDS = 2.0


def validate_loopback_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or parts.hostname not in LOOPBACK_HOSTS:
        raise ValueError("ollama_base_url must point at this machine (127.0.0.1, localhost, ::1)")
    return base_url.rstrip("/")


class OllamaProvider:
    def __init__(
        self,
        config: ProviderConfig,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.config = config
        self._base_url = validate_loopback_url(base_url)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(connect=5.0, read=self.config.timeout_seconds, write=10.0, pool=5.0)
        return httpx.AsyncClient(
            base_url=self._base_url, timeout=timeout, transport=self._transport, trust_env=False
        )

    def _payload(self, request: GenerationRequest) -> dict:
        options: dict = {"num_predict": request.max_output_tokens}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        messages = [{"role": "system", "content": request.system}]
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        return {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
            "think": False,
            "options": options,
        }

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        attempts = 1 + max(0, self.config.max_retries)
        for attempt in range(attempts):
            started = False
            try:
                async for event in self._stream_once(request):
                    started = True
                    yield event
                return
            except AiError as err:
                if started or not err.retryable or attempt == attempts - 1:
                    raise
                await asyncio.sleep(_backoff(attempt))

    async def _stream_once(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        done = False
        try:
            async with self._client() as client:
                payload = self._payload(request)
                async with client.stream("POST", "/api/chat", json=payload) as response:
                    if response.status_code >= 500:
                        raise AiError("unavailable", retryable=True)
                    if response.status_code >= 400:
                        logger.warning("ollama_rejected_request", status=response.status_code)
                        raise AiError("rejected")
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        for event in _parse_chunk(line):
                            done = done or isinstance(event, Done)
                            yield event
        except httpx.TimeoutException as err:
            raise AiError("timeout") from err
        except httpx.TransportError as err:
            raise AiError("unavailable", retryable=True) from err
        if not done:
            raise AiError("invalid_response")

    async def status(self) -> ProviderStatus:
        try:
            names = await self.list_models()
        except AiError as err:
            return ProviderStatus(available=False, detail=err.code)
        if self.config.model not in names:
            return ProviderStatus(available=False, detail="model_not_installed")
        return ProviderStatus(available=True, detail="ok")

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(3.0),
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
                return [item["name"] for item in response.json().get("models", [])]
        except httpx.TimeoutException as err:
            raise AiError("timeout") from err
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
            raise AiError("unavailable") from err


def _parse_chunk(line: str) -> list[StreamEvent]:
    try:
        chunk = json.loads(line)
    except ValueError as err:
        raise AiError("invalid_response") from err
    if not isinstance(chunk, dict):
        raise AiError("invalid_response")
    if "error" in chunk:
        logger.warning("ollama_reported_error")
        raise AiError("rejected")
    events: list[StreamEvent] = []
    content = chunk.get("message", {}).get("content", "")
    if content:
        events.append(TextDelta(content))
    if chunk.get("done"):
        events.append(Done(finish_reason=str(chunk.get("done_reason", "stop"))))
    return events


def _backoff(attempt: int) -> float:
    return min(MAX_BACKOFF_SECONDS, 0.2 * (2**attempt)) + random.uniform(0, 0.1)
