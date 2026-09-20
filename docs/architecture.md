# Architecture (Phase 2)

## Principles

- Local-first: everything runs on the user's machine and binds to localhost.
- Security-first: secrets only in environment variables, minimal CORS, host validation, token auth, no internal errors exposed.
- Services-first: each service owns its code, tests, evals, and config. They talk only through contracts.

## Components

```
Browser (React dashboard, :5173)
   |  /v1/* (Vite dev proxy, Bearer token)
   v
FastAPI backend (:8787)
   |  host guard -> request ID -> auth -> router -> repository
   v
SQLite (data/greenloop.db)
```

### Backend (`services/backend`)

| Module | Role |
|---|---|
| `app/main.py` | `create_app` factory, host guard, request-ID and logging middleware, error handlers, routers |
| `app/config.py` | `Settings` from `GREENLOOP_*` env vars and `.env` |
| `app/errors.py` | `ApiError` and the standard error body for 4xx and 5xx |
| `app/security/token.py` | Token generation, SHA-256 hashing, constant-time comparison |
| `app/security/hosts.py` | `Host` header allow-list check |
| `app/security/dependencies.py` | `require_token`, attached to every protected router |
| `app/api/` | `health` (public), `conversations`, `approvals` |
| `app/repositories/` | Database access. Routers never build queries. |
| `app/models/` | SQLAlchemy models with shared id and timestamp mixins |
| `app/schemas.py` | Pydantic request and response models |
| `alembic/` | `0001` baseline, `0002` core tables |

### Data model (migration `0002`)

| Table | Purpose |
|---|---|
| `conversations` | Title, soft delete |
| `messages` | Stored per conversation, role check constraint, soft delete. No API yet. |
| `approvals` | Human approval requests: `pending`, `approved`, `denied` |
| `audit_events` | Actor, action, resource, request ID |
| `settings` | Key/value, no API yet |

Every table has a primary key and `created_at` and `updated_at`. Timestamps are stored as UTC.

### Request flow

1. Host guard rejects any `Host` not in the allow-list with 400.
2. A request ID is generated, bound to the logs, and returned in `X-Request-ID`.
3. Protected routers run `require_token`. The presented token is hashed and compared with `hmac.compare_digest`.
4. The handler calls a repository, records an audit event, and commits once.

### Approval decisions

`decide_if_pending` is a single conditional `UPDATE ... WHERE status = 'pending'`. Two concurrent decisions cannot both succeed: the loser sees zero rows updated and gets 409.

### Frontend (`services/frontend`)

`Dashboard` polls `/v1/health` and shows `StatusCard`. Without a token it shows `UnlockScreen`, which validates the token against the API. With a token it shows `ConversationList` and `ApprovalsPanel`. The token lives in `sessionStorage` (cleared when the tab closes) and is sent as a Bearer header. Any 401 locks the dashboard again.

### Contracts (`contracts`)

JSON schemas for every response. Backend tests validate live responses against them. See `docs/api.md`.

## Testing

- Gate tests: `pytest` for the backend, `vitest` for the frontend. Deterministic and local.
- Migration tests: upgrade, downgrade, repeat, model-versus-migration drift, and constraint checks.
- Evals: none yet (`services/backend/evals/README.md`). Real AI evals begin in Phase 3.
- CI: `.github/workflows/ci.yml` runs both suites on `windows-latest`.

## Decisions

- Python is pinned to 3.12. The machine default is 3.14, so scripts call `.venv` explicitly.
- TypeScript is pinned to 5.9 because `typescript-eslint` does not yet support 7.
- The API listens on 8787 because Docker Desktop uses 8000 on the development machine.
- The API token is a random 256-bit value. Only its SHA-256 hash is stored, in `.env`. A fast hash is enough because the token is high-entropy, not a human password.
- Unauthenticated requests are refused when no token is configured (fail closed).
- Audit and mutation share one transaction, so an action cannot succeed without its audit row.
