# AI model providers

GreenLoop talks to models through a provider interface (`app/ai/providers/base.py`). Two providers ship in Phase 3, plus a mock for tests.

| Provider | Where the model runs | How it is called |
|---|---|---|
| `claude_cli` (default) | Anthropic, through your local Claude Code login | The installed `claude` executable, headless, with tools disabled |
| `ollama` | This machine | HTTP to a local Ollama server (`/api/chat`) |
| `mock` | Nowhere | Scripted replies for tests. Registered only when `GREENLOOP_AI_ENABLE_MOCK=true`. |

GreenLoop never calls a hosted LLM API directly and holds no LLM API key. This follows the project rule in `CLAUDE.md`.

## Configuration

All values are environment variables (`.env`). Nothing here is a secret.

| Variable | Default | Meaning |
|---|---|---|
| `GREENLOOP_AI_DEFAULT_PROVIDER` | `claude_cli` | Provider used when a request names none |
| `GREENLOOP_AI_TIMEOUT_SECONDS` | `120` | Whole-reply deadline, enforced by the engine for every provider |
| `GREENLOOP_AI_MAX_RETRIES` | `1` | Retries before any output starts (Ollama connect and 5xx errors only), 0 to 3 |
| `GREENLOOP_AI_MAX_OUTPUT_TOKENS` | `2048` | Reply length cap. The engine stops reading at about 4 characters per token. |
| `GREENLOOP_AI_TEMPERATURE` | unset | Passed to providers that support it. The Claude CLI has no such flag and ignores it. |
| `GREENLOOP_AI_CONTEXT_TOKEN_LIMIT` | `8000` | Input budget, estimated at 4 characters per token |
| `GREENLOOP_AI_HISTORY_MESSAGE_LIMIT` | `40` | Most recent messages considered for context |
| `GREENLOOP_AI_MAX_MESSAGE_CHARS` | `8000` | Longest accepted user message |
| `GREENLOOP_AI_PROMPT_VERSION` | `v1` | Active system prompt version |
| `GREENLOOP_CLAUDE_CLI_COMMAND` | `["claude"]` | Executable and fixed leading arguments |
| `GREENLOOP_CLAUDE_CLI_MODEL` | empty | Empty uses the CLI's default model |
| `GREENLOOP_CLAUDE_CLI_ENV_PASSTHROUGH` | `[]` | Names of extra environment variables to forward to the CLI, for example `["ANTHROPIC_API_KEY"]` if you use key auth instead of a login |
| `GREENLOOP_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Must be `127.0.0.1`, `localhost`, or `::1`. Anything else stops startup. |
| `GREENLOOP_OLLAMA_MODEL` | `qwen3.5:latest` | Model name as shown by `ollama list` |

### Credentials

- Settings never contain an API key. `claude_cli_env_passthrough` lists variable names, and the value is read from the process environment at call time.
- Provider endpoints (`GET /v1/ai/providers`, `/v1/ai/models`) return names, models, and availability only.
- Values of passthrough variables are registered with the log and output redactor.
- The GreenLoop API token is never given to a provider. The child process environment drops every `GREENLOOP_*` variable even if it is listed for passthrough.

## Claude CLI lockdown

The Claude Code CLI is an agent, not just a model. It can run shell commands, edit files, and call MCP servers, so GreenLoop starts it with every tool switched off and checks that the switches took effect.

### What was verified

Tested against Claude Code 2.1.278 on 2026-09-20, with a prompt that told the model to run `echo PWNED > canary.txt` and list its tools:

| Check | Result |
|---|---|
| `--tools ""` alone | Not assumed to be enough. The init event was inspected instead. |
| Init event with the flags below | `tools: []`, `mcp_servers: []`, `slash_commands: []`, `skills: []`, `permissionMode: dontAsk`, `cwd` equal to the sandbox |
| Hostile prompt | The model said it has no tools. No `canary.txt` was created anywhere. |
| Bad model name | The CLI exits 0 with `is_error: true` in the result event, so the exit code alone is not a failure signal |
| `--bare` | Unusable: it ignores OAuth and keychain login |

### Flags

`-p --restricted --tools "" --strict-mcp-config --mcp-config {"mcpServers":{}} --disable-slash-commands --setting-sources "" --permission-mode dontAsk --permission-prompts none --no-session-persistence --output-format stream-json --include-partial-messages --verbose --system-prompt <prompt>`

`--restricted` removes command-running tools and ignores user, project, and local settings files. The rest close MCP, skills, prompts, and session files.

### Fail closed

The provider reads the CLI's first event (`system` / `init`) before using any output. It aborts with `unsafe_configuration` and kills the process when any of these is true:

- No init event arrived before other output.
- `tools`, `mcp_servers`, `slash_commands`, or `skills` is not empty.
- `permissionMode` is not `dontAsk`.
- `cwd` is not the sandbox directory.
- A `tool_use` block appears in the stream.

A future CLI version that ignores a flag therefore stops GreenLoop instead of silently giving the model tools.

### Other containment

- **Sandbox:** the CLI runs in an empty directory, `%TEMP%\greenloop-claude-sandbox`, never in the repo.
- **Environment:** the child gets a short allow-list (`PATH`, `USERPROFILE`, `APPDATA`, temp paths, and similar) plus `CLAUDE_CODE_MAX_OUTPUT_TOKENS`. Everything else is dropped.
- **No shell:** the command is an argument list. `.cmd`, `.bat`, and `.ps1` wrappers are refused.
- **Prompt on stdin:** conversation text is sent on standard input, so it never appears in the process list. Only the system prompt is on the command line.
- **Cleanup:** the process tree is killed on timeout, error, and client disconnect (`taskkill /T` on Windows).

### Known limits

- Requests use your Claude Code account and count against its limits.
- The CLI ignores `temperature`.
- Output is buffered by the CLI in chunks, so short replies may arrive as one piece.

## Ollama

- `think` is off and thinking output is ignored.
- Connect errors and 5xx responses are retried with exponential backoff and jitter, only before any output has started. Timeouts and 4xx responses are not retried.
- `trust_env` is off, so proxy environment variables are ignored.
- Availability means the server answers and the configured model is installed.

## Adding a provider

Implement `ModelProvider` (`stream`, `status`, `list_models`) and register it in `build_registry`. Providers must raise `AiError` with a code from `app/ai/errors.py`. Never raise raw exception text: `AiError` messages are the only strings shown to clients.
