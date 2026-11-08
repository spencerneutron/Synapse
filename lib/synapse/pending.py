#!/usr/bin/env python3
"""
pending.py — archived sessions that were never extracted.

  synapse pending [--project P] [--json]
  synapse pending --hook            # SessionStart: reads hook JSON, prints a reminder
                                    # (also counts unreviewed automatically extracted notes)

A session is pending when its files are in <store>/archive/<project>/ but
<store>/archive/<project>/.processed/<id>.json is not. The hook form covers
this project only, speaks only on startup and /clear (not on resume or
compaction), and stays silent when [extract] remind = false or nothing is
pending. A file scan only: no Ollama, no DB.
"""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from archive import discover_sessions  # noqa: E402

REMIND_ON = ("startup", "clear")


def pending_sessions(r: paths.Resolved) -> list[str]:
    return [s["id"] for s in discover_sessions(r.archive_dir) if not s["processed"]]


def reminder(project: str, ids: list[str]) -> str:
    n = len(ids)
    return (f"Synapse: {n} archived session{'s' if n != 1 else ''} for project {project!r} "
            f"{'were' if n != 1 else 'was'} never extracted (latest {ids[-1]}). Mention it once "
            "and offer /synapse:extract-session; do not extract without the user's go-ahead.")


def review_line(r: paths.Resolved) -> str | None:
    import review
    old = review.unreviewed(review.load(r))
    if not old:
        return None
    n = len(old)
    first = min((str(e.get("time", ""))[:10] for e in old if e.get("time")), default="an unknown date")
    return (f"Synapse: {n} note{'s' if n != 1 else ''} {'were' if n != 1 else 'was'} written by "
            f"automatic extraction since {first}; `synapse extract review` lists "
            f"{'them' if n != 1 else 'it'}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synapse pending", description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--hook", action="store_true", help="read SessionStart JSON; print a reminder")
    args = parser.parse_args(argv)

    if args.hook:
        try:
            event = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
            if event.get("source", "startup") not in REMIND_ON or not paths.settings()["extract_remind"]:
                return 0
            r = paths.resolve(cwd=Path(event.get("cwd") or Path.cwd()))
            ids = pending_sessions(r)
            lines = ([reminder(r.project, ids)] if ids else []) + [l for l in [review_line(r)] if l]
        except (Exception, SystemExit):  # fail open: a reminder must never break a session
            return 0
        if lines:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                     "additionalContext": "\n".join(lines)}}))
        return 0

    r = paths.resolve(project=args.project)
    ids = pending_sessions(r)
    if args.json:
        print(json.dumps({"project": r.project, "store": r.store, "pending": ids}, indent=2))
    else:
        print(f"{len(ids)} pending in project {r.project!r} (store {r.store!r})"
              + "".join(f"\n  {i}" for i in ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
