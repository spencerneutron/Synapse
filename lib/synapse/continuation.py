#!/usr/bin/env python3
"""
continuation.py — context-size facts for the nudge hook (stdlib only, no I/O beyond small files).

Called from nudge.handle; it never prints and never raises on its own account.
  last_usage(path)         tail-read a transcript for the newest main-session usage entry
  window_for(...)          the context window for a session and where it came from
                           (Claude Code's auto-compact point when its settings set one)
  context_nudge(...)       PostToolUse: one line at 60% and 90% of the context window
  resume_time_line(...)    UserPromptSubmit: the prompt cache expired while idle
  resume_pointer(...)      SessionStart (compact or clear): point at EXECUTION.md ## Resume
  cross / uncross          when the context reached 60% / 90% (for the Stop gate in gate.py)
  resume_written(path)     when EXECUTION.md's ## Resume was last written
"""

import json
import os
import re
import time
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
    """Newest main-session assistant usage: {"context", "time", "ttl", "model"} or None."""
    return scan(transcript_path)[0]


def scan(transcript_path, boundary=False):
    """(usage, observed): the newest usage as in last_usage, and the preTokens of the
    newest compact_boundary in the tail if it was an auto-compaction (else None).
    The boundary lies behind the newest usage, so it is only looked for (reading on
    to it, or to the tail cap) when boundary is true (about 3 ms over a full 2 MiB tail)."""
    observed = None
    try:
        if not isinstance(transcript_path, str) or not os.path.isfile(transcript_path):
            return None, None
        found = None
        for line in _tail_lines(transcript_path):
            if b"compact_boundary" in line:
                try:
                    b = json.loads(line)
                except Exception:
                    b = None
                if isinstance(b, dict) and b.get("type") == "system" \
                        and b.get("subtype") == "compact_boundary":
                    meta = b.get("compactMetadata")
                    if isinstance(meta, dict) and meta.get("trigger") == "auto":
                        pre = _int(meta.get("preTokens"))
                        observed = pre if pre > 0 else None
                    break  # older usage predates the compaction: stale
            if b'"usage"' not in line or b'"assistant"' not in line:
                continue
            if found is not None and found["ttl"] is not None:
                continue  # usage is complete; reading on only to find the boundary
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
                model = msg.get("model")
                found = {"context": ctx, "time": when, "ttl": ttl,
                         "model": model if isinstance(model, str) else ""}
            elif found["ttl"] is None:
                found["ttl"] = ttl
            if found["ttl"] is not None and not boundary:
                break
        return found, observed
    except Exception:
        return None, observed


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


