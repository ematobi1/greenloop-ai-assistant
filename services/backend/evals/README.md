# Backend evals

Phases 1 and 2 have no AI model behavior, so there is nothing to evaluate yet. This is a deliberate stub.

## Strategy (starts in Phase 3)

- Evals measure model output quality, so they call the LLM and are non-deterministic. They live here, separate from gate tests in `tests/`.
- Each eval case is a fixture file: input, expected properties, and a pass rule. Prefer deterministic checks (schema validity, required facts, refusal on forbidden actions) over model-graded checks.
- Each eval suite has a pass threshold. A run below threshold fails.
- LLM calls route through the local Claude Code CLI via `services/llm/`, never a hosted API.
- Evals run before ship and nightly, not on every commit.
- Every bug fix in AI behavior adds a case that would have caught it.
