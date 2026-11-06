#!/usr/bin/env python3
"""
compact_guide.py — what the compaction summary should keep (PreCompact hook).

  synapse compact-guide --hook   # PreCompact: reads hook JSON, prints plain text

Claude Code uses a PreCompact hook's stdout as instructions for the
compaction summary. This prints about 1,000 characters of guidance: what to
keep, what to drop, where the planning files are, and that the user's own
compact instructions take precedence. Stdlib only: no Ollama, no database,
no venv. It must never block compaction: it always exits 0, prints plain
text (never JSON, never a decision), and on any error prints the static text
or nothing.
"""

import json
import sys
import time
from pathlib import Path

RESUME_WINDOW_S = 30 * 60

KEEP = """\
Guidance for this compaction summary (from the Synapse plugin).
Worth keeping: the user's objective in their own words; the active step and the next action; decisions with their rationale and the alternatives rejected; facts the user stated or confirmed, marked "user-stated"; open questions and decisions waiting on the user; the state of the work (branch, uncommitted files, last test command and its result, background jobs still running).
Safe to drop: tool output, logs, file contents that are on disk, search results, superseded attempts, diffs already reported.
Where a planning file holds an item, a pointer to the file is enough; restating it adds nothing."""


def read_input() -> dict:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "null")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def has_heading(path: Path, needle: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    return any(line.lstrip("# ").strip().lower().startswith(needle)
               for line in text.splitlines() if line.startswith("#"))


def recent_resume(path: Path) -> bool:
    """EXECUTION.md has a '## Resume' section and was modified in the last 30 minutes."""
    try:
        if time.time() - path.stat().st_mtime > RESUME_WINDOW_S:
            return False
    except Exception:
        return False
    return has_heading(path, "resume")


def build(data: dict) -> str:
    parts = [KEEP]
    cwd = data.get("cwd")
    root = Path(cwd) if isinstance(cwd, str) and cwd else None
    if root is not None:
        try:
            import paths
            work = paths.find_work_dir(root)
            found = [(work / n).as_posix() for n in ("PLAN.md", "EXECUTION.md", "CHECKPOINTS.md")
                     if (work / n).is_file()]
            if found:
                parts.append("Planning files that exist and are the source of truth for plan, progress, and checkpoints: "
                             + ", ".join(found) + ".")
            if recent_resume(work / "EXECUTION.md"):
                parts.append("EXECUTION.md has a '## Resume' section written in the last 30 minutes, "
                             "so the summary can stay short and point to it.")
        except Exception:
            pass
        try:
            if has_heading(root / "CLAUDE.md", "compact instructions"):
                parts.append("The project's CLAUDE.md has a 'Compact instructions' section; those instructions take precedence over this guidance.")
        except Exception:
            pass
    custom = data.get("custom_instructions")
    if isinstance(custom, str) and custom.strip():
        parts.append("The user gave their own instructions for this compaction; they take precedence over this guidance.")
    return "\n".join(parts)


def main(argv: list[str]) -> int:
    try:
        if "--hook" not in argv:
            print(__doc__.strip())
            return 0
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            text = build(read_input())
        except Exception:
            text = KEEP
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(text[:9000])
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