def _state(path: Path) -> dict:
    try:
        d = json.loads(path.read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _nat(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _epoch(path: Path) -> int:
    return _nat(_state(path).get("epoch"))


def _observed(path: Path) -> int:
    return _nat(_state(path).get("observed"))


def _write_state(path: Path, **changes) -> None:
    """Merge changes into the state file atomically; keys not named are kept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _state(path)
    data.update(changes)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data), "utf-8")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


_NEW = re.compile(r"claude-([a-z]+)-(\d+)(?:[-.](\d{1,2}))?(?!\d)")
_OLD = re.compile(r"claude-(\d+)(?:[-.](\d{1,2}))?-([a-z]+)")
ALIASES = ("opus", "sonnet", "haiku", "fable")


def _big_model(name) -> bool:
    """True for a 1M-window model, from its name: claude-<family>-<major>[-<minor>]
    ("-" or "." between the numbers), where a date suffix is ignored. 1M-class: the
    fable family, major 5 or later, or opus 4.7 or later. A name that parses with an
    older version (sonnet 4.5, haiku 4.5, opus 4.6, claude-3-5-sonnet) is not, and
    neither is a name without "claude" that is no bare alias (gpt-4o, a gateway
    model). A bare alias (opus, haiku, ...), no name, or a claude name that does not
    parse counts as 1M-class, because the current aliases point at 1M-class models.
    "[1m]" in a name counts too, but transcripts never carry it: a [1m] opt-in on a
    4.x model is invisible here, and those users set [nudge] context_window."""
    n = name.lower().strip() if isinstance(name, str) else ""
    if "[1m]" in n or not n or n in ALIASES:
        return True
    m = _NEW.search(n)
    if m:
        family, major, minor = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    else:
        m = _OLD.search(n)
        if not m:
            return "claude" in n
        major, minor, family = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    return family == "fable" or major >= 5 or (family == "opus" and (major, minor) >= (4, 7))


def window_for(paths, sid, u, observed):
    """(window, source) for this session; window is 0 when the context lines are off.

    1. [nudge] context_window in config.toml (0 = off): "from your config".
    2. Otherwise Claude Code's auto-compact window for the session's model, from its
       settings or CLAUDE_CODE_AUTO_COMPACT_WINDOW (autocompact.effective), as the
       point where it compacts: the value capped at the model's window, less the
       33k buffer (300000 -> 267000, so 90% is 240300, before compaction):
       "from the auto-compact window".
    3. Otherwise the model's window, by name alone (no model table to go stale):
       300000 for a 1M-window model, 150000 for an older one (marks at 90k and 135k
       on a 200k window). These are intended marks, not compaction-relative: unset,
       a 1M model compacts near 967k. See _big_model: "from the model".
    4. An auto compact_boundary in the session can only lower that. Its preTokens is
       the context size when compaction ran, which overshoots the threshold, so the
       smallest one seen is the closest to it (a mid-session /model switch from 1M to
       200k lowers it too): "from an earlier auto-compaction". A manual /compact
       happens at a size the user chose, so it is never counted. The smallest value
       is kept in the state file, because the boundary scrolls out of the tail."""
    explicit = paths.settings()["context_window"]
    if explicit is not None:
        return explicit, "from your config"
    seen = observed or 0
    if isinstance(sid, str) and sid:
        state = paths.context_state(sid)
        saved = _observed(state)
        if saved and (not seen or saved < seen):
            seen = saved
        elif seen:  # new smallest
            try:
                _write_state(state, observed=seen)
            except OSError:
                pass  # another hook holds the file; the value is still used this call
    model = (u or {}).get("model")
    big = _big_model(model)
    window, source = (300000 if big else 150000), "from the model"
    try:
        import autocompact
        n, _ = autocompact.effective(model)
        if n:
            window = autocompact.compaction_point(n, 1000000 if big else 200000)
            source = f"from the auto-compact window {_k(n)}"
    except Exception:
        pass  # unreadable settings: keep the model's window
    if seen and seen < window:
        return seen, "from an earlier auto-compaction"
    return window, source


def _claim(path: Path, level: str, epoch: int) -> bool:
    """Create the marker for (level, epoch) exclusively; True for the one process that did."""
    try:
        os.close(os.open(path.with_name(f"{path.stem}.{level}.{epoch}"),
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        return True
    except FileExistsError:
        return False


def cross(path: Path, level: str) -> float:
    """When the context first reached `level` ("low" 60%, "high" 90%) since it was
    last below 60%: recorded in the state file on first sight, now if absent."""
    d = _state(path).get("crossed")
    d = d if isinstance(d, dict) else {}
    t = d.get(level)
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        return float(t)
    now = time.time()
    d[level] = now
    if level == "high":
        d.setdefault("low", now)
    _write_state(path, crossed=d)
    return now


def uncross(path: Path) -> None:
    """The context is below 60% (after a compaction): forget the crossing times."""
    if _state(path).get("crossed"):
        try:
            _write_state(path, crossed=None)
        except OSError:
            pass


def context_nudge(paths, sid: str, data: dict) -> str:
    """The context-size line for this call, or "". Main session only.

    State: context-<sid>.json holds an epoch, bumped when the context drops
    below the low threshold; a fire is claimed by creating the marker
    context-<sid>.<level>.<epoch> with O_EXCL, so parallel hooks print it once.
    The cap counts markers."""
    if data.get("agent_id"):
        return ""
    explicit = paths.settings()["context_window"]
    if explicit == 0:
        return ""
    u, observed = scan(data.get("transcript_path"), explicit is None)
    window, source = window_for(paths, sid, u, observed)
    if not window or not u:
        return ""
    ctx = u["context"]
    path = paths.context_state(sid)
    epoch = _epoch(path)
    here = lambda lv: path.with_name(f"{path.stem}.{lv}.{epoch}").exists()  # noqa: E731
    if ctx < window * LOW:
        if here("low") or here("high"):
            _write_state(path, epoch=epoch + 1)
        uncross(path)
        return ""
    try:
        cross(path, "high" if ctx >= window * HIGH else "low")
    except OSError:
        pass
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
    return (f"Synapse: the context is about {_k(ctx)} tokens (window {_k(window)}, {source}). "
            f"{CHECKPOINT}")


def resume_time_line(paths, data: dict, sid=None) -> str:
    """UserPromptSubmit: the cache expired while idle and the context is large."""
    explicit = paths.settings()["context_window"]
    if explicit == 0:
        return ""
    u, observed = scan(data.get("transcript_path"), explicit is None)
    if not u or not u["time"]:
        return ""
    try:
        window, _ = window_for(paths, sid, u, observed)
    except Exception:
        return ""
    if not window:
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


def _resume(f: Path):
    """(when, label) for EXECUTION.md's ## Resume section, or None without one:
    the section's checkpoint stamp, else the file's modification time."""
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
        return None
    m = STAMP.search("\n".join(section))
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M %z"), "checkpoint written"
        except ValueError:
            pass
    return datetime.fromtimestamp(f.stat().st_mtime, timezone.utc), "file modified"


def resume_written(f: Path):
    """When ## Resume in EXECUTION.md was last written (its stamp, else the file's
    modification time), or None when the file or the section is missing."""
    try:
        found = _resume(Path(f)) if Path(f).is_file() else None
    except OSError:
        return None
    return found[0] if found else None


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
    found = _resume(f)
    if found is None:
        return ""
    when, label = found
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
