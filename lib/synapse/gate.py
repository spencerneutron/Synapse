#!/usr/bin/env python3
"""
gate.py — hook gates for the main session, where a reminder line was not enough.

  synapse gate --hook   # PreToolUse (Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell), Stop

1. Cost-aware deny (PreToolUse). When the hands-on count of the current step
   (the nudge's count: reset by a dispatch or a new prompt) has reached
   [nudge] calls (default 5), twice or four times that, and the context is at
   least [gate] min_context of the window (default 0.5; the window from
   continuation.window_for), the next hands-on call is denied once with a
   reason that names the cost and the role to brief. The retried call is
   allowed: a speed bump, not a wall. Synapse CLI calls, .claude-work/ edits,
   and git commit, git push and gh pr commands are never denied. Below
   min_context the nudge's PostToolUse line runs instead.
2. Stop-forced checkpoint (Stop). When the context is at or above 60% of the
   window and EXECUTION.md's ## Resume has not been written since the context
   reached that mark, block the stop once asking for /synapse:checkpoint. At
   most once at 60% and once at 90% per session; never when stop_hook_active
   is true; below 90% only when .claude-work/current/ exists.
3. Wait for agents (Stop, after 2). When the Stop input's background_tasks
   lists a sub-agent still running, block once per prompt asking the session
   to end the turn with one line naming what it waits for, then verify the
   report when it resumes. The ask is skipped when the final message
   (last_assistant_message) does not open by calling the work finished (Done,
   Fixed, Finished, Shipped, Complete, Merged, Pushed) and one sentence of its
   prose names both a wait and an agent, a role, or its report or findings.
   Backtick code spans, fences and `>` lines are not read as prose (a role
   named in a code span still counts as the agent); negated waits do not
   count. A wording heuristic. [gate] wait_for_agents switches it.

[gate] enabled, min_context, checkpoint and wait_for_agents switch them; a project's
.synapse.toml may override them. State sits next to context-<sid>.json:
context-<sid>.gate.<n> (cleared with the count) and context-<sid>.ckpt.<level>,
each claimed with O_EXCL so parallel hooks act once. Stdlib only. It never
raises: on any error it prints nothing, which allows the call or the stop.
"""

import json
import os
import re
import sys
from pathlib import Path

SHELLS = {"Bash", "PowerShell"}
# Wording heuristic, English only: the wait-for-agents ask is skipped when the message does not
# open by calling the work finished and one sentence of its prose names both a wait and an agent,
# a role, or its report or findings. Backtick code spans, fences and `>` lines are not read as prose.
# Not the session's own statement: fenced code, quoted lines, inline code, negated waits.
_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_QUOTE = re.compile(r"^[ \t]*>[^\n]*", re.M)
_INLINE = re.compile(r"`[^`\n]*`")
_NEGATED = re.compile(
    r"(?:\b(?:not|never|without|no\s+longer|rather\s+than|instead\s+of|no\s+(?:need|reason)\s+to)|n['\u2019]t)"
    r"(?:\s+(?:need|have)\s+to)?\s+a?wait\w*", re.I)
# A message that opens by calling the work finished is asked whatever else it says.
_DONE_LEAD = re.compile(r"[\s*_#>-]*(?:all\s+)?(?:done|fixed|finished|shipped|completed?|merged|pushed)\b", re.I)
# Sentence ends: .!? (and closers) before a space, a blank line, a list or table line.
_SENTENCE = re.compile(r"[.!?][\"')\]*_\u201d\u2019]*\s+|\n\s*\n|\n(?=[ \t]*(?:[-*+]|\d+[.)]|\|)[ \t])")
# Who is awaited: a sub-agent, a role, or what it hands back ("review" not in its pull-request senses).
_AGENT = re.compile(
    r"\b(?:sub-?agents?|agents?|scouts?|implementers?|verifiers?|researchers?|reviewers?|extractors?"
    r"|reports?|findings"
    r"|(?<!\byour\s)(?<!\bfor\s)(?<!\bawaiting\s)(?<!\bpending\s)(?<!\bcode\s)(?<!\bto\s)(?<!\bon\s)(?<!\ba\s)"
    r"(?<!\bPR\s)(?<!\bmy\s)review(?!\s+comments?))\b", re.I)
_DONE = r"(?:is|are|['\u2019]s)\s+(?:done|finished|back|in)"
# The wait itself: waiting, still running, or resuming when it hands back.
_HOLD = re.compile(
    r"\b(?:a?wait(?:s|ing)?|pending|blocked\s+on|on\s+hold|holding\s+(?:for|until)|paused\s+until"
    r"|standing\s+by|check\s+back|resum(?:e|es|ing)|in\s+flight|in\s+the\s+background)\b"
    r"|\bstill\s+(?:[\w-]+ing|in\s+progress|out)\b"
    r"|\b(?:is|are|['\u2019]re)\s+(?:now\s+|currently\s+)?(?:running|working|going)\b"
    r"|\b(?:has|have)(?:n['\u2019]t|\s+not)\s+(?:yet\s+)?(?:reported|finished|returned|come\s+back|replied)\b"
    r"|\b(?:when|once|until|after|while|as\s+soon\s+as|upon)\b.{0,120}?"
    r"(?:\b(?:reports(?=\s*(?:$|[,;:.!?)]|back\b|and\b|or\b|then\b))|report\s+back|returns?|finish(?:es)?"
    r"|lands?|arrives?|comes?\s+(?:back|in)|hands?\s+back|completes?|completion|repl(?:y|ies)"
    r"|(?:has|have)\s+(?:reported|finished|returned))\b|" + _DONE + r"\b)",
    re.I)
