#!/usr/bin/env python3
"""
backfill.py — embed all archived sessions into the local vector DB.

Scans `.claude-work/archive/` for session IDs, infers project from the
archive content where possible, and runs `extract.py embed-archive` for
each session that doesn't already have a `.processed/<id>.json` marker.

Usage:
    python kb/scripts/backfill.py                    # interactive
    python kb/scripts/backfill.py --force            # re-embed all sessions
    python kb/scripts/backfill.py --project foo      # apply to all sessions
    python kb/scripts/backfill.py --include-reports  # embed REPORT files too
    python kb/scripts/backfill.py --dry-run          # show what would happen
"""

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Force UTF-8 for stdout/stderr on Windows PowerShell.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


DEFAULT_ARCHIVE_DIR = Path(".claude-work/archive")
DEFAULT_PROCESSED_DIR = Path(".claude-work/archive/.processed")
EXTRACT_SCRIPT = Path("kb/scripts/extract.py")

# Session ID pattern: YYYY-MM-DD-HHMM with optional -vN suffix.
SESSION_ID_RE = re.compile(r"^(?:PLAN|EXECUTION|NOTES|REPORT)_(.+)\.md$")


# ---------- Discovery ----------

def discover_sessions(archive_dir: Path) -> list[dict]:
    """Find all session IDs in the archive directory.

    Returns a list of dicts with: id, files (dict of prefix→path), processed.
    """
    if not archive_dir.is_dir():
        sys.exit(f"error: archive directory not found: {archive_dir}")

    sessions: dict[str, dict] = defaultdict(lambda: {"files": {}})
    processed_dir = archive_dir / ".processed"

    for entry in archive_dir.iterdir():
        if not entry.is_file() or entry.suffix != ".md":
            continue
        m = SESSION_ID_RE.match(entry.name)
        if not m:
            continue
        session_id = m.group(1)
        prefix = entry.name.split("_", 1)[0]
        sessions[session_id]["files"][prefix] = entry

    result = []
    for session_id, data in sessions.items():
        marker = processed_dir / f"{session_id}.json"
        result.append({
            "id": session_id,
            "files": data["files"],
            "processed": marker.exists(),
        })

    # Sort chronologically — session IDs start with YYYY-MM-DD so lex sort works.
    result.sort(key=lambda s: s["id"])
    return result


# ---------- Project inference ----------

def discover_repos(workspace_root: Path) -> list[str]:
    """Find candidate repo names in the workspace root. Used as the
    vocabulary for project inference."""
    skip_dirs = {".claude-work", "kb", ".claude", ".git", "node_modules", "Synapse"}
    repos = []
    for entry in workspace_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in skip_dirs:
            continue
        repos.append(entry.name)
    return sorted(repos)


def infer_project(session: dict, repos: list[str]) -> tuple[str | None, str]:
    """Guess a project name for a session by scanning archive content for
    repo-name mentions. Returns (best_guess, confidence_explanation).

    Strategy: count how many times each known repo name appears in the
    first ~80 lines of PLAN and EXECUTION (the highest-signal regions
    for project naming). Highest count wins, with a minimum threshold."""
    if not repos:
        return None, "no candidate repos found in workspace"

    counts = {repo: 0 for repo in repos}
    sources_scanned = 0

    for prefix in ("PLAN", "EXECUTION"):
        path = session["files"].get(prefix)
        if not path:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sources_scanned += 1
        # Scan first 80 lines — the front matter, purpose, and constraints
        # blocks contain project naming most reliably.
        head = "\n".join(content.splitlines()[:80])
        for repo in repos:
            # Count whole-token occurrences (so "acme.billing" doesn't match
            # "Acme.Billing.Service"; we want the standalone repo name).
            pattern = re.compile(r"(?<![\w.])" + re.escape(repo) + r"(?![\w])")
            counts[repo] += len(pattern.findall(head))

    if not sources_scanned:
        return None, "no PLAN/EXECUTION files to scan"

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top_repo, top_count = ranked[0]

    if top_count == 0:
        return None, "no repo names matched in archive content"

    # Confidence: dominant if top is at least 2x the runner-up
    if len(ranked) > 1:
        runner_up_count = ranked[1][1]
        if top_count >= max(runner_up_count * 2, 2):
            return top_repo, f"{top_count} mentions, dominant"
        if top_count == runner_up_count:
            return top_repo, f"tied with {ranked[1][0]} ({top_count} each)"
    return top_repo, f"{top_count} mention{'s' if top_count != 1 else ''}"


# ---------- Ollama warmup ----------

def warmup_ollama() -> None:
    """Send one trivial embed request so the model loads before the
    real work starts. Avoids a confusing slow first iteration."""
    print("warming up ollama...", end=" ", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, str(EXTRACT_SCRIPT), "init"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if result.returncode == 0:
            print("ok")
        else:
            print(f"warning: init returned {result.returncode}")
            print(result.stderr.strip())
    except subprocess.TimeoutExpired:
        print("timed out (continuing anyway)")


# ---------- Per-session embedding ----------

def embed_session(
    session: dict,
    project: str,
    include_reports: bool,
    force: bool,
    dry_run: bool,
) -> tuple[bool, str]:
    """Run `extract.py embed-archive` for one session. Returns (ok, message)."""
    cmd = [
        sys.executable, str(EXTRACT_SCRIPT),
        "embed-archive", session["id"],
        "--project", project,
    ]
    if force:
        cmd.append("--force")
    if include_reports and "REPORT" in session["files"]:
        cmd.append("--include-report")

    if dry_run:
        return True, "would run: " + " ".join(cmd)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,  # 10 minutes per session — generous for big archives
        )
    except subprocess.TimeoutExpired:
        return False, "timed out after 10 minutes"

    if result.returncode != 0:
        return False, f"exit {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"

    # Pull the summary line out of the output for a tidy report.
    last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no output)"
    return True, last_line


