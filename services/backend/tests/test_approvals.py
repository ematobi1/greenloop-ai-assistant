from sqlalchemy import select

from app.models import AuditEvent


def create(client, auth, action="send_email", description="Reply to recruiter"):
    return client.post(
        "/v1/approvals", json={"action": action, "description": description}, headers=auth
    )


def decide(client, auth, approval_id, decision):
    return client.post(
        f"/v1/approvals/{approval_id}/decision", json={"decision": decision}, headers=auth
    )


def test_create_is_pending(client, auth, contract):
    response = create(client, auth)

    assert response.status_code == 201
    body = response.json()
    contract(body, "approval")
    assert body["status"] == "pending"
    assert body["decided_at"] is None


def test_approve_sets_status_and_timestamp(client, auth, contract):
    approval_id = create(client, auth).json()["id"]

    response = decide(client, auth, approval_id, "approved")

    assert response.status_code == 200
    body = response.json()
    contract(body, "approval")
    assert body["status"] == "approved"
    assert body["decided_at"] is not None


def test_deny_sets_status(client, auth):
    approval_id = create(client, auth).json()["id"]

    assert decide(client, auth, approval_id, "denied").json()["status"] == "denied"


def test_second_decision_is_409_and_keeps_first(client, auth, contract):
    approval_id = create(client, auth).json()["id"]
    decide(client, auth, approval_id, "approved")

    response = decide(client, auth, approval_id, "denied")

    assert response.status_code == 409
    contract(response.json(), "error")
    assert response.json()["error"]["code"] == "APPROVAL_ALREADY_DECIDED"
    assert client.get(f"/v1/approvals/{approval_id}", headers=auth).json()["status"] == "approved"


def test_same_decision_twice_is_also_409(client, auth):
    approval_id = create(client, auth).json()["id"]
    decide(client, auth, approval_id, "approved")

    assert decide(client, auth, approval_id, "approved").status_code == 409


def test_deciding_unknown_approval_is_404(client, auth):
    response = decide(client, auth, "missing", "approved")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "APPROVAL_NOT_FOUND"


def test_invalid_decision_value_is_422(client, auth):
    approval_id = create(client, auth).json()["id"]

    response = decide(client, auth, approval_id, "maybe")

    assert response.status_code == 422
    assert "decision" in response.json()["error"]["fields"]


def test_invalid_decision_leaves_approval_pending(client, auth):
    approval_id = create(client, auth).json()["id"]
    decide(client, auth, approval_id, "maybe")

    assert client.get(f"/v1/approvals/{approval_id}", headers=auth).json()["status"] == "pending"


def test_create_validates_action(client, auth):
    assert client.post("/v1/approvals", json={"action": ""}, headers=auth).status_code == 422
    assert client.post("/v1/approvals", json={}, headers=auth).status_code == 422
    assert create(client, auth, action="x" * 101).status_code == 422
    assert create(client, auth, description="x" * 501).status_code == 422


def test_list_filters_by_status(client, auth, contract):
    pending_id = create(client, auth, "a").json()["id"]
    approved_id = create(client, auth, "b").json()["id"]
    decide(client, auth, approved_id, "approved")

    pending = client.get("/v1/approvals?status=pending", headers=auth).json()
    everything = client.get("/v1/approvals", headers=auth).json()

    contract(pending, "approval-list")
    assert [item["id"] for item in pending["data"]] == [pending_id]
    assert pending["meta"]["total"] == 1
    assert everything["meta"]["total"] == 2


def test_list_rejects_unknown_status(client, auth):
    assert client.get("/v1/approvals?status=bogus", headers=auth).status_code == 422


def test_get_unknown_is_404(client, auth):
    assert client.get("/v1/approvals/missing", headers=auth).status_code == 404


def test_approval_flow_writes_audit_events(client, app, auth):
    approval_id = create(client, auth).json()["id"]
    decide(client, auth, approval_id, "approved")
    decide(client, auth, approval_id, "denied")

    with app.state.session_factory() as session:
        events = session.scalars(select(AuditEvent).order_by(AuditEvent.created_at)).all()

    assert [event.action for event in events] == ["approval.create", "approval.approved"]
    assert all(event.resource_id == approval_id for event in events)