# git commit / git push / gh pr, after any leading `cd DIR &&` or `git add ... &&`
LEAD = re.compile(r"^(?:cd\s+[^&;|]+|git(?:\s+-C\s+\S+)?\s+add\b[^&;|]*)\s*(?:&&|;)\s*")
SHIP = re.compile(r"^(?:git(?:\s+-C\s+\S+)?\s+(?:commit|push)\b|gh\s+pr\b)")
CHECKPOINT_SLACK_S = 60   # the stamp has minute resolution

DENY = ("Synapse gate: {n} hands-on calls in this step at about {ctx} context (each call here "
        "costs about {cost} base-equivalent). Brief the rest of this step to synapse:implementer "
        "(goal, files, failing command, done condition, attempt limit) or synapse:scout / "
        "synapse:researcher for searches, then read the report. This gate lifts after a dispatch "
        "or on the next prompt.")
WAIT = ("Synapse: a dispatched agent is still running. End this turn with one line naming what you are "
        "waiting for; the agent's report or the user's next message resumes you. Verify the report before "
        "calling the work done, and if the agent asked a question, answer it or relay it.")
CHECKPOINT = ("Synapse: the context is about {ctx} tokens. Run /synapse:checkpoint now (rewrite "
              "## Resume in EXECUTION.md, append to NOTES.md, `synapse checkpoint --stamp`), then "
              "finish your message.")


def shipping(cmd: str) -> bool:
    """A git commit, git push or gh pr command (optionally after cd / git add)."""
    cmd = cmd.strip()
    while (m := LEAD.match(cmd)):
        cmd = cmd[m.end():]
    return bool(SHIP.match(cmd))


def _k(tokens: float) -> str:
    return f"{round(tokens / 1000)}k"


def _marker(paths, sid: str, name: str) -> Path:
    p = paths.context_state(sid)
    return p.with_name(f"{p.stem}.{name}")


