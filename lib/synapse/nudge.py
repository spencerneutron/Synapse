#!/usr/bin/env python3
"""
nudge.py — remind the main session to dispatch after a run of hands-on calls.

  synapse nudge --hook   # PostToolUse, PostToolUseFailure, UserPromptSubmit, SessionStart

Counts consecutive hands-on tool calls (Bash, PowerShell, Edit, Write,
MultiEdit, NotebookEdit) made by the main session, one byte per call in a
per-session file. At the budget ([nudge] calls in config.toml, default 5; 0
turns it off), and again at twice and four times that, it adds one line of
context telling the main session to brief the rest to a role.
Synapse's own CLI calls and edits under .claude-work/ are not counted. A dispatch (Agent, Task) or a new prompt resets the count; calls made inside
a sub-agent (hook input has agent_id) are ignored. Stdlib only: no Ollama, no
database, no venv. It must never block: it always exits 0, never prints a
decision, and on any error prints nothing.
"""

import json
import os
import sys
import time
from pathlib import Path

HANDS_ON = {"Bash", "PowerShell", "Edit", "Write", "MultiEdit", "NotebookEdit"}
DISPATCH = {"Agent", "Task"}
STALE_S = 24 * 3600
SHELLS = {"Bash", "PowerShell"}
PLANNING_DIRS = ("/.claude-work/", "\\.claude-work\\")


def exempt(tool: str, tool_input) -> bool:
    """Synapse's own CLI calls and planning-file edits do not count."""
    if not isinstance(tool_input, dict):
        return False
    if tool in SHELLS:
        cmd = tool_input.get("command")
        if isinstance(cmd, str):
            cmd = cmd.strip()
            return cmd == "synapse" or cmd.startswith("synapse ")
        return False
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    return isinstance(path, str) and any(d in path for d in PLANNING_DIRS)


def read_input() -> dict:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "null")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def reset(paths, sid: str) -> None:
    try:
        paths.nudge_state(sid).unlink()
    except OSError:
        pass


def prune(paths, sid: str) -> None:
    state = paths.nudge_state(sid).parent
    own = paths.nudge_state(sid)
    now = time.time()
    for f in state.glob("nudge-*"):
        try:
            if f == own or now - f.stat().st_mtime > STALE_S:
                f.unlink()
        except OSError:
            pass


def count_call(paths, sid: str) -> int:
    path = paths.nudge_state(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, b".")
        # With O_APPEND the write lands at the end, so the offset is this call's own count.
        return os.lseek(fd, 0, os.SEEK_CUR)
    finally:
        os.close(fd)


def handle(data: dict) -> str:
    sid = data.get("session_id")
    event = data.get("hook_event_name")
    if not isinstance(sid, str) or not sid or not any(c.isalnum() for c in sid):
        return ""
    import paths
    if event in ("PostToolUse", "PostToolUseFailure"):
        if data.get("agent_id"):
            return ""
        tool = data.get("tool_name")
        if tool in DISPATCH:
            reset(paths, sid)
        elif tool in HANDS_ON:
            if exempt(tool, data.get("tool_input")):
                return ""
            n = paths.settings()["nudge_calls"]
            if n == 0:
                return ""
            count = count_call(paths, sid)
            if count in (n, 2 * n, 4 * n):
                text = (f"Synapse: {count} hands-on calls in a row in the main session. "
                        "Brief the rest of this step to a role instead of continuing here: "
                        "synapse:implementer for changes or a fix loop (goal, files, failing "
                        "command, done condition, attempt limit), synapse:scout or "
                        "synapse:researcher for searches. Read its report.")
                return json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                                          "additionalContext": text}})
    elif event == "UserPromptSubmit":
        reset(paths, sid)
    elif event == "SessionStart":
        prune(paths, sid)
    return ""


def main(argv: list[str]) -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if "--hook" not in argv:
            print(__doc__.strip())
            return 0
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        out = handle(read_input())
        if out:
            print(out)
    except BaseException:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
