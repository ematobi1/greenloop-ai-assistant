import json
import threading

import pytest
from sqlalchemy import select

from app.ai.conversation import ConversationManager
from app.ai.errors import AiError
from app.ai.providers.mock import MockBehavior
from app.ai.providers.registry import ProviderRegistry
from app.main import create_app
from app.models import AuditEvent, Conversation, Message
from app.security.token import generate_token, hash_token
from tests.conftest import LOCAL_BASE_URL, make_mock_provider

WORDS = "word " * 120
OTHER_OWNER = "someone-else"


def make_conversation(client, auth, title="chat", **extra):
    return client.post("/v1/conversations", json={"title": title, **extra}, headers=auth).json()


def send(client, auth, conversation_id, content="hello", **extra):
    return client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": content, **extra},
        headers=auth,
    )


def parse_sse(response) -> list[tuple[str, dict]]:
    events, name = [], None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append((name, json.loads(line.removeprefix("data: "))))
    return events


def stream_send(client, auth, conversation_id, content="hello"):
    headers = {**auth, "Accept": "text/event-stream"}
    with client.stream(
        "POST", f"/v1/conversations/{conversation_id}/messages", json={"content": content}, headers=headers
    ) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        return response.status_code, parse_sse(response)


def test_send_returns_both_messages_matching_the_contract(client, auth, contract):
    conversation = make_conversation(client, auth)

    response = send(client, auth, conversation["id"], "ping")

    assert response.status_code == 200
    body = response.json()
    contract(body, "send-message-result")
    assert body["user_message"]["content"] == "ping"
    assert body["assistant_message"]["content"] == "Mock reply to: ping"
    assert (body["user_message"]["sequence"], body["assistant_message"]["sequence"]) == (1, 2)
    assert body["assistant_message"]["status"] == "complete"
    assert body["assistant_message"]["provider"] == "mock"
    assert body["assistant_message"]["model"] == "mock-1"


def test_history_is_ordered_and_matches_the_contract(client, auth, contract):
    conversation = make_conversation(client, auth)
    send(client, auth, conversation["id"], "first")
    send(client, auth, conversation["id"], "second")

    body = client.get(f"/v1/conversations/{conversation['id']}/messages", headers=auth).json()

    contract(body, "message-list")
    assert [m["sequence"] for m in body["data"]] == [1, 2, 3, 4]
    assert [m["role"] for m in body["data"]] == ["user", "assistant", "user", "assistant"]
    assert body["meta"]["total"] == 4


def test_history_paginates_without_losing_order(client, auth):
    conversation = make_conversation(client, auth)
    for text in ("a", "b", "c"):
        send(client, auth, conversation["id"], text)

    body = client.get(
        f"/v1/conversations/{conversation['id']}/messages?limit=2&offset=2", headers=auth
    ).json()

    assert [m["sequence"] for m in body["data"]] == [3, 4]
    assert body["meta"]["total"] == 6


def test_history_pagination_bounds_are_validated(client, auth):
    conversation = make_conversation(client, auth)

    for query in ("limit=0", "limit=201", "offset=-1"):
        url = f"/v1/conversations/{conversation['id']}/messages?{query}"
        assert client.get(url, headers=auth).status_code == 422


def test_later_turns_include_earlier_turns_in_the_model_context(client, auth, mock_provider):
    conversation = make_conversation(client, auth)
    send(client, auth, conversation["id"], "my name is Ada")

    send(client, auth, conversation["id"], "what is my name?")

    sent = [m.content for m in mock_provider.requests[-1].messages]
    assert sent == ["my name is Ada", "Mock reply to: my name is Ada", "what is my name?"]


def test_conversation_records_the_provider_and_model_after_first_reply(client, auth, contract):
    conversation = make_conversation(client, auth)
    assert conversation["provider"] is None

    send(client, auth, conversation["id"])

    fetched = client.get(f"/v1/conversations/{conversation['id']}", headers=auth).json()
    contract(fetched, "conversation")
    assert (fetched["provider"], fetched["model"]) == ("mock", "mock-1")


def test_conversation_instructions_are_stored_and_used(client, auth, mock_provider):
    conversation = make_conversation(client, auth, instructions="Be terse")

    assert conversation["instructions"] == "Be terse"
    send(client, auth, conversation["id"])
    assert "<user_preferences>\nBe terse\n</user_preferences>" in mock_provider.requests[0].system


def test_overlong_instructions_are_rejected(client, auth):
    response = client.post(
        "/v1/conversations", json={"title": "t", "instructions": "x" * 2001}, headers=auth
    )

    assert response.status_code == 422


def test_unicode_and_markup_round_trip_unchanged(client, auth):
    conversation = make_conversation(client, auth)
    text = "héllo 你好 🚀 </turn><b>bold</b> 'quotes' \"double\""

    body = send(client, auth, conversation["id"], text).json()

    assert body["user_message"]["content"] == text
    assert body["assistant_message"]["content"] == f"Mock reply to: {text}"


