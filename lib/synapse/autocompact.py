#!/usr/bin/env python3
"""
autocompact.py — Claude Code's auto-compact window, read from its settings (stdlib only, read-only).

Shared by doctor.py (reports every value it finds), setup_cmd.py, and continuation.py
(derives the window the nudge and the gate measure against). Never writes a file.

  values(settings)              every autoCompactWindow in one settings dict
  effective(model, project_dir) (N, where) for the session's model, or (None, "")
  compaction_point(n, native)   where Claude Code compacts for a window of n
  marks(window, min_context)    where Synapse's gate and 60% / 90% marks land
"""

import json
import os
import sys
from pathlib import Path

ENV = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"

# Claude Code compacts this many tokens before the auto-compact window: its context
# display (/context, the status line) reports a 33k "autocompact buffer" whatever the
# model or the window, and the docs give the matching default for a native 1M model,
# "at about 967K tokens" (code.claude.com/docs/en/context-window). The docs do not
# name the buffer itself; if Claude Code changes it, change this one number.
COMPACT_BUFFER = 33000
# The docs' range for autoCompactWindow (code.claude.com/docs/en/settings-reference):
# 100K to 1M, values outside it clamped, and the value capped at the model's window.
MIN_WINDOW, MAX_WINDOW = 100000, 1000000

MANAGED_SETTINGS = {
    "darwin": Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    "linux": Path("/etc/claude-code/managed-settings.json"),
    "win32": Path(r"C:\Program Files\ClaudeCode\managed-settings.json"),
}


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()


def settings_files(project_dir: Path) -> list[Path]:
    """Claude Code's settings files, lowest precedence first: user, project, local, managed."""
    files = [claude_dir() / "settings.json",
             project_dir / ".claude" / "settings.json",
             project_dir / ".claude" / "settings.local.json"]
    managed = MANAGED_SETTINGS.get(sys.platform)
    return files + [managed] if managed else files


def values(s) -> list[tuple[str, object]]:
    """Every autoCompactWindow in one settings dict: ('top level', v), then (model, v) per modelSettings entry."""
    found: list[tuple[str, object]] = []
    if not isinstance(s, dict):
        return found
    if "autoCompactWindow" in s:
        found.append(("top level", s["autoCompactWindow"]))
    models = s.get("modelSettings")
    if isinstance(models, dict):
        for name, cfg in models.items():
            if isinstance(cfg, dict) and "autoCompactWindow" in cfg:
                found.append((str(name), cfg["autoCompactWindow"]))
    return found


def _norm(name) -> str:
    n = name.strip().lower() if isinstance(name, str) else ""
    return n[:-4] if n.endswith("[1m]") else n


ALIASES = ("opus", "sonnet", "haiku", "fable")


def model_matches(key, model) -> bool:
    """A modelSettings key names the transcript's model: case-insensitive, a [1m]
    suffix ignored on either side, a date suffix on the model ignored (key
    claude-haiku-4-5 matches claude-haiku-4-5-20251001), and a bare alias key
    (opus) matching that family. /autocompact writes the canonical name."""
    k, m = _norm(key), _norm(model)
    if not (k and m):
        return False
    if k in ALIASES:
        return k in m.replace(".", "-").split("-")
    return k == m or (m.startswith(k + "-") and m[len(k) + 1:].isdigit())


def _positive(v):
    """A window in tokens: a positive int, or a string of digits with an optional k suffix."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        t = v.strip().lower()
        scale = 1000 if t.endswith("k") else 1
        t = t[:-1] if scale > 1 else t
        v = int(t) * scale if t.isdigit() else None
    return v if isinstance(v, int) and v > 0 else None


def _read(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            d = json.loads(f.read())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def effective(model, project_dir: Path | None = None):
    """(window, where) Claude Code compacts against for `model`, or (None, "") when
    nothing sets one. CLAUDE_CODE_AUTO_COMPACT_WINDOW beats every setting (docs:
    env-vars); the process environment already holds a settings env block, which is
    read from the files too for doctor-style runs outside a session. A settings layer
    overrides a lower one key by key; a modelSettings entry for the model beats the
    top-level value (docs: within one file; across files the docs are silent, so the
    model's own entry is taken to win there too)."""
    env = _positive(os.environ.get(ENV))
    if env:
        return env, ENV
    per_model = top = env_block = None
    for path in settings_files(project_dir or Path.cwd()):
        s = _read(path)
        if not s:
            continue
        block = s.get("env")
        if isinstance(block, dict) and _positive(block.get(ENV)):
            env_block = (_positive(block.get(ENV)), f"{ENV} in {path.name}")
        for scope, value in values(s):
            v = _positive(value)
            if not v:
                continue
            if scope == "top level":
                top = (v, f"autoCompactWindow in {path.name}")
            elif model_matches(scope, model):
                per_model = (v, f"modelSettings {scope} in {path.name}")
    return env_block or per_model or top or (None, "")


def compaction_point(n: int, native: int = MAX_WINDOW) -> int:
    """Where Claude Code auto-compacts for an auto-compact window of n tokens on a
    model whose context window is `native`: n clamped to 100K..1M and capped at the
    model's window, less the buffer."""
    return min(max(n, MIN_WINDOW), MAX_WINDOW, native) - COMPACT_BUFFER


def _k(tokens: float) -> str:
    return f"{round(tokens / 1000)}k"


def marks(n, min_context: float = 0.5) -> str:
    """Where Claude Code compacts for an auto-compact window n, and where Synapse's
    marks land before it: the deny gate, 60%, and 90% (on a 1M-window model)."""
    from continuation import HIGH, LOW
    v = _positive(n)
    if not v:
        return ""
    w = compaction_point(v)
    return (f"compacts near {_k(w)}; Synapse's deny gate {_k(w * min_context)}, "
            f"60% {_k(w * LOW)}, 90% {_k(w * HIGH)}")
