#!/usr/bin/env python3
"""
backfill.py — embed archived sessions in the active store that have no
.processed marker yet. An archive folder's name is its project.

Usage:
    synapse backfill                       # every project in the store
    synapse backfill --project billing-api # one project
    synapse backfill --dry-run             # list what would be embedded
    synapse backfill --force               # re-embed sessions already processed
    synapse backfill --include-reports     # embed REPORT files too
"""

import argparse
import sys
from pathlib import Path

# Force UTF-8 for stdout/stderr on Windows PowerShell.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract  # noqa: E402  (re-execs under the Synapse venv when needed)
import paths  # noqa: E402
from archive import discover_sessions  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--include-reports", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    r = paths.resolve(project=args.project)
    if args.project:
        projects = [r.project]
    elif r.archive_root.is_dir():
        projects = sorted(d.name for d in r.archive_root.iterdir() if d.is_dir())
    else:
        projects = []

    todo = [(p, s) for p in projects for s in discover_sessions(r.archive_root / p)
            if args.force or not s["processed"]]
    if not todo:
        print(f"nothing to embed in store {r.store!r} ({r.archive_root})")
        return 0

    for project, s in todo:
        print(f"  {project}/{s['id']}  ({', '.join(sorted(s['files']))})")
    if args.dry_run:
        print(f"{len(todo)} session(s) would be embedded into {r.db}")
        return 0

    failures = 0
    for project, s in todo:
        ns = argparse.Namespace(
            session_id=s["id"], project=project, archive_dir=None,
            processed_dir=None, force=args.force,
            include_report=args.include_reports, db=r.db,
        )
        try:
            extract.cmd_embed_archive(ns)
        except SystemExit as e:
            failures += 1
            print(f"  {project}/{s['id']}: {e}", file=sys.stderr)

    print(f"backfill: {len(todo) - failures} embedded, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