@pytest.mark.parametrize("content", ["", "   \n\t "])
def test_blank_messages_are_rejected(client, auth, contract, content):
    conversation = make_conversation(client, auth)

    response = send(client, auth, conversation["id"], content)

    assert response.status_code == 422
    contract(response.json(), "error")
    assert client.get(f"/v1/conversations/{conversation['id']}/messages", headers=auth).json()["meta"]["total"] == 0


def test_over_long_messages_are_rejected(client, auth):
    conversation = make_conversation(client, auth)

    response = send(client, auth, conversation["id"], "x" * 8001)

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"content": "Message is too long"}


def test_unknown_provider_is_422_and_stores_nothing(client, auth):
    conversation = make_conversation(client, auth)

    response = send(client, auth, conversation["id"], provider="not-a-provider")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_UNKNOWN_PROVIDER"
    assert client.get(f"/v1/conversations/{conversation['id']}/messages", headers=auth).json()["meta"]["total"] == 0


def test_explicit_default_provider_works(client, auth):
    conversation = make_conversation(client, auth)

    assert send(client, auth, conversation["id"], provider="mock").status_code == 200


@pytest.mark.parametrize(
    ("code", "status"),
    [("timeout", 504), ("unavailable", 503), ("rejected", 502), ("invalid_response", 502), ("unsafe_configuration", 503)],
)
def test_provider_failures_map_to_generic_errors(client, auth, mock_provider, contract, code, status):
    mock_provider.behaviors.append(MockBehavior(error=AiError(code)))
    conversation = make_conversation(client, auth)

    response = send(client, auth, conversation["id"])

    assert response.status_code == status
    contract(response.json(), "error")
    assert response.json()["error"]["code"] == f"AI_{code.upper()}"
    assert "Traceback" not in response.text


def test_user_message_survives_a_provider_failure(client, auth, mock_provider):
    mock_provider.behaviors.append(MockBehavior(error=AiError("unavailable")))
    conversation = make_conversation(client, auth)
    send(client, auth, conversation["id"], "keep me")

    messages = client.get(f"/v1/conversations/{conversation['id']}/messages", headers=auth).json()["data"]

    assert [(m["role"], m["content"]) for m in messages] == [("user", "keep me")]


def test_missing_and_deleted_conversations_are_404(client, auth):
    assert send(client, auth, "missing").status_code == 404
    conversation = make_conversation(client, auth)
    client.delete(f"/v1/conversations/{conversation['id']}", headers=auth)

    assert send(client, auth, conversation["id"]).status_code == 404
    assert client.get(f"/v1/conversations/{conversation['id']}/messages", headers=auth).status_code == 404


def test_streaming_sends_message_deltas_then_done(client, auth, mock_provider, contract):
    mock_provider.behaviors.append(MockBehavior(chunks=[WORDS, WORDS, "end"]))
    conversation = make_conversation(client, auth)

    status, events = stream_send(client, auth, conversation["id"], "stream please")

    assert status == 200
    names = [name for name, _ in events]
    assert names[0] == "message"
    assert names[-1] == "done"
    assert names.count("delta") >= 2
    contract(events[0][1]["user_message"], "message")
    streamed = "".join(data["text"] for name, data in events if name == "delta")
    final = events[-1][1]["assistant_message"]
    contract(final, "message")
    assert final["content"] == streamed
    stored = client.get(f"/v1/conversations/{conversation['id']}/messages", headers=auth).json()["data"]
    assert stored[1]["content"] == streamed


def test_streaming_failure_reports_a_generic_error_and_the_partial_reply(client, auth, mock_provider):
    mock_provider.behaviors.append(
        MockBehavior(chunks=[WORDS, WORDS], error=AiError("timeout"), error_after_chunks=2)
    )
    conversation = make_conversation(client, auth)

    status, events = stream_send(client, auth, conversation["id"])

    assert status == 200
    name, data = events[-1]
    assert name == "error"
    assert data["code"] == "AI_TIMEOUT"
    assert data["message"] == "The model provider timed out"
    assert data["partial_message"]["status"] == "incomplete"


