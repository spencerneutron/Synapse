"""
nudge.py — hook-time reminders for the main session, in one process.

  synapse nudge --hook   # PostToolUse, PostToolUseFailure, UserPromptSubmit, SessionStart

1. Dispatch nudge. Counts consecutive hands-on tool calls (Bash, PowerShell,
   Edit, Write, MultiEdit, NotebookEdit) made by the main session, one byte per
   call in a per-session file. At the budget ([nudge] calls in config.toml,
   default 5; 0 turns it off), and again at twice and four times that, it adds
   one line telling the main session to brief the rest to a role. Synapse's own
   CLI calls and edits under .claude-work/ are not counted. A dispatch (Agent,
   Task) or a new prompt resets the count (and re-arms gate.py's deny); calls
   made inside a sub-agent (hook input has agent_id) are ignored. When the
   context is at or above [gate] min_context, gate.py denies the next call
   instead and this line is not printed.
2. Context nudge. After each matched tool call (Bash, PowerShell, Edit, Write,
   MultiEdit, NotebookEdit, Agent, Task; Read, Grep and MCP calls do not run
   the hook) it reads the transcript tail and, at 60%
   and 90% of the window (from [nudge] context_window; unset: Claude Code's
   auto-compact point when its settings set a window, else 300000 for 1M-window
   models and 150000 for older ones, by model name, lowered by the smallest
   auto-compaction seen in the session; 0 turns 2 and 3 off),
   suggests /synapse:checkpoint. At most 3 times per session; re-armed when the
   context drops below 60% (after a compaction).
3. Prompt digest. On every new prompt, one line (under 200 characters) saying
   a step over about five tool calls or three files is a brief for a role, and
   that the Stop hook checks the final message. [nudge] digest = false turns it
   off. It comes before the resume-time line.
4. Resume-time line. On a new prompt, if the last request was longer ago than
   the prompt cache lives and the context is at least 60% of the window, says
   what the request will rewrite.
5. Resume pointer. At SessionStart after /compact or /clear, points at the
   ## Resume section of .claude-work/current/EXECUTION.md (pointers only).

Stdlib only: no Ollama, no database, no venv. It must never block: it always
exits 0, never prints a decision, and on any error prints nothing.
"""

import json
import os
import sys
import time
from pathlib import Path

HANDS_ON = {"Bash", "PowerShell", "Edit", "Write", "MultiEdit", "NotebookEdit"}
DISPATCH = {"Agent", "Task"}
STALE_S = 24 * 3600
CONTEXT_STALE_S = 7 * 24 * 3600  # the state file is only written on a change
SHELLS = {"Bash", "PowerShell"}
DIGEST = ("Synapse: a step over about five tool calls or three files is a brief for a role, "
          "not work for this session. The Stop hook checks your final message.")
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
    try:
        import gate
        gate.clear(paths, sid)
    except Exception:
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
    own_ctx = paths.context_state(sid).stem
    for f in state.glob("context-*"):
        try:
            if f.name.split(".")[0] != own_ctx \
                    and now - f.stat().st_mtime > CONTEXT_STALE_S:
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


def dispatch_line(paths, sid: str, data: dict) -> str:
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
            try:
                import gate
                if gate.applies(paths, sid, data):
                    return ""   # above [gate] min_context the PreToolUse gate denies instead
            except Exception:
                pass
            return (f"Synapse: {count} hands-on calls in a row in the main session. "
                    "Brief the rest of this step to a role instead of continuing here: "
                    "synapse:implementer for changes or a fix loop (goal, files, failing "
                    "command, done condition, attempt limit), synapse:scout or "
                    "synapse:researcher for searches. Read its report.")
    return ""


def digest_line(paths) -> str:
    try:
        return DIGEST if paths.settings()["nudge_digest"] else ""
    except BaseException:
        return ""


def emit(event: str, *lines: str) -> str:
    text = "\n".join(x for x in lines if x)
    if not text:
        return ""
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def handle(data: dict) -> str:
    sid = data.get("session_id")
    event = data.get("hook_event_name")
    if not isinstance(sid, str) or not sid or not any(c.isalnum() for c in sid):
        return ""
    import paths
    import continuation
    if event in ("PostToolUse", "PostToolUseFailure"):
        if data.get("agent_id"):
            return ""
        first = dispatch_line(paths, sid, data)
        try:
            second = continuation.context_nudge(paths, sid, data)
        except Exception:
            second = ""
        return emit(event, first, second)
    elif event == "UserPromptSubmit":
        reset(paths, sid)
        return emit(event, digest_line(paths),
                    continuation.resume_time_line(paths, data, sid))
    elif event == "SessionStart":
        prune(paths, sid)
        return emit(event, continuation.resume_pointer(paths, data))
    return ""


def main(argv: list[str]) -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if "--hook" not in argv:
            print(__doc__.strip())
            return 0
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        data = read_input()
        cwd = data.get("cwd")
        if isinstance(cwd, str) and os.path.isdir(cwd):
            os.chdir(cwd)   # a project's .synapse.toml applies
        out = handle(data)
        if out:
            print(out)
    except BaseException:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
