#!/usr/bin/env python3
"""
migrate.py — copy a V1 or v1.5 workspace's memory into the active store.

  synapse migrate --from DIR [--project P] [--dry-run]

Reads DIR/.claude-work/archive/ and DIR/.claude-work/kb/vectors.db and never
writes to either (the DB is read from a copy in the system temp folder, deleted
afterwards). Each archived session lands in <store>/archive/<project>/,
where the project comes from --project, else the session's .processed marker,
else a guess from the repo names under DIR, else "unsorted".

DB chunks merge into the store's vectors.db with their paths rewritten to the
portable form (archive/<project>/<file>, vault/<Folder>/<file>). Chunks already
present are skipped, so migrate is safe to re-run and to run once per old
workspace. Vault notes are not copied: point the store's `vault` at the vault
V1 used.
"""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 for stdout/stderr on Windows PowerShell.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract  # noqa: E402  (re-execs under the Synapse venv when needed)
import paths  # noqa: E402
from archive import discover_sessions  # noqa: E402


# ---------- Project inference (carried over from V1's backfill.py) ----------

def discover_repos(workspace_root: Path) -> list[str]:
    """Find candidate repo names in the workspace root. Used as the
    vocabulary for project inference."""
    skip_dirs = {".claude-work", "kb", ".claude", ".git", "node_modules"}
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


# ---------- Plan ----------

def plan_sessions(src_archive: Path, repos: list[str], forced: str | None) -> list[tuple]:
    plan = []
    for s in discover_sessions(src_archive):
        project, why = None, ""
        if forced:
            project, why = forced, "--project"
        else:
            marker = src_archive / ".processed" / f"{s['id']}.json"
            if marker.exists():
                try:
                    project = json.loads(marker.read_text(encoding="utf-8")).get("project")
                    why = "marker"
                except (OSError, json.JSONDecodeError):
                    project = None
            if not project:
                project, why = infer_project(s, repos)
                why = f"guessed ({why})"
            if not project:
                project, why = "unsorted", "no marker, no repo match"
        plan.append((s, paths.safe_project(project), why))
    return plan


def copy_sessions(plan, r: paths.Resolved, src_archive: Path, copy_markers: bool,
                  dry: bool) -> dict:
    stats = {"copied": 0, "identical": 0, "conflicts": [], "markers": 0}
    for s, project, _ in plan:
        dest_dir = r.archive_root / project
        for src in s["files"].values():
            dest = dest_dir / src.name
            if dest.exists():
                if dest.read_bytes() == src.read_bytes():
                    stats["identical"] += 1
                else:
                    stats["conflicts"].append(f"{project}/{src.name}")
                continue
            if not dry:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            stats["copied"] += 1

        marker = src_archive / ".processed" / f"{s['id']}.json"
        dest_marker = dest_dir / ".processed" / marker.name
        if copy_markers and marker.exists() and not dest_marker.exists():
            if not dry:
                data = json.loads(marker.read_text(encoding="utf-8"))
                data["project"] = project
                data["files"] = [f"archive/{project}/{Path(f).name}" for f in data.get("files", [])]
                data["migrated_at"] = datetime.now(timezone.utc).isoformat()
                dest_marker.parent.mkdir(parents=True, exist_ok=True)
                dest_marker.write_text(json.dumps(data, indent=2), encoding="utf-8")
            stats["markers"] += 1
    return stats


# ---------- DB merge ----------

ARCHIVE_PATH_RE = re.compile(r"(^|/)\.claude-work/archive/[^/]+$")


def portable_path(stored: str, project: str) -> str:
    """V1 stored cwd-relative, other-workspace, and absolute paths; rewrite them."""
    norm = stored.replace("\\", "/")
    name = norm.rsplit("/", 1)[-1]
    if ARCHIVE_PATH_RE.search(norm):
        return f"archive/{project}/{name}"
    parts = norm.split("/")
    if len(parts) >= 2 and parts[-2] in paths.VAULT_FOLDERS:
        return f"vault/{parts[-2]}/{name}"
    return stored