# ---------- Interactive review ----------

def confirm_assignments(assignments: list[dict]) -> list[dict] | None:
    """Show the user each session's inferred project and let them
    accept, override, or skip. Returns the final list, or None if cancelled."""
    print()
    print("=" * 70)
    print(f"Sessions to embed ({len(assignments)} total):")
    print("=" * 70)
    print()

    for i, a in enumerate(assignments, 1):
        files = sorted(a["session"]["files"])
        files_str = "+".join(p[0] for p in files)  # P+E+N or P+E+N+R
        marker = " [reprocess]" if a["session"]["processed"] else ""
        print(f"  {i:>2}. {a['session']['id']}  [{files_str}]  "
              f"→ {a['project'] or '?'}  ({a['rationale']}){marker}")

    print()
    print("Options:")
    print("  yes / y          — proceed with these assignments")
    print("  no / cancel      — abort")
    print("  N <project>      — set project for entry N (e.g. '3 acme.billing')")
    print("  skip N           — exclude entry N from the run")
    print("  all <project>    — apply this project to every entry")

    while True:
        try:
            response = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not response:
            continue

        lower = response.lower()
        if lower in ("yes", "y", "proceed"):
            missing = [a for a in assignments if not a["project"]]
            if missing:
                print(f"  cannot proceed: {len(missing)} session(s) still have no project assigned.")
                continue
            return assignments
        if lower in ("no", "cancel", "abort"):
            return None
        if lower.startswith("all "):
            project = response[4:].strip()
            for a in assignments:
                a["project"] = project
                a["rationale"] = "user override (all)"
            print(f"  applied {project!r} to all {len(assignments)} entries.")
            continue
        if lower.startswith("skip "):
            try:
                idx = int(response.split()[1])
                if 1 <= idx <= len(assignments):
                    assignments[idx - 1]["skipped"] = True
                    print(f"  marked entry {idx} as skipped.")
                else:
                    print(f"  invalid index: {idx}")
            except (ValueError, IndexError):
                print("  usage: skip N")
            continue
        # Pattern: "N <project>"
        parts = response.split(maxsplit=1)
        if len(parts) == 2:
            try:
                idx = int(parts[0])
                project = parts[1].strip()
                if 1 <= idx <= len(assignments):
                    assignments[idx - 1]["project"] = project
                    assignments[idx - 1]["rationale"] = "user override"
                    print(f"  set entry {idx} to project {project!r}.")
                else:
                    print(f"  invalid index: {idx}")
                continue
            except ValueError:
                pass
        print(f"  unrecognized input: {response!r}")


# ---------- Entry point ----------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--workspace-root", type=Path, default=Path("."),
                        help="root for repo-name discovery (default: cwd)")
    parser.add_argument("--project", default=None,
                        help="apply this project to all sessions; skips inference")
    parser.add_argument("--force", action="store_true",
                        help="re-embed sessions even if already processed")
    parser.add_argument("--include-reports", action="store_true",
                        help="also embed REPORT files where present")
    parser.add_argument("--dry-run", action="store_true",
                        help="show plan without making changes")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="skip interactive confirmation (use with caution)")
    args = parser.parse_args()

    if not EXTRACT_SCRIPT.exists():
        sys.exit(f"error: cannot find {EXTRACT_SCRIPT}. run from workspace root.")

    print(f"scanning {args.archive_dir} ...")
    sessions = discover_sessions(args.archive_dir)
    print(f"  found {len(sessions)} session(s)")

    if not args.force:
        unprocessed = [s for s in sessions if not s["processed"]]
        already = len(sessions) - len(unprocessed)
        if already:
            print(f"  {already} already processed (use --force to re-embed)")
        sessions = unprocessed

    if not sessions:
        print("nothing to do.")
        return 0

    repos = discover_repos(args.workspace_root)
    print(f"  candidate projects from workspace: {', '.join(repos) if repos else '(none)'}")

    # Build initial assignments
    assignments = []
    for session in sessions:
        if args.project:
            project, rationale = args.project, "from --project flag"
        else:
            project, rationale = infer_project(session, repos)
        assignments.append({
            "session": session,
            "project": project,
            "rationale": rationale,
            "skipped": False,
        })

    # Interactive review unless --yes
    if not args.yes:
        confirmed = confirm_assignments(assignments)
        if confirmed is None:
            print("cancelled.")
            return 1
        assignments = confirmed
    else:
        # Auto-confirm requires every session have a project assigned
        missing = [a for a in assignments if not a["project"]]
        if missing:
            sys.exit(f"error: --yes given but {len(missing)} session(s) "
                     f"have no project. specify --project or run interactively.")

    # Filter out skipped entries
    work = [a for a in assignments if not a["skipped"]]
    if not work:
        print("everything skipped. exiting.")
        return 0

    if not args.dry_run:
        warmup_ollama()

    print()
    print("=" * 70)
    print(f"embedding {len(work)} session(s)")
    print("=" * 70)

    succeeded = 0
    failed = []

    for i, a in enumerate(work, 1):
        sid = a["session"]["id"]
        proj = a["project"]
        print(f"\n[{i}/{len(work)}] {sid} → {proj}")
        ok, msg = embed_session(
            session=a["session"],
            project=proj,
            include_reports=args.include_reports,
            force=args.force,
            dry_run=args.dry_run,
        )
        print(f"    {msg}")
        if ok:
            succeeded += 1
        else:
            failed.append((sid, msg))

    print()
    print("=" * 70)
    print(f"done. {succeeded} succeeded, {len(failed)} failed.")
    if failed:
        print("\nfailures:")
        for sid, msg in failed:
            print(f"  {sid}: {msg}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())