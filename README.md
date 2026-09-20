# GreenLoop AI Assistant

A professional, security-first, local-first personal AI assistant for Windows. It is a personal automation platform, not a recycling or sustainability app.

Status: **Phase 2 of 16**, the secure API and data foundation. No AI, voice, or integration features exist yet.

## Requirements

- Windows 11, PowerShell 5.1+
- Python 3.12 (`py -3.12`)
- Node.js 22+

## Quick start

```powershell
scripts\setup.ps1     # venv, dependencies, .env, migration, API token (printed once)
scripts
ew-token.ps1 # rotate the API token
scripts\dev.ps1       # API on 127.0.0.1:8787, dashboard on 127.0.0.1:5173
scripts\test.ps1      # backend and frontend lint, type checks, tests
scripts\migrate.ps1   # apply database migrations
```

Check the API: `Invoke-RestMethod http://127.0.0.1:8787/v1/health`

Open the dashboard and paste the token from `setup.ps1` into the unlock form. Every endpoint except `/v1/health` needs `Authorization: Bearer <token>`. See `docs/api.md`.

## Layout

| Path | Purpose |
|---|---|
| `services/backend` | FastAPI app, SQLAlchemy, Alembic, pytest tests |
| `services/frontend` | React, TypeScript, Vite, Tailwind, Vitest tests |
| `contracts` | JSON schemas shared by both services |
| `scripts` | PowerShell entry points |
| `docs` | Architecture notes and API reference |

## Configuration

Copy `.env.example` to `.env` (`setup.ps1` does this). All variables use the `GREENLOOP_` prefix. `.env` and `data/` are git-ignored. Never commit secrets.

## Security defaults

- Servers bind to `127.0.0.1` only, and requests with any other `Host` header get 400.
- Bearer token auth on every endpoint except health. Only the token's hash is stored, and with no token configured the API refuses everything.
- Every change is written to an audit table with its request ID.
- CORS allows only the local dashboard origins.
- Unhandled errors return a generic message. Stack traces go to logs only.
- Every request gets an `X-Request-ID` header and structured JSON log lines.

## Roadmap

Later phases add conversations, voice, agents, memory, integrations, scheduling, security monitoring, approvals, and deployment automation. See `CLAUDE.md` for the full list. Each phase needs approval before it starts.