def chunk_hash(source_path: str, chunk_index: int, text: str) -> str:
    """Must match extract.Chunk.hash()."""
    h = hashlib.sha256()
    h.update(source_path.encode())
    h.update(str(chunk_index).encode())
    h.update(text.encode())
    return h.hexdigest()


def merge_db(src_db: Path, r: paths.Resolved, session_projects: dict, dry: bool) -> dict:
    stats = {"inserted": 0, "present": 0, "no_vector": 0}
    with tempfile.TemporaryDirectory() as tmp:
        # Work on a copy: the source DB is never opened for writing.
        src_copy = Path(tmp) / "src.db"
        shutil.copy2(src_db, src_copy)
        if dry:
            src = sqlite3.connect(src_copy)
            src.row_factory = sqlite3.Row
            dst = sqlite3.connect(f"file:{r.db}?mode=ro", uri=True) if r.db.exists() else None
        else:
            src = extract.db_connect(src_copy)
            dst = extract.db_connect(r.db)
            extract.db_init(dst)

        for row in src.execute("SELECT * FROM chunks ORDER BY id").fetchall():
            project = session_projects.get(row["session_id"]) or paths.safe_project(
                row["project"] or "unsorted")
            new_path = portable_path(row["source_path"], project)
            new_hash = chunk_hash(new_path, row["chunk_index"], row["text"])
            if dst is not None and dst.execute(
                    "SELECT 1 FROM chunks WHERE chunk_hash = ?", (new_hash,)).fetchone():
                stats["present"] += 1
                continue
            if dry:
                stats["inserted"] += 1
                continue
            vec = src.execute("SELECT embedding FROM chunks_vec WHERE rowid = ?",
                              (row["id"],)).fetchone()
            if vec is None:
                stats["no_vector"] += 1
                continue
            cur = dst.execute(
                """INSERT INTO chunks (chunk_hash, source_path, source_type, session_id,
                   project, chunk_index, text, metadata, embedding_model, embedding_dim,
                   created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_hash, new_path, row["source_type"], row["session_id"],
                 project if row["source_type"] == "archive" else row["project"],
                 row["chunk_index"], row["text"], row["metadata"],
                 row["embedding_model"], row["embedding_dim"], row["created_at"]),
            )
            dst.execute("INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
                        (cur.lastrowid, vec[0]))
            stats["inserted"] += 1
        if not dry:
            dst.commit()
        src.close()
        if dst is not None:
            dst.close()
    return stats


# ---------- Entry point ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from", dest="source", type=Path, required=True,
                        help="the old workspace root (holds .claude-work/)")
    parser.add_argument("--project", default=None,
                        help="put every session under this project")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    src = args.source.expanduser().resolve()
    src_archive = src / ".claude-work" / "archive"
    src_db = src / ".claude-work" / "kb" / "vectors.db"
    if not src_archive.is_dir() and not src_db.is_file():
        sys.exit(f"error: no .claude-work/archive or .claude-work/kb/vectors.db under {src}")

    r = paths.resolve()
    plan = plan_sessions(src_archive, discover_repos(src), args.project)
    session_projects = {s["id"]: project for s, project, _ in plan}

    tag = "[dry run] " if args.dry_run else ""
    print(f"{tag}migrating {src} -> store {r.store!r} ({r.store_path})")
    for s, project, why in plan:
        print(f"  {s['id']:<24} -> {project:<16} {why}")

    db_stats = merge_db(src_db, r, session_projects, args.dry_run) if src_db.is_file() else None
    stats = copy_sessions(plan, r, src_archive, copy_markers=db_stats is not None,
                          dry=args.dry_run)

    print(f"{tag}archive: {stats['copied']} file(s) copied, {stats['identical']} already "
          f"present, {stats['markers']} marker(s)")
    for c in stats["conflicts"]:
        print(f"  conflict, left as is: {c} differs from the store's copy")
    if db_stats:
        print(f"{tag}vectors: {db_stats['inserted']} chunk(s) added, {db_stats['present']} "
              f"already present" + (f", {db_stats['no_vector']} without a vector"
                                    if db_stats["no_vector"] else ""))
    else:
        print("vectors: no old DB; run `synapse backfill` to embed the copied sessions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