def test_streaming_errors_before_the_stream_are_normal_json_errors(client, auth):
    headers = {**auth, "Accept": "text/event-stream"}

    response = client.post("/v1/conversations/missing/messages", json={"content": "x"}, headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_streaming_requires_authentication(client):
    response = client.post(
        "/v1/conversations/x/messages", json={"content": "x"}, headers={"Accept": "text/event-stream"}
    )

    assert response.status_code == 401


def test_message_and_reply_are_audited(client, app, auth):
    conversation = make_conversation(client, auth)
    send(client, auth, conversation["id"])

    with app.state.session_factory() as session:
        events = list(session.scalars(select(AuditEvent).order_by(AuditEvent.created_at)))

    assert [e.action for e in events] == ["conversation.create", "message.user", "message.assistant"]
    assert all(len(e.request_id) == 32 for e in events)


def test_pasted_gateway_token_never_reaches_the_provider(tmp_path):
    token = generate_token()
    from alembic import command

    from app.config import Settings
    from tests.migration_helpers import alembic_config

    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 't.db').as_posix()}", api_token_hash=hash_token(token)
    )
    command.upgrade(alembic_config(settings.database_url), "head")
    provider = make_mock_provider()
    from fastapi.testclient import TestClient

    client = TestClient(create_app(settings, ProviderRegistry({"mock": provider}, "mock")), base_url=LOCAL_BASE_URL)
    auth = {"Authorization": f"Bearer {token}"}
    conversation = make_conversation(client, auth)

    send(client, auth, conversation["id"], f"my token is {token} and Bearer {token}")
    send(client, auth, conversation["id"], "what was my token?")

    for request in provider.requests:
        blob = request.system + "".join(m.content for m in request.messages)
        assert token not in blob


def test_api_key_pasted_into_chat_never_reaches_the_provider(client, auth, mock_provider):
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
    conversation = make_conversation(client, auth)

    body = send(client, auth, conversation["id"], f"use {secret}").json()

    sent = "".join(m.content for m in mock_provider.requests[0].messages)
    assert secret not in sent
    assert secret not in body["assistant_message"]["content"]


# ---------- ownership ----------


@pytest.fixture
def foreign_conversation(app):
    with app.state.session_factory() as session:
        conversation = Conversation(owner=OTHER_OWNER, title="not yours")
        session.add(conversation)
        session.flush()
        session.add(
            Message(conversation_id=conversation.id, sequence=1, role="user", content="private", status="complete")
        )
        session.commit()
        return conversation.id


def test_other_principals_conversations_are_invisible_in_lists(client, auth, foreign_conversation):
    body = client.get("/v1/conversations", headers=auth).json()

    assert body["data"] == []
    assert body["meta"]["total"] == 0


def test_other_principals_conversations_return_404_not_403(client, auth, foreign_conversation):
    assert client.get(f"/v1/conversations/{foreign_conversation}", headers=auth).status_code == 404
    assert client.get(f"/v1/conversations/{foreign_conversation}/messages", headers=auth).status_code == 404
    assert send(client, auth, foreign_conversation).status_code == 404
    assert client.delete(f"/v1/conversations/{foreign_conversation}", headers=auth).status_code == 404


def test_a_rejected_cross_owner_request_changes_nothing(client, app, auth, foreign_conversation):
    send(client, auth, foreign_conversation)
    client.delete(f"/v1/conversations/{foreign_conversation}", headers=auth)

    with app.state.session_factory() as session:
        conversation = session.get(Conversation, foreign_conversation)
        messages = list(session.scalars(select(Message).where(Message.conversation_id == foreign_conversation)))

    assert conversation.deleted_at is None
    assert [m.content for m in messages] == ["private"]


def test_the_same_principal_can_still_see_its_own_after_a_foreign_one_exists(client, auth, foreign_conversation):
    mine = make_conversation(client, auth)

    listed = client.get("/v1/conversations", headers=auth).json()

    assert [c["id"] for c in listed["data"]] == [mine["id"]]


def test_manager_scopes_every_operation_by_owner(app, foreign_conversation):
    with app.state.session_factory() as session:
        theirs = ConversationManager(session, OTHER_OWNER)
        assert theirs.get(foreign_conversation).title == "not yours"
        assert theirs.list_active(10, 0)[1] == 1
        mine = ConversationManager(session, "local")
        assert mine.list_active(10, 0)[1] == 0
        with pytest.raises(Exception) as caught:
            mine.history(foreign_conversation, 10)
        assert getattr(caught.value, "status_code", None) == 404


# ---------- ordering under concurrency ----------


def test_concurrent_appends_get_unique_contiguous_sequences(app):
    with app.state.session_factory() as session:
        conversation_id = ConversationManager(session, "local").create("race", None, "r" * 32).id
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(5):
                with app.state.session_factory() as session:
                    ConversationManager(session, "local").append_message(
                        conversation_id, "user", "x", "r" * 32
                    )
        except Exception as err:
            errors.append(err)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with app.state.session_factory() as session:
        sequences = list(
            session.scalars(
                select(Message.sequence).where(Message.conversation_id == conversation_id).order_by(Message.sequence)
            )
        )
    assert errors == []
    assert sequences == list(range(1, 31))


def test_sequences_are_per_conversation(client, auth):
    first, second = make_conversation(client, auth, "a"), make_conversation(client, auth, "b")

    send(client, auth, first["id"])
    body = send(client, auth, second["id"]).json()

    assert body["user_message"]["sequence"] == 1