def _claim(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        return True
    except FileExistsError:
        return False


def clear(paths, sid: str) -> None:
    """Re-arm the deny gate (called with the nudge's count reset)."""
    p = paths.context_state(sid)
    for f in p.parent.glob(f"{p.stem}.gate.*"):
        try:
            f.unlink()
        except OSError:
            pass


def thresholds(n: int) -> tuple:
    return (n, 2 * n, 4 * n)


def count_now(paths, sid: str) -> int:
    try:
        return paths.nudge_state(sid).stat().st_size
    except OSError:
        return 0


def context_now(paths, sid: str, data: dict, s: dict, scanned=None):
    """(context tokens, window): 0 when unknown; window 0 when the context lines are off.
    scanned: the (usage, observed) a Stop-hook scan already made, to skip a second read."""
    import continuation
    explicit = s["context_window"]
    if explicit == 0:
        u, window = (scanned or continuation.scan(data.get("transcript_path")))[0], 0
    else:
        u, observed = scanned or continuation.scan(data.get("transcript_path"), explicit is None)
        window, _ = continuation.window_for(paths, sid, u, observed)
    return (u["context"] if u else 0), window


def above(s: dict, ctx: int, window: int) -> bool:
    m = s["gate_min_context"]
    return m <= 0 or (bool(window) and ctx >= window * m)


def applies(paths, sid: str, data: dict) -> bool:
    """True when the deny gate, not the nudge's line, handles this step's threshold."""
    s = paths.settings()
    if not s["gate_enabled"] or s["nudge_calls"] == 0:
        return False
    ctx, window = context_now(paths, sid, data, s)
    return above(s, ctx, window)


def pre_tool(paths, sid: str, data: dict) -> str:
    if data.get("agent_id"):
        return ""
    import nudge
    tool, ti = data.get("tool_name"), data.get("tool_input")
    if tool not in nudge.HANDS_ON or nudge.exempt(tool, ti):
        return ""
    if tool in SHELLS and isinstance(ti, dict) and isinstance(ti.get("command"), str) \
            and shipping(ti["command"]):
        return ""
    s = paths.settings()
    n = s["nudge_calls"]
    if not s["gate_enabled"] or n == 0:
        return ""
    count = count_now(paths, sid)
    due = [t for t in thresholds(n) if count >= t and not _marker(paths, sid, f"gate.{t}").exists()]
    if not due:
        return ""
    ctx, window = context_now(paths, sid, data, s)
    if not above(s, ctx, window):
        return ""
    won = [t for t in due if _claim(_marker(paths, sid, f"gate.{t}"))]
    if not won:
        return ""
    reason = DENY.format(n=count, ctx=_k(ctx), cost=_k(ctx * 0.1))
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                              "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}})


def running_agent(data: dict) -> bool:
    """True when the Stop input's background_tasks lists a sub-agent still running.
    The field (Claude Code docs, 2026-11) lists in-flight tasks: type "subagent"
    with agent_type, status such as "running". It says nothing about which turn
    started a task, so any running sub-agent counts."""
    tasks = data.get("background_tasks")
    if not isinstance(tasks, list):
        return False
    return any(isinstance(t, dict) and t.get("type") == "subagent"
               and str(t.get("status", "running")).lower() in ("running", "pending", "in_progress")
               for t in tasks)


def capture_artifacts(paths, data: dict, s: dict):
    """Record the Artifacts this turn published in ARTIFACTS.md, in the one transcript
    scan the Stop hook makes. Returns that scan's (usage, observed) for context_now, or
    None when the scan did not happen. Prints nothing and never raises."""
    try:
        import artifacts
        import continuation
        explicit = s["context_window"]
        turn = []
        scanned = continuation.scan(data.get("transcript_path"), explicit is None, turn)
        try:
            items = artifacts.from_turn(turn)
            urls = artifacts.from_message(data.get("last_assistant_message"), turn)
            known = {u for u, _ in items}
            items += [(u, None) for u in urls if u not in known]
            if items:
                cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else os.getcwd()
                artifacts.record(paths.find_work_dir(Path(cwd)), items)
        except Exception:
            pass
        return scanned
    except Exception:
        return None


def stop(paths, sid: str, data: dict) -> str:
    if data.get("agent_id"):
        return ""
    s = paths.settings()
    scanned = capture_artifacts(paths, data, s) if s["extract_artifacts"] else None
    if data.get("stop_hook_active"):
        return ""
    return checkpoint_ask(paths, sid, data, s, scanned) or wait_ask(paths, sid, data, s)


def waiting_text(msg: str) -> bool:
    """True when the message does not open as a finished-work report and one sentence of its
    prose names both a wait and an agent, a role, or its report or findings."""
    if _DONE_LEAD.match(msg):
        return False
    text = _NEGATED.sub(" ", _QUOTE.sub(" ", _FENCE.sub(" ", msg)))
    for s in _SENTENCE.split(text):
        s = " ".join(s.split())
        if _AGENT.search(s.replace("`", "")) and _HOLD.search(_INLINE.sub(" ", s)):
            return True
    return False


def says_waiting(data: dict) -> bool:
    """True when the final message (last_assistant_message) does not open by calling the work
    finished and one sentence of its prose names both a wait and an agent, a role, or its report
    or findings. Code spans, fences and `>` lines are not prose (a role in a code span still
    counts as the agent); negated waits do not count. A wording heuristic."""
    msg = data.get("last_assistant_message")
    return isinstance(msg, str) and waiting_text(msg)


def wait_ask(paths, sid: str, data: dict, s: dict) -> str:
    """Block once per prompt (the marker is cleared with the count) while a sub-agent runs,
    unless says_waiting: the message does not open by calling the work finished and one sentence
    of its prose names both a wait and an agent, a role, or its report or findings (no marker is
    claimed then). A wording heuristic."""
    if not s["gate_wait_for_agents"] or not running_agent(data):
        return ""
    if says_waiting(data):
        return ""
    if not _claim(_marker(paths, sid, "gate.wait")):
        return ""
    return json.dumps({"decision": "block", "reason": WAIT})


def checkpoint_ask(paths, sid: str, data: dict, s: dict, scanned=None) -> str:
    import continuation
    if not s["gate_checkpoint"]:
        return ""
    ctx, window = context_now(paths, sid, data, s, scanned)
    if not window or not ctx:
        return ""
    state = paths.context_state(sid)
    if ctx < window * continuation.LOW:
        continuation.uncross(state)
        return ""
    level = "high" if ctx >= window * continuation.HIGH else "low"
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else os.getcwd()
    work = paths.find_work_dir(Path(cwd))
    if level == "low" and not work.is_dir():
        return ""
    if _marker(paths, sid, f"ckpt.{level}").exists():
        return ""
    since = continuation.cross(state, level)
    written = continuation.resume_written(work / "EXECUTION.md")
    if written is not None and written.timestamp() + CHECKPOINT_SLACK_S >= since:
        return ""
    if not _claim(_marker(paths, sid, f"ckpt.{level}")):
        return ""
    if level == "high":
        _claim(_marker(paths, sid, "ckpt.low"))   # 90% first: the 60% ask is moot
    return json.dumps({"decision": "block", "reason": CHECKPOINT.format(ctx=_k(ctx))})


def handle(data: dict) -> str:
    sid = data.get("session_id")
    if not isinstance(sid, str) or not sid or not any(c.isalnum() for c in sid):
        return ""
    import paths
    event = data.get("hook_event_name")
    if event == "PreToolUse":
        return pre_tool(paths, sid, data)
    if event == "Stop":
        return stop(paths, sid, data)
    return ""


def main(argv: list[str]) -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if "--hook" not in argv:
            print(__doc__.strip())
            return 0
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "null")
        except Exception:
            return 0
        if not isinstance(data, dict):
            return 0
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
