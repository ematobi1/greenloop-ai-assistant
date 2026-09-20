# API reference (v1)

Base URL: `http://127.0.0.1:8787`. All timestamps are ISO 8601 UTC (`2026-09-20T14:30:00Z`). IDs are strings.

## Authentication

Every endpoint except `GET /v1/health` requires `Authorization: Bearer <token>`.

- `scripts\setup.ps1` generates the token, prints it once, and stores only its SHA-256 hash in `.env` as `GREENLOOP_API_TOKEN_HASH`.
- `scripts\new-token.ps1` rotates it. Restart the backend afterwards.
- With no hash configured, every protected endpoint returns 401.
- Requests whose `Host` header is not in `GREENLOOP_ALLOWED_HOSTS` (default `127.0.0.1`, `localhost`) get 400 `INVALID_HOST`. This blocks DNS-rebinding attacks from web pages.

## Errors

```json
{ "error": { "code": "VALIDATION_FAILED", "message": "Request validation failed", "fields": { "title": "..." } } }
```

| Status | Codes |
|---|---|
| 400 | `INVALID_HOST` |
| 401 | `UNAUTHENTICATED` (with `WWW-Authenticate: Bearer`) |
| 404 | `NOT_FOUND`, `CONVERSATION_NOT_FOUND`, `APPROVAL_NOT_FOUND` |
| 409 | `APPROVAL_ALREADY_DECIDED` |
| 422 | `VALIDATION_FAILED` (with `fields`) |
| 500 | `INTERNAL_ERROR` (no internals exposed) |

Every response carries `X-Request-ID`. The same ID appears in the logs and in `audit_events.request_id`.

## Lists

`GET` list endpoints take `limit` (1 to 100, default 50) and `offset` (0 or more) and return `{ "data": [...], "meta": { "total": N } }`. `total` counts all matching rows, not just the page.

## Endpoints

| Method and path | Success | Notes |
|---|---|---|
| `GET /v1/health` | 200, or 503 when the database is unreachable | Public |
| `POST /v1/conversations` | 201 | Body `{ "title": "1 to 200 chars, trimmed" }` |
| `GET /v1/conversations` | 200 | Newest first, excludes deleted |
| `GET /v1/conversations/{id}` | 200 | 404 if missing or deleted |
| `DELETE /v1/conversations/{id}` | 204 | Soft delete. A second delete returns 404. |
| `POST /v1/approvals` | 201 | Body `{ "action": "1 to 100 chars", "description": "up to 500 chars" }`. Starts `pending`. |
| `GET /v1/approvals?status=pending` | 200 | `status` is `pending`, `approved`, or `denied` |
| `GET /v1/approvals/{id}` | 200 | |
| `POST /v1/approvals/{id}/decision` | 200 | Body `{ "decision": "approved" \| "denied" }`. A decided approval returns 409. |

Approving a request records the decision only. Nothing executes an approved action in Phase 2.

## Audit trail

Every successful mutation writes one `audit_events` row in the same transaction: `conversation.create`, `conversation.delete`, `approval.create`, `approval.approved`, `approval.denied`. Reads and failed requests write nothing.

## Contracts

JSON schemas live in `contracts/` and are checked against live responses by the backend tests: `health`, `conversation`, `conversation-list`, `approval`, `approval-list`, `error`.
