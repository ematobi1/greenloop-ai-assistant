"""Stand-in for the claude CLI. Behavior is chosen with FAKE_CLAUDE_MODE."""

import json
import os
import sys
import time


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def delta(text: str) -> dict:
    return {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    }


def init_event(**overrides) -> dict:
    event = {
        "type": "system",
        "subtype": "init",
        "tools": [],
        "mcp_servers": [],
        "slash_commands": [],
        "skills": [],
        "permissionMode": "dontAsk",
        "cwd": os.getcwd(),
    }
    event.update(overrides)
    return event


def main() -> None:
    mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
    if "--version" in sys.argv:
        print("9.9.9 (Fake Claude)")
        return
    prompt = sys.stdin.buffer.read().decode("utf-8")
    record_path = os.environ.get("FAKE_CLAUDE_RECORD")
    if record_path:
        with open(record_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "argv": sys.argv[1:],
                    "env_names": sorted(os.environ),
                    "stdin": prompt,
                    "cwd": os.getcwd(),
                    "pid": os.getpid(),
                },
                handle,
            )

    if mode == "noinit":
        emit(delta("sneaky"))
        return
    if mode == "tools":
        emit(init_event(tools=["Bash"]))
        emit(delta("should never be read"))
        return
    if mode == "mcp":
        emit(init_event(mcp_servers=[{"name": "x"}]))
        return
    if mode == "loose_permissions":
        emit(init_event(permissionMode="bypassPermissions"))
        return
    if mode == "wrong_cwd":
        emit(init_event(cwd="C:\\somewhere\\else"))
        return
    emit(init_event())
    if mode == "tool_use":
        emit(
            {
                "type": "stream_event",
                "event": {"type": "content_block_start", "content_block": {"type": "tool_use"}},
            }
        )
        return
    if mode == "hang":
        time.sleep(60)
        return
    if mode == "slow":
        emit(delta("first"))
        time.sleep(60)
        return
    if mode == "noresult":
        emit(delta("partial"))
        return
    if mode == "error404":
        emit({"type": "result", "is_error": True, "api_error_status": 404, "result": "SECRET-DETAIL"})
        return
    if mode == "error500":
        emit({"type": "result", "is_error": True, "api_error_status": 500, "result": "boom"})
        return
    if mode == "garbage":
        sys.stdout.write("not json\n[1,2]\n")
        sys.stdout.flush()
    if mode == "result_only":
        emit({"type": "result", "is_error": False, "result": "Whole reply"})
        return
    emit(delta("Hello "))
    emit(delta("world"))
    emit({"type": "result", "is_error": False, "result": "Hello world"})


if __name__ == "__main__":
    main()
