import json

import httpx
import pytest

from app.ai.errors import AiError
from app.ai.providers import ollama as ollama_module
from app.ai.providers.base import (
    ChatMessage,
    Done,
    GenerationRequest,
    ProviderConfig,
    TextDelta,
    collect_text,
)
from app.ai.providers.ollama import OllamaProvider

BASE = "http://127.0.0.1:11434"


def ndjson(*chunks: dict) -> bytes:
    return ("\n".join(json.dumps(chunk) for chunk in chunks) + "\n").encode()


def token(text, **extra):
    return {"message": {"role": "assistant", "content": text}, "done": False, **extra}


DONE = {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"}


def make_provider(handler, retries=1):
    config = ProviderConfig("ollama", "tiny:1b", "local", 5.0, retries, 128)
    return OllamaProvider(config, BASE, transport=httpx.MockTransport(handler))


def make_request(temperature=None):
    messages = [ChatMessage("user", "hi"), ChatMessage("assistant", "yo")]
    return GenerationRequest("SYSTEM", messages, 128, temperature)


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(ollama_module, "_backoff", lambda attempt: 0)


async def test_streams_content_and_ignores_thinking():
    def handler(request):
        return httpx.Response(
            200,
            content=ndjson(
                {"message": {"role": "assistant", "content": "", "thinking": "hmm"}, "done": False},
                token("Hel"),
                token("lo"),
                DONE,
            ),
        )

    events = [event async for event in make_provider(handler).stream(make_request())]

    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Hel", "lo"]
    assert isinstance(events[-1], Done)


async def test_request_payload_matches_the_provider_config():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=ndjson(token("ok"), DONE))

    await collect_text(make_provider(handler), make_request(temperature=0.2))

    body = seen["body"]
    assert seen["url"] == f"{BASE}/api/chat"
    assert body["model"] == "tiny:1b"
    assert body["stream"] is True
    assert body["think"] is False
    assert body["options"] == {"num_predict": 128, "temperature": 0.2}
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant"]
    assert body["messages"][0]["content"] == "SYSTEM"


async def test_temperature_is_omitted_when_unset():
    seen = {}

    def handler(request):
        seen["options"] = json.loads(request.content)["options"]
        return httpx.Response(200, content=ndjson(token("ok"), DONE))

    await collect_text(make_provider(handler), make_request())

    assert "temperature" not in seen["options"]


async def test_error_object_is_rejected_without_detail():
    def handler(request):
        return httpx.Response(200, content=ndjson({"error": "model 'x' not found SECRET"}))

    with pytest.raises(AiError) as caught:
        await collect_text(make_provider(handler), make_request())

    assert caught.value.code == "rejected"
    assert "SECRET" not in str(caught.value)


async def test_client_error_status_is_rejected_and_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404, json={"error": "nope"})

    with pytest.raises(AiError) as caught:
        await collect_text(make_provider(handler, retries=3), make_request())

    assert caught.value.code == "rejected"
    assert len(calls) == 1


async def test_server_errors_are_retried_then_reported_unavailable():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(AiError) as caught:
        await collect_text(make_provider(handler, retries=2), make_request())

    assert caught.value.code == "unavailable"
    assert len(calls) == 3


async def test_a_retry_can_succeed():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, content=ndjson(token("recovered"), DONE))

    assert await collect_text(make_provider(handler), make_request()) == "recovered"
    assert len(calls) == 2


async def test_read_timeouts_are_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(AiError) as caught:
        await collect_text(make_provider(handler, retries=3), make_request())

    assert caught.value.code == "timeout"
    assert len(calls) == 1


async def test_failures_after_output_started_are_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, content=ndjson(token("part"), {"error": "died"}))

    provider = make_provider(handler, retries=3)
    seen = []

    with pytest.raises(AiError):
        async for event in provider.stream(make_request()):
            if isinstance(event, TextDelta):
                seen.append(event.text)

    assert seen == ["part"]
    assert len(calls) == 1


async def test_stream_without_a_done_marker_is_invalid():
    def handler(request):
        return httpx.Response(200, content=ndjson(token("cut off")))

    with pytest.raises(AiError) as caught:
        await collect_text(make_provider(handler, retries=0), make_request())

    assert caught.value.code == "invalid_response"


async def test_malformed_json_is_invalid():
    def handler(request):
        return httpx.Response(200, content=b"not json\n")

    with pytest.raises(AiError) as caught:
        await collect_text(make_provider(handler), make_request())

    assert caught.value.code == "invalid_response"


@pytest.mark.parametrize(
    "url",
    ["http://evil.example.com:11434", "http://127.0.0.1.evil.com", "file:///x", "http://10.0.0.5:11434"],
)
def test_provider_refuses_non_local_servers(url):
    config = ProviderConfig("ollama", "m", "local", 5.0, 0, 128)

    with pytest.raises(ValueError):
        OllamaProvider(config, url)


async def test_status_reports_an_installed_model():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "tiny:1b"}, {"name": "other:2b"}]})

    status = await make_provider(handler).status()

    assert status.available is True


async def test_status_reports_a_missing_model():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "other:2b"}]})

    status = await make_provider(handler).status()

    assert (status.available, status.detail) == (False, "model_not_installed")


async def test_status_reports_an_unreachable_server():
    def handler(request):
        raise httpx.ConnectError("refused")

    status = await make_provider(handler).status()

    assert (status.available, status.detail) == (False, "unavailable")


async def test_list_models_returns_names():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "a"}, {"name": "b"}]})

    assert await make_provider(handler).list_models() == ["a", "b"]
