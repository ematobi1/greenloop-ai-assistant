# GreenLoop AI Assistant

GreenLoop is a personal AI automation platform. It is not a recycling or sustainability application.

It is a professional, security-first, local-first personal AI assistant for Windows.

## Target capabilities (built across 16 phases)

1. React and TypeScript web dashboard
2. Python FastAPI backend
3. Natural language AI conversations
4. Voice interaction with wake-word activation
5. Standby and listening modes
6. Multi-agent AI orchestration
7. Persistent memory
8. Gmail, Slack, Google Calendar, GitHub, browser, and VS Code integrations
9. Career and productivity assistance
10. AWS, Kubernetes, and Docker integrations
11. Scheduled task automation
12. Continuous security monitoring
13. Human approval and permission management
14. GitHub Actions CI/CD deployment automation
15. Automated error investigation and self-correction
16. Automated dependency maintenance and controlled self-recovery

## Current phase: PHASE 1 ONLY

Objective: establish a working application foundation.

In scope:

- Python 3.12 and FastAPI backend
- React, TypeScript, Vite, Tailwind CSS frontend
- SQLite development database, SQLAlchemy, Alembic
- Environment configuration
- Structured logging
- Health-check API endpoint
- Initial GreenLoop dashboard
- Windows PowerShell scripts
- Backend and frontend automated tests
- Initial GitHub Actions CI
- README and architecture documentation
- `.gitignore` excluding `.venv` and secrets

Out of scope until a later phase is approved: voice, AI agents, integrations, self-correction, scheduling, and anything else in the capability list above.

## Working agreements

- No implementation begins until the user approves the phase plan.
- Do not start the next phase without explicit approval.
- Platform is Windows 11. Scripts are PowerShell. Use `py -3.12` for Python.
- Backend runs in the project-root `.venv` (Python 3.12). Never commit `.venv`.
- Local-first: no data leaves the machine unless a phase explicitly adds an integration.
- Security-first: no secrets in code or git, config from environment variables, `.env` is git-ignored, only `.env.example` is committed.
- Human approval is required before any action that changes external systems (later phases enforce this in code).
- LLM calls, when added, route through the local Claude Code CLI via a self-contained `services/llm/` service, not a hosted API.
- Every feature ships with gate tests in the same commit.
- Global rules in `~/.claude/CLAUDE.md` also apply.
