import asyncio

import pytest
from sqlalchemy import select

from app.ai.engine import Delta, Failed, Finished
from app.ai.errors import AiError
from app.ai.providers.mock import MockBehavior
from app.ai.providers.registry import ProviderRegistry
from app.errors import ApiError
from app.main import create_app
from app.models import AuditEvent, Message
from app.redaction import REDACTED
from app.security.principal import LOCAL_PRINCIPAL
from tests.conftest import make_mock_provider

SECRET = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
WORDS = "word " * 120


def new_conversation(app, title="chat", instructions=None) -> str:
    from app.ai.conversation import ConversationManager

    with app.state.session_factory() as session:
        return ConversationManager(session, LOCAL_PRINCIPAL).create(title, instructions, "r" * 32).id


def stored_messages(app, conversation_id):
    with app.state.session_factory() as session:
        return list(
            session.scalars(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.sequence)
            )
        )


def prepare(app, conversation_id, content="hello", provider=None):
    return app.state.ai_engine.prepare(LOCAL_PRINCIPAL, conversation_id, content, provider, "q" * 32)


async def run_all(app, turn):
    return [event async for event in app.state.ai_engine.run(turn)]


async def test_reply_streams_then_finishes_and_is_stored(app, mock_provider):
    mock_provider.behaviors.append(MockBehavior(chunks=["Hel", "lo ", "there"]))
    conversation_id = new_conversation(app)

    events = await run_all(app, prepare(app, conversation_id))

    assert "".join(e.text for e in events if isinstance(e, Delta)) == "Hello there"
    assert isinstance(events[-1], Finished)
    stored = stored_messages(app, conversation_id)
    assert [(m.sequence, m.role, m.status) for m in stored] == [
        (1, "user", "complete"),
        (2, "assistant", "complete"),
    ]
    assert stored[1].content == "Hello there"
    assert (stored[1].provider, stored[1].model) == ("mock", "mock-1")


async def test_secrets_in_model_output_are_redacted_in_stream_and_storage(app, mock_provider):
    half = len(SECRET) // 2
    mock_provider.behaviors.append(
        MockBehavior(chunks=["My key is ", SECRET[:half], SECRET[half:], " thanks"])
    )
    conversation_id = new_conversation(app)

    events = await run_all(app, prepare(app, conversation_id))

    streamed = "".join(e.text for e in events if isinstance(e, Delta))
    assert SECRET not in streamed
    assert REDACTED in streamed
    assert SECRET not in stored_messages(app, conversation_id)[1].content


async def test_provider_failure_before_any_text_stores_no_reply(app, mock_provider):
    mock_provider.behaviors.append(MockBehavior(error=AiError("unavailable")))
    conversation_id = new_conversation(app)

    events = await run_all(app, prepare(app, conversation_id))

    assert isinstance(events[-1], Failed)
    assert events[-1].error.code == "unavailable"
    assert events[-1].partial_message is None
    assert [m.role for m in stored_messages(app, conversation_id)] == ["user"]


async def test_failure_midway_keeps_the_partial_reply_as_incomplete(app, mock_provider):
    mock_provider.behaviors.append(
        MockBehavior(chunks=["partial ", "answer"], error=AiError("unavailable"), error_after_chunks=2)
    )
    conversation_id = new_conversation(app)

    events = await run_all(app, prepare(app, conversation_id))

    failed = events[-1]
    assert isinstance(failed, Failed)
    assert failed.partial_message.content == "partial answer"
    assert failed.partial_message.status == "incomplete"
    assert stored_messages(app, conversation_id)[1].status == "incomplete"


async def test_incomplete_replies_are_not_fed_back_into_later_context(app, mock_provider):
    mock_provider.behaviors.append(
        MockBehavior(chunks=["half"], error=AiError("unavailable"), error_after_chunks=1)
    )
    conversation_id = new_conversation(app)
    await run_all(app, prepare(app, conversation_id, "first"))

    await run_all(app, prepare(app, conversation_id, "second"))

    sent = mock_provider.requests[-1].messages
    assert [m.content for m in sent] == ["first", "second"]


async def test_a_slow_provider_times_out_and_keeps_what_it_sent(settings):
    provider = make_mock_provider(timeout_seconds=0.3)
    provider.behaviors.append(MockBehavior(chunks=["early"], delay_seconds=0))
    provider.behaviors.append(MockBehavior(hang=True))
    app = _app_with(settings, provider)
    conversation_id = new_conversation(app)

    await run_all(app, prepare(app, conversation_id, "one"))
    events = await run_all(app, prepare(app, conversation_id, "two"))

    assert isinstance(events[-1], Failed)
    assert events[-1].error.code == "timeout"
    assert [m.role for m in stored_messages(app, conversation_id)][-1] == "user"


