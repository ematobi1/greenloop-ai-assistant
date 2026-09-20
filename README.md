# GreenLoop AI Assistant

A professional, security-first, local-first personal AI assistant for Windows. It is a personal automation platform, not a recycling or sustainability app.

Status: **Phase 1 of 16**, the application foundation. No AI, voice, or integration features exist yet.

## Requirements

- Windows 11, PowerShell 5.1+
- Python 3.12 (`py -3.12`)
- Node.js 22+

## Quick start

```powershell
scripts\setup.ps1     # venv, dependencies, .env, database migration
scripts\dev.ps1       # API on 127.0.0.1:8787, dashboard on 127.0.0.1:5173
scripts\test.ps1      # backend and frontend lint, type checks, tests
scripts\migrate.ps1   # apply database migrations
```

Check the API: `Invoke-RestMethod http://127.0.0.1:8787/v1/health`

## Layout

| Path | Purpose |
|---|---|
| `services/backend` | FastAPI app, SQLAlchemy, Alembic, pytest tests |
| `services/frontend` | React, TypeScript, Vite, Tailwind, Vitest tests |
| `contracts` | JSON schemas shared by both services |
| `scripts` | PowerShell entry points |
| `docs` | Architecture notes |

## Configuration

Copy `.env.example` to `.env` (`setup.ps1` does this). All variables use the `GREENLOOP_` prefix. `.env` and `data/` are git-ignored. Never commit secrets.

## Security defaults

- Servers bind to `127.0.0.1` only.
- CORS allows only the local dashboard origins.
- Unhandled errors return a generic message. Stack traces go to logs only.
- Every request gets an `X-Request-ID` header and structured JSON log lines.

## Roadmap

Later phases add conversations, voice, agents, memory, integrations, scheduling, security monitoring, approvals, and deployment automation. See `CLAUDE.md` for the full list. Each phase needs approval before it starts.
