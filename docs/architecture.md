# Architecture (Phase 1)

## Principles

- Local-first: everything runs on the user's machine and binds to localhost.
- Security-first: secrets only in environment variables, minimal CORS, no internal errors exposed.
- Services-first: each service owns its code, tests, evals, and config. They talk only through contracts.

## Components

```
Browser (React dashboard, :5173)
   |  /v1/* (Vite dev proxy)
   v
FastAPI backend (:8787)
   |  SQLAlchemy
   v
SQLite (data/greenloop.db)
```

### Backend (`services/backend`)

| Module | Role |
|---|---|
| `app/main.py` | `create_app` factory, request-ID and logging middleware, generic 500 handler |
| `app/config.py` | `Settings` from `GREENLOOP_*` env vars and `.env` |
| `app/logging_config.py` | structlog JSON output |
| `app/db.py` | Engine and session factory. Creates the SQLite directory on demand. |
| `app/models/base.py` | Declarative base with a constraint naming convention for Alembic |
| `app/api/health.py` | `GET /v1/health` |
| `alembic/` | Migrations, baseline revision `0001` has no tables |

### Frontend (`services/frontend`)

`Dashboard` polls `/v1/health` every 10 seconds and renders `StatusCard` in one of four states: checking, healthy, degraded, unreachable. Later-phase capabilities show as "Not yet available".

### Contracts (`contracts`)

`health.schema.json` defines the health response. Backend tests validate live responses against it.

## API

`GET /v1/health`

| Case | Status | Body |
|---|---|---|
| Database reachable | 200 | `{"status":"ok","database":"ok",...}` |
| Database unreachable | 503 | `{"status":"degraded","database":"error",...}` |

Unhandled errors return 500 with `{"error":{"code":"INTERNAL_ERROR","message":"Internal server error"}}`.

## Testing

- Gate tests: `pytest` for the backend, `vitest` for the frontend. Deterministic and local. Fast is preferred, but correctness and reliability come first.
- Evals: none in Phase 1 (`services/backend/evals/README.md`). Real AI evals begin in Phase 3.
- CI: `.github/workflows/ci.yml` runs both suites on `windows-latest`.

## Decisions

- Python is pinned to 3.12. The machine default is 3.14, so scripts call `.venv` explicitly.
- TypeScript is pinned to 5.9 because `typescript-eslint` does not yet support 7.
- API paths use the `/v1` prefix.
