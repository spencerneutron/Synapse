#!/usr/bin/env python3
"""
archive.py — archive a session's working files into the active store.

  synapse archive [--project P] [--id SESSION_ID] [--workdir DIR]

Copies DIR/.claude-work/current/{PLAN,EXECUTION,REPORT}.md (whichever exist)
to <store>/archive/<project>/<PREFIX>_<session-id>.md and prints JSON with the
session ID, the copied files, and the path where /end-session writes NOTES.
Copies, never moves: the working files stay for the next session.

The session ID defaults to the local time as YYYY-MM-DD-HHMM; a taken ID gets
-v2, -v3, and so on.
"""

import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

PREFIXES = ("PLAN", "EXECUTION", "NOTES", "REPORT")
SESSION_FILE_RE = re.compile(r"^(PLAN|EXECUTION|NOTES|REPORT)_(.+)\.md$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def discover_sessions(archive_dir: Path) -> list[dict]:
    """Session IDs in one archive folder, oldest first.

    Each item: {"id", "files": {prefix: path}, "processed": bool}.
    """
    if not archive_dir.is_dir():
        return []
    sessions: dict[str, dict] = defaultdict(dict)
    for entry in archive_dir.iterdir():
        m = SESSION_FILE_RE.match(entry.name)
        if entry.is_file() and m:
            sessions[m.group(2)][m.group(1)] = entry
    processed = archive_dir / ".processed"
    return sorted(
        ({"id": sid, "files": files, "processed": (processed / f"{sid}.json").exists()}
         for sid, files in sessions.items()),
        key=lambda s: s["id"],
    )


def free_session_id(archive_dir: Path, base: str) -> str:
    taken = {s["id"] for s in discover_sessions(archive_dir)}
    if base not in taken:
        return base
    n = 2
    while f"{base}-v{n}" in taken:
        n += 1
    return f"{base}-v{n}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", default=None)
    parser.add_argument("--id", dest="session_id", default=None,
                        help="session ID (default: local time, YYYY-MM-DD-HHMM)")
    parser.add_argument("--workdir", type=Path, default=Path.cwd(),
                        help="folder holding .claude-work/current (default: cwd)")
    args = parser.parse_args(argv)

    current = args.workdir / ".claude-work" / "current"
    sources = {p: current / f"{p}.md" for p in ("PLAN", "EXECUTION", "REPORT")}
    sources = {p: f for p, f in sources.items() if f.is_file()}
    if not sources:
        sys.exit(f"error: nothing to archive: no PLAN.md or EXECUTION.md in {current}")

    base = args.session_id or datetime.now().strftime("%Y-%m-%d-%H%M")
    if not SAFE_ID_RE.match(base):
        sys.exit(f"error: unsafe session ID {base!r}: use letters, digits, '.', '_' and '-'")

    r = paths.resolve(project=args.project, cwd=args.workdir)
    r.archive_dir.mkdir(parents=True, exist_ok=True)
    session_id = free_session_id(r.archive_dir, base)

    copied = []
    for prefix, src in sources.items():
        dest = r.archive_dir / f"{prefix}_{session_id}.md"
        shutil.copy2(src, dest)
        copied.append(str(dest))

    print(json.dumps({
        "session_id": session_id,
        "project": r.project,
        "store": r.store,
        "archive_dir": str(r.archive_dir),
        "copied": copied,
        "missing": [p for p in ("PLAN", "EXECUTION") if p not in sources],
        "notes_path": str(r.archive_dir / f"NOTES_{session_id}.md"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
