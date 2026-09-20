from sqlalchemy import select

from app.models import AuditEvent, Conversation


def create(client, auth, title="Trip planning"):
    return client.post("/v1/conversations", json={"title": title}, headers=auth)


def audit_actions(app) -> list[str]:
    with app.state.session_factory() as session:
        return list(session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at)))


def test_create_returns_contract_shape(client, auth, contract):
    response = create(client, auth)

    assert response.status_code == 201
    contract(response.json(), "conversation")
    assert response.json()["title"] == "Trip planning"


def test_title_is_trimmed(client, auth):
    assert create(client, auth, "  padded  ").json()["title"] == "padded"


def test_get_returns_created_conversation(client, auth, contract):
    created = create(client, auth).json()

    response = client.get(f"/v1/conversations/{created['id']}", headers=auth)

    assert response.status_code == 200
    contract(response.json(), "conversation")
    assert response.json() == created


def test_get_unknown_id_is_404(client, auth, contract):
    response = client.get("/v1/conversations/missing", headers=auth)

    assert response.status_code == 404
    contract(response.json(), "error")
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_list_wraps_data_and_total(client, auth, contract):
    for title in ("one", "two", "three"):
        create(client, auth, title)

    response = client.get("/v1/conversations", headers=auth)

    body = response.json()
    contract(body, "conversation-list")
    assert body["meta"]["total"] == 3
    assert {item["title"] for item in body["data"]} == {"one", "two", "three"}


def test_list_paginates_and_reports_full_total(client, auth):
    for index in range(5):
        create(client, auth, f"c{index}")

    body = client.get("/v1/conversations?limit=2&offset=1", headers=auth).json()

    assert len(body["data"]) == 2
    assert body["meta"]["total"] == 5


def test_delete_is_soft_and_hides_from_reads(client, app, auth):
    conversation_id = create(client, auth).json()["id"]

    response = client.delete(f"/v1/conversations/{conversation_id}", headers=auth)

    assert response.status_code == 204
    assert client.get(f"/v1/conversations/{conversation_id}", headers=auth).status_code == 404
    assert client.get("/v1/conversations", headers=auth).json()["meta"]["total"] == 0
    with app.state.session_factory() as session:
        row = session.get(Conversation, conversation_id)
        assert row is not None and row.deleted_at is not None


def test_deleting_twice_is_404(client, auth):
    conversation_id = create(client, auth).json()["id"]
    client.delete(f"/v1/conversations/{conversation_id}", headers=auth)

    assert client.delete(f"/v1/conversations/{conversation_id}", headers=auth).status_code == 404


def test_blank_title_is_rejected_with_field_errors(client, auth, contract):
    response = create(client, auth, "   ")

    assert response.status_code == 422
    contract(response.json(), "error")
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert "title" in response.json()["error"]["fields"]


def test_overlong_title_is_rejected(client, auth):
    assert create(client, auth, "x" * 201).status_code == 422


def test_missing_body_is_rejected(client, auth):
    assert client.post("/v1/conversations", json={}, headers=auth).status_code == 422


def test_pagination_bounds_are_validated(client, auth):
    for query in ("limit=0", "limit=101", "offset=-1", "limit=abc"):
        assert client.get(f"/v1/conversations?{query}", headers=auth).status_code == 422


def test_sql_metacharacters_in_title_are_stored_literally(client, auth):
    payload = "Robert'); DROP TABLE conversations;--"
    created = create(client, auth, payload).json()

    fetched = client.get(f"/v1/conversations/{created['id']}", headers=auth).json()

    assert fetched["title"] == payload
    assert client.get("/v1/conversations", headers=auth).json()["meta"]["total"] == 1


def test_mutations_write_audit_events(client, app, auth):
    conversation_id = create(client, auth).json()["id"]
    client.delete(f"/v1/conversations/{conversation_id}", headers=auth)

    assert audit_actions(app) == ["conversation.create", "conversation.delete"]
    with app.state.session_factory() as session:
        event = session.scalars(select(AuditEvent)).first()
        assert event.resource_id == conversation_id
        assert event.actor == "local-token"
        assert len(event.request_id) == 32


def test_reads_and_failures_write_no_audit_events(client, app, auth):
    client.get("/v1/conversations", headers=auth)
    create(client, auth, "   ")
    client.delete("/v1/conversations/missing", headers=auth)

    assert audit_actions(app) == []