def _app_with(settings, provider):
    from alembic import command

    from tests.migration_helpers import alembic_config

    command.upgrade(alembic_config(settings.database_url), "head")
    return create_app(settings, ProviderRegistry({"mock": provider}, "mock"))


async def test_closing_the_stream_early_stores_the_partial_reply(app, mock_provider):
    mock_provider.behaviors.append(MockBehavior(chunks=[WORDS, WORDS, WORDS]))
    conversation_id = new_conversation(app)
    events = app.state.ai_engine.run(prepare(app, conversation_id))

    first = await events.__anext__()
    await events.aclose()

    assert isinstance(first, Delta)
    stored = stored_messages(app, conversation_id)
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[1].status == "incomplete"
    assert stored[1].content.startswith("word")


async def test_cancelling_the_task_stores_the_partial_reply(app, mock_provider):
    mock_provider.behaviors.append(MockBehavior(chunks=[WORDS, WORDS, WORDS]))
    conversation_id = new_conversation(app)
    started = asyncio.Event()

    async def consume():
        events = app.state.ai_engine.run(prepare(app, conversation_id))
        try:
            async for event in events:
                if isinstance(event, Delta):
                    started.set()
                    await asyncio.sleep(10)
        finally:
            await events.aclose()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    stored = stored_messages(app, conversation_id)
    assert stored[-1].role == "assistant"
    assert stored[-1].status == "incomplete"


async def test_output_is_capped_at_the_configured_limit(settings, mock_provider):
    app = _app_with(settings.model_copy(update={"ai_max_output_tokens": 256}), mock_provider)
    limit_chars = 256 * 4
    mock_provider.behaviors.append(MockBehavior(chunks=[WORDS] * 20))
    conversation_id = new_conversation(app)

    events = await run_all(app, prepare(app, conversation_id))

    assert isinstance(events[-1], Finished)
    assert len(events[-1].message.content) < limit_chars + 2 * len(WORDS)


async def test_an_empty_reply_is_a_failure(app, mock_provider):
    mock_provider.behaviors.append(MockBehavior(chunks=[]))
    conversation_id = new_conversation(app)

    events = await run_all(app, prepare(app, conversation_id))

    assert events[-1].error.code == "invalid_response"


async def test_unexpected_provider_exceptions_become_a_generic_failure(app, mock_provider):
    class Boom(Exception):
        pass

    mock_provider.behaviors.append(MockBehavior(chunks=["ok"], error=Boom("internal secret"), error_after_chunks=1))
    conversation_id = new_conversation(app)

    events = await run_all(app, prepare(app, conversation_id))

    failed = events[-1]
    assert failed.error.code == "unavailable"
    assert "internal secret" not in failed.error.public_message


async def test_prepare_rejects_a_context_that_cannot_fit_and_stores_nothing(settings, mock_provider):
    tight = settings.model_copy(update={"ai_context_token_limit": 800})
    app = _app_with(tight, mock_provider)
    conversation_id = new_conversation(app)

    with pytest.raises(ApiError) as caught:
        prepare(app, conversation_id, "x" * 8000)

    assert caught.value.status_code == 422
    assert caught.value.code == "AI_CONTEXT_TOO_LARGE"
    assert stored_messages(app, conversation_id) == []


async def test_prepare_rejects_over_long_messages(settings, mock_provider):
    app = _app_with(settings.model_copy(update={"ai_max_message_chars": 50}), mock_provider)
    conversation_id = new_conversation(app)

    with pytest.raises(ApiError) as caught:
        prepare(app, conversation_id, "x" * 51)

    assert caught.value.fields == {"content": "Message is too long"}
    assert stored_messages(app, conversation_id) == []


async def test_prepare_rejects_unknown_providers(app):
    conversation_id = new_conversation(app)

    with pytest.raises(ApiError) as caught:
        prepare(app, conversation_id, provider="nope")

    assert caught.value.code == "AI_UNKNOWN_PROVIDER"
    assert stored_messages(app, conversation_id) == []


async def test_conversation_instructions_reach_the_system_prompt_only(app, mock_provider):
    conversation_id = new_conversation(app, instructions="Answer in French")

    await run_all(app, prepare(app, conversation_id, "bonjour"))

    request = mock_provider.requests[0]
    assert "<user_preferences>\nAnswer in French\n</user_preferences>" in request.system
    assert "Answer in French" not in "".join(m.content for m in request.messages)


async def test_each_stored_message_writes_an_audit_event(app):
    conversation_id = new_conversation(app)

    await run_all(app, prepare(app, conversation_id))

    with app.state.session_factory() as session:
        actions = list(session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at)))
    assert actions == ["conversation.create", "message.user", "message.assistant"]

