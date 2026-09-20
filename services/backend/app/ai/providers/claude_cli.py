import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import structlog

from app.ai.errors import AiError
from app.ai.providers.base import (
    Done,
    GenerationRequest,
    ProviderConfig,
    ProviderStatus,
    StreamEvent,
    TextDelta,
)
from app.ai.providers.transcript import render_transcript

logger = structlog.get_logger()

FORBIDDEN_EXECUTABLE_SUFFIXES = {".cmd", ".bat", ".ps1"}
BASE_ENV_NAMES = (
    "SystemRoot", "SYSTEMDRIVE", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "HOMEDRIVE",
    "HOMEPATH", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "USERNAME", "USERDOMAIN",
    "PROGRAMDATA", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
)
NEVER_FORWARDED_PREFIX = "GREENLOOP_"
STDERR_LIMIT = 4096
SANDBOX_DIRECTORY_NAME = "greenloop-claude-sandbox"
FINAL_INSTRUCTION = "Reply as the assistant to the last user turn."


def restrict_to_current_user(directory: Path) -> None:
    """Remove inherited access so only this user (and SYSTEM on Windows) can use the directory."""
    if os.name != "nt":
        directory.chmod(0o700)
        return
    domain, name = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    account = f"{domain}\\{name}" if domain else name
    completed = subprocess.run(  # noqa: S603
        [
            "icacls", str(directory), "/inheritance:r",
            "/grant:r", f"{account}:(OI)(CI)F", "/grant:r", "SYSTEM:(OI)(CI)F",
        ],
        capture_output=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if not account or completed.returncode != 0:
        raise AiError("unsafe_configuration")


def clear_directory(directory: Path) -> None:
    """Delete everything inside the sandbox so nothing persists between runs."""
    leftovers = list(directory.iterdir())
    if leftovers:
        logger.warning("claude_sandbox_had_files", count=len(leftovers))
    for entry in leftovers:
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError as err:
            raise AiError("unsafe_configuration") from err


def lockdown_arguments(system_prompt: str, model: str) -> list[str]:
    arguments = [
        "-p",
        "--restricted",
        "--tools", "",
        "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}',
        "--disable-slash-commands",
        "--setting-sources", "",
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--no-session-persistence",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--system-prompt", system_prompt,
    ]
    if model:
        arguments += ["--model", model]
    return arguments


def build_environment(passthrough: list[str], max_output_tokens: int) -> dict[str, str]:
    names = [*BASE_ENV_NAMES, *passthrough]
    environment = {
        name: os.environ[name]
        for name in names
        if name in os.environ and not name.upper().startswith(NEVER_FORWARDED_PREFIX)
    }
    environment["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_output_tokens)
    return environment


def verify_lockdown(init_event: dict, sandbox_dir: Path) -> None:
    same_directory = os.path.normcase(os.path.realpath(str(init_event.get("cwd", "")))) == (
        os.path.normcase(os.path.realpath(str(sandbox_dir)))
    )
    locked_down = (
        init_event.get("tools") == []
        and init_event.get("mcp_servers") == []
        and init_event.get("slash_commands", []) == []
        and init_event.get("skills", []) == []
        and init_event.get("permissionMode") == "dontAsk"
        and same_directory
    )
    if not locked_down:
        raise AiError("unsafe_configuration")


class ClaudeCliProvider:
    def __init__(
        self,
        config: ProviderConfig,
        command: list[str],
        env_passthrough: list[str] | None = None,
        sandbox_dir: Path | None = None,
    ):
        self.config = config
        self._command = command
        self._env_passthrough = env_passthrough or []
        self._sandbox_dir = sandbox_dir
        self._secured = False

    def _sandbox(self) -> Path:
        if self._sandbox_dir is None:
            self._sandbox_dir = Path(tempfile.gettempdir()) / SANDBOX_DIRECTORY_NAME
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        if not self._secured:
            restrict_to_current_user(self._sandbox_dir)
            self._secured = True
        clear_directory(self._sandbox_dir)
        return self._sandbox_dir

    def _executable(self) -> str:
        resolved = shutil.which(self._command[0])
        if resolved is None:
            raise AiError("unavailable")
        if Path(resolved).suffix.lower() in FORBIDDEN_EXECUTABLE_SUFFIXES:
            raise AiError("unsafe_configuration")
        return resolved

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        executable = self._executable()
        sandbox = self._sandbox()
        lockdown = lockdown_arguments(request.system, self.config.model)
        argv = [executable, *self._command[1:], *lockdown]
        prompt = f"{render_transcript(request.messages)}\n\n{FINAL_INSTRUCTION}"
        environment = build_environment(self._env_passthrough, request.max_output_tokens)
        try:
            process = subprocess.Popen(  # noqa: S603 - argv list, no shell, fixed flags
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=sandbox,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as err:
            raise AiError("unavailable") from err

        loop = asyncio.get_running_loop()
        lines: asyncio.Queue[bytes | None] = asyncio.Queue()
        stderr_tail = bytearray()
        threading.Thread(target=_feed_stdin, args=(process, prompt), daemon=True).start()
        threading.Thread(target=_pump_stdout, args=(process, loop, lines), daemon=True).start()
        threading.Thread(target=_drain_stderr, args=(process, stderr_tail), daemon=True).start()

        try:
            async for event in self._events(process, lines, sandbox, stderr_tail):
                yield event
        finally:
            _terminate(process)
            clear_directory(sandbox)

    async def _events(
        self,
        process: subprocess.Popen,
        lines: "asyncio.Queue[bytes | None]",
        sandbox: Path,
        stderr_tail: bytearray,
    ) -> AsyncIterator[StreamEvent]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.timeout_seconds
        verified = False
        emitted_text = False
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AiError("timeout")
            try:
                raw = await asyncio.wait_for(lines.get(), remaining)
            except TimeoutError as err:
                raise AiError("timeout") from err
            if raw is None:
                break
            event = _parse_line(raw)
            if event is None:
                continue
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                verify_lockdown(event, sandbox)
                verified = True
                continue
            if kind in {"stream_event", "assistant", "result"} and not verified:
                raise AiError("unsafe_configuration")
            if kind == "stream_event":
                text = _delta_text(event.get("event", {}))
                if text:
                    emitted_text = True
                    yield TextDelta(text)
            elif kind == "result":
                for outgoing in _finish(event, emitted_text, stderr_tail):
                    yield outgoing
                return
        _log_failure("claude_cli_ended_without_result", process, stderr_tail)
        raise AiError("invalid_response")

    async def status(self) -> ProviderStatus:
        try:
            executable = self._executable()
        except AiError as err:
            return ProviderStatus(available=False, detail=err.code)
        version = await asyncio.to_thread(_read_version, executable, self._command[1:])
        return ProviderStatus(available=version is not None, detail=version or "unavailable")

    async def list_models(self) -> list[str]:
        return [self.config.model or "default"]


def _feed_stdin(process: subprocess.Popen, prompt: str) -> None:
    try:
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()
    except OSError:
        return


def _pump_stdout(process: subprocess.Popen, loop: asyncio.AbstractEventLoop, lines) -> None:
    try:
        for raw in process.stdout:
            loop.call_soon_threadsafe(lines.put_nowait, raw)
    except (OSError, ValueError):
        pass
    try:
        loop.call_soon_threadsafe(lines.put_nowait, None)
    except RuntimeError:
        return


def _drain_stderr(process: subprocess.Popen, tail: bytearray) -> None:
    try:
        for raw in process.stderr:
            if len(tail) < STDERR_LIMIT:
                tail.extend(raw[: STDERR_LIMIT - len(tail)])
    except (OSError, ValueError):
        return


def _parse_line(raw: bytes) -> dict | None:
    try:
        event = json.loads(raw)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _delta_text(inner: dict) -> str:
    kind = inner.get("type")
    if kind == "content_block_start" and inner.get("content_block", {}).get("type") == "tool_use":
        raise AiError("unsafe_configuration")
    if kind == "content_block_delta" and inner.get("delta", {}).get("type") == "text_delta":
        return inner["delta"].get("text", "")
    return ""


def _finish(event: dict, emitted_text: bool, stderr_tail: bytearray) -> list[StreamEvent]:
    if event.get("is_error"):
        status = event.get("api_error_status")
        logger.warning("claude_cli_reported_error", subtype=event.get("subtype"), status=status)
        rejected = isinstance(status, int) and 400 <= status < 500
        raise AiError("rejected" if rejected else "unavailable")
    outgoing: list[StreamEvent] = []
    if not emitted_text:
        text = event.get("result")
        if not isinstance(text, str) or not text.strip():
            raise AiError("invalid_response")
        outgoing.append(TextDelta(text))
    outgoing.append(Done())
    return outgoing


def _log_failure(message: str, process: subprocess.Popen, stderr_tail: bytearray) -> None:
    logger.warning(
        message,
        return_code=process.poll(),
        stderr=bytes(stderr_tail[:200]).decode("utf-8", errors="replace"),
    )


def _read_version(executable: str, extra: list[str]) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603
            [executable, *extra, "--version"],
            capture_output=True,
            timeout=8,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace").strip()[:100]


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            process.kill()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
    for stream in (process.stdin, process.stdout, process.stderr):
        try:
            stream.close()
        except (OSError, ValueError, AttributeError):
            continue
