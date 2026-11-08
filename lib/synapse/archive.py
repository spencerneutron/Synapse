#!/usr/bin/env python3
"""
archive.py — archive a session's working files into the active store.

  synapse archive [--project P] [--id SESSION_ID] [--workdir DIR]
  synapse archive --auto --hook     # SessionEnd: archive without a model call

Copies DIR/.claude-work/current/{PLAN,EXECUTION,REPORT}.md (whichever exist)
to <store>/archive/<project>/<PREFIX>_<session-id>.md and prints JSON with the
session ID, the copied files, and the path where /end-session writes NOTES.
Copies, never moves: the working files stay for the next session.

The session ID defaults to the local time as YYYY-MM-DD-HHMM; a taken ID gets
-v2, -v3, and so on.

--auto --hook (SessionEnd hook) reads the event JSON from stdin and copies
PLAN, EXECUTION, REPORT and NOTES (whichever exist) in one pass: no model call,
no embedding, no DB. It skips when the content hash matches the last auto
archive of this Claude session or the newest archived session, and reuses the
session's archive ID until that ID is extracted. Off with [archive] on_exit =
false or SYNAPSE_DETACHED. Fails open: any error exits 0 with no output.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

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


def content_hash(files: dict[str, Path]) -> str:
    """sha256 over the files in PREFIXES order, each preceded by its prefix."""
    h = hashlib.sha256()
    for prefix in PREFIXES:
        if prefix in files:
            h.update(prefix.encode() + b"\0" + files[prefix].read_bytes() + b"\0")
    return h.hexdigest()


def auto_archive(event: dict) -> None:
    """The SessionEnd archive. Raises on error; the caller fails open."""
    if os.environ.get("SYNAPSE_DETACHED"):
        return
    cwd = event.get("cwd")
    cwd = Path(cwd) if isinstance(cwd, str) and os.path.isdir(cwd) else Path.cwd()
    os.chdir(cwd)   # a project's .synapse.toml applies
    if not paths.settings()["archive_on_exit"]:
        return
    current = paths.find_work_dir(cwd)
    sources = {p: current / f"{p}.md" for p in PREFIXES}
    sources = {p: f for p, f in sources.items() if f.is_file()}
    if "PLAN" not in sources and "EXECUTION" not in sources:
        return
    digest = content_hash(sources)

    r = paths.resolve(cwd=cwd)
    sid = str(event.get("session_id") or "unknown")
    state_path = paths.auto_archive_state(r, sid)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    if state.get("hash") == digest:
        return
    sessions = discover_sessions(r.archive_dir)
    if sessions:
        # end-session archives the planning files and writes its own NOTES_<id>
        # from the conversation, so NOTES is left out of this comparison.
        plan = lambda files: {p: f for p, f in files.items() if p != "NOTES"}  # noqa: E731
        newest, mine = plan(sessions[-1]["files"]), plan(sources)
        if mine and set(newest) == set(mine) and content_hash(newest) == content_hash(mine):
            return

    session_id = state.get("id")
    reuse = (isinstance(session_id, str) and SAFE_ID_RE.match(session_id)
             and any(s["id"] == session_id and not s["processed"] for s in sessions))
    r.archive_dir.mkdir(parents=True, exist_ok=True)
    if not reuse:
        session_id = free_session_id(r.archive_dir, datetime.now().strftime("%Y-%m-%d-%H%M"))
    for prefix, src in sources.items():
        shutil.copy2(src, r.archive_dir / f"{prefix}_{session_id}.md")

    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_name(f"{state_path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({
        "id": session_id, "hash": digest, "reason": str(event.get("reason") or ""),
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": list(sources),
    }), encoding="utf-8")
    os.replace(tmp, state_path)
    if paths.settings()["extract_on_exit"]:
        import detach
        detach.spawn_extract(cwd, r.project, session_id)


def hook_main() -> int:
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "null")
        if isinstance(event, dict):
            auto_archive(event)
    except (Exception, SystemExit) as e:   # fail open: never block the exit
        print(f"synapse archive --auto: skipped ({type(e).__name__})", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synapse archive", description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", default=None)
    parser.add_argument("--id", dest="session_id", default=None,
                        help="session ID (default: local time, YYYY-MM-DD-HHMM)")
    parser.add_argument("--workdir", type=Path, default=Path.cwd(),
                        help="folder holding .claude-work/current (default: cwd)")
    parser.add_argument("--auto", action="store_true", help="archive only if the content changed")
    parser.add_argument("--hook", action="store_true", help="read SessionEnd JSON from stdin (with --auto)")
    args = parser.parse_args(argv)

    if args.auto and args.hook:
        return hook_main()

    current = paths.work_dir(args.workdir)
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
