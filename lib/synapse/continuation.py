#!/usr/bin/env python3
"""
continuation.py — context-size facts for the nudge hook (stdlib only, no I/O beyond small files).

Called from nudge.handle; it never prints and never raises on its own account.
  last_usage(path)         tail-read a transcript for the newest main-session usage entry
  context_nudge(...)       PostToolUse: one line at 60% and 90% of the context window
  resume_time_line(...)    UserPromptSubmit: the prompt cache expired while idle
  resume_pointer(...)      SessionStart (compact or clear): point at EXECUTION.md ## Resume
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

CHUNK = 64 * 1024
TAIL_CAP = 2 * 1024 * 1024
MAX_FIRES = 3
LOW, HIGH = 0.6, 0.9
CHECKPOINT = ("A /synapse:checkpoint before the next stage or before stepping away "
              "keeps /clear free.")


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _split_ttl(usage: dict):
    cc = usage.get("cache_creation")
    if not isinstance(cc, dict):
        return None
    if _int(cc.get("ephemeral_1h_input_tokens")) > 0:
        return "1h"
    if _int(cc.get("ephemeral_5m_input_tokens")) > 0:
        return "5m"
    return None


def _tail_lines(path: str):
    """Complete lines from the end of the file, newest first, within TAIL_CAP."""
    with open(path, "rb") as f:
        pos = f.seek(0, os.SEEK_END)
        read = 0
        carry = b""
        while pos > 0 and read < TAIL_CAP:
            size = min(CHUNK, pos, TAIL_CAP - read)
            pos -= size
            read += size
            f.seek(pos)
            parts = (f.read(size) + carry).split(b"\n")
            carry = parts[0]
            yield from reversed(parts[1:])
        if pos == 0:
            yield carry


def last_usage(transcript_path):
    """Newest main-session assistant usage: {"context", "time", "ttl"} or None."""
    try:
        if not isinstance(transcript_path, str) or not os.path.isfile(transcript_path):
            return None
        found = None
        for line in _tail_lines(transcript_path):
            if b"compact_boundary" in line:
                try:
                    b = json.loads(line)
                except Exception:
                    b = None
                if isinstance(b, dict) and b.get("type") == "system" \
                        and b.get("subtype") == "compact_boundary":
                    break  # older usage predates the compaction: stale
            if b'"usage"' not in line or b'"assistant"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict) or e.get("type") != "assistant" or e.get("isSidechain") is True:
                continue
            msg = e.get("message")
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(usage, dict):
                continue
            ctx = (_int(usage.get("input_tokens")) + _int(usage.get("cache_read_input_tokens"))
                   + _int(usage.get("cache_creation_input_tokens")))
            if ctx == 0:
                continue
            ttl = _split_ttl(usage)
            if found is None:
                when = None
                ts = e.get("timestamp")
                if isinstance(ts, str):
                    try:
                        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if when.tzinfo is None:
                            when = when.replace(tzinfo=timezone.utc)
                    except Exception:
                        when = None
                found = {"context": ctx, "time": when, "ttl": ttl}
            elif found["ttl"] is None:
                found["ttl"] = ttl
            if found["ttl"] is not None:
                break
        return found
    except Exception:
        return None


def fmt_age(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 120:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h"
    return f"{hours // 24} d"


def _k(tokens: int) -> str:
    return f"{round(tokens / 1000)}k"


def _epoch(path: Path) -> int:
    try:
        e = json.loads(path.read_text("utf-8")).get("epoch")
        return e if isinstance(e, int) and not isinstance(e, bool) and e >= 0 else 0
    except Exception:
        return 0


def _write_epoch(path: Path, epoch: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"epoch": epoch}), "utf-8")
    os.replace(tmp, path)


def _claim(path: Path, level: str, epoch: int) -> bool:
    """Create the marker for (level, epoch) exclusively; True for the one process that did."""
    try:
        os.close(os.open(path.with_name(f"{path.stem}.{level}.{epoch}"),
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        return True
    except FileExistsError:
        return False


def context_nudge(paths, sid: str, data: dict) -> str:
    """The context-size line for this call, or "". Main session only.

    State: context-<sid>.json holds an epoch, bumped when the context drops
    below the low threshold; a fire is claimed by creating the marker
    context-<sid>.<level>.<epoch> with O_EXCL, so parallel hooks print it once.
    The cap counts markers."""
    if data.get("agent_id"):
        return ""
    window = paths.settings()["context_window"]
    if not window:
        return ""
    u = last_usage(data.get("transcript_path"))
    if not u:
        return ""
    ctx = u["context"]
    path = paths.context_state(sid)
    epoch = _epoch(path)
    here = lambda lv: path.with_name(f"{path.stem}.{lv}.{epoch}").exists()  # noqa: E731
    if ctx < window * LOW:
        if here("low") or here("high"):
            _write_epoch(path, epoch + 1)
        return ""
    if ctx >= window * HIGH:
        level, ok = "high", not here("high")
    else:
        level, ok = "low", not (here("low") or here("high"))
    if not ok:
        return ""

    def fires():
        return len(list(path.parent.glob(f"{path.stem}.low.*"))) + \
            len(list(path.parent.glob(f"{path.stem}.high.*")))
    if fires() >= MAX_FIRES:
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _claim(path, level, epoch):
        return ""
    if fires() > MAX_FIRES:  # lost a race for the last slot
        try:
            path.with_name(f"{path.stem}.{level}.{epoch}").unlink()
        except OSError:
            pass
        return ""
    return f"Synapse: the context is about {_k(ctx)} tokens. {CHECKPOINT}"


def resume_time_line(paths, data: dict) -> str:
    """UserPromptSubmit: the cache expired while idle and the context is large."""
    window = paths.settings()["context_window"]
    if not window:
        return ""
    u = last_usage(data.get("transcript_path"))
    if not u or not u["time"]:
        return ""
    ttl = 300 if u["ttl"] == "5m" else 3600
    idle = (datetime.now(timezone.utc) - u["time"]).total_seconds()
    if idle <= ttl or u["context"] < window * LOW:
        return ""
    return (f"Synapse: idle {fmt_age(idle)} since the last request, so the prompt cache has "
            f"expired and this request rewrites about {_k(u['context'])} tokens. "
            "A /synapse:checkpoint before stepping away keeps /clear free.")


STAMP = re.compile(r"Checkpoint written:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2} [+-]\d{2}:?\d{2})")
HEADING = re.compile(r"^##\s+Resume\b", re.I)


def resume_pointer(paths, data: dict) -> str:
    """SessionStart after /compact or /clear: point at EXECUTION.md ## Resume."""
    if data.get("source") not in ("compact", "clear"):
        return ""
    cwd = data.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return ""
    work = paths.find_work_dir(Path(cwd))
    f = work / "EXECUTION.md"
    if not f.is_file():
        return ""
    with open(f, "rb") as fh:
        text = fh.read(1024 * 1024).decode("utf-8", "replace")
    section = None
    for ln in text.splitlines():
        if section is None:
            if HEADING.match(ln):
                section = []
        elif ln.startswith("## "):
            break
        else:
            section.append(ln)
    if section is None:
        return ""
    when, label = None, "file modified"
    m = STAMP.search("\n".join(section))
    if m:
        try:
            when = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M %z")
            label = "checkpoint written"
        except ValueError:
            when = None
    if when is None:
        when = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)
        label = "file modified"
    age = fmt_age(max(0.0, (datetime.now(timezone.utc) - when).total_seconds()))
    age = age if age == "just now" else f"{age} ago"
    shown = when.astimezone().strftime("%Y-%m-%d %H:%M")
    rel = f
    for base in (Path(cwd), work.parent.parent):
        try:
            rel = f.relative_to(base)
            break
        except ValueError:
            pass
    notes = ("; NOTES.md beside it holds the checkpoint's facts and decisions"
             if (work / "NOTES.md").is_file() else "")
    return (f"Synapse: work in progress is recorded in {rel.as_posix()} under ## Resume "
            f"({label} {shown}, {age}). If this conversation continues that work, "
            f"read it before acting{notes}.")
