#!/usr/bin/env python3
"""
shared.py — team memory: a shared folder of Decisions and Patterns, changed
through git or a synced folder, with a local index per team.

  synapse shared init <team> --author NAME (--remote URL | --path DIR [--transport folder])
  synapse shared join <team> <remote-or-folder> --author NAME
  synapse shared sync [<team>...] [--quiet]      # pull (git) and re-index
  synapse shared status [--json]
  synapse shared retract <team> <note> --reason TEXT
  synapse shared push <team>                     # git only; ask the user first
  synapse shared hook                            # SessionStart: background sync

The folder is the source of truth and the index (<home>/shared/<team>/
vectors.db) is rebuilt from it by content hash, so both transports share one
code path: git only adds pull, commit, and push. Nothing here prompts for
credentials or writes outside the Synapse home and the team's notes folder.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

FOLDERS = ("Decisions", "Patterns")
RETRACTED = "Retracted"
MANIFEST = ".synapse-team.toml"
FORMAT = 1
SYNC_EVERY_S = 10 * 60          # automatic sync at most this often
STALE_AFTER_S = 3 * 24 * 3600   # a failing sync is mentioned after this long
LOCK_STALE_S = 10 * 60
GIT_TIMEOUT_S = 60
REMIND_ON = ("startup", "clear")
# Sync-service conflict copies: Dropbox "(… conflicted copy …)", Syncthing
# ".sync-conflict-…", and "Name 2.md" duplicates (iCloud, Drive) of a Name.md.
CONFLICT_RE = re.compile(r"conflicted copy|\.sync-conflict-", re.I)
DUPLICATE_RE = re.compile(r"^(.*) \d+\.md$")
TITLE_RE = re.compile(r"^# (.+)$", re.M)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def die(msg: str) -> None:
    sys.exit(f"error: {msg}")


def get_team(name: str) -> paths.Team:
    team = paths.teams().get(name)
    if not team:
        die(f"no team {name!r} in {paths.config_path()} (see `synapse shared status`)")
    return team


# ---------- git ----------

def git_env() -> dict:
    """Never wait for a password: no terminal prompt, no askpass or credential
    manager window, SSH in batch mode. Stored credentials (keychain, helpers)
    still work; anything that would ask fails instead."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
           "SSH_ASKPASS_REQUIRE": "never"}
    if sys.platform != "win32" and shutil.which("true"):
        env["GIT_ASKPASS"] = shutil.which("true")   # answers nothing: the request fails
    ssh = env.get("GIT_SSH_COMMAND", "ssh")
    if "BatchMode" not in ssh:
        env["GIT_SSH_COMMAND"] = f"{ssh} -o BatchMode=yes"
    return env


def is_checkout(team: paths.Team) -> bool:
    return (team.notes / ".git").exists()


def require_checkout(team: paths.Team) -> None:
    """A git team's folder must be its own clone: `git -C` on a plain folder
    inside another repo would pull, commit, and push that repo instead."""
    if team.transport == "git" and not is_checkout(team):
        die(f"{team.notes} is not a git clone; rejoin the team (synapse shared join) "
            "or set transport = \"folder\"")


def git(team_or_dir, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    if isinstance(team_or_dir, paths.Team):
        require_checkout(team_or_dir)
    where = team_or_dir.notes if isinstance(team_or_dir, paths.Team) else team_or_dir
    try:
        p = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                           env=git_env(), timeout=GIT_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        die("git is not installed (needed for a git team)")
    except subprocess.TimeoutExpired:
        die(f"git {args[0]} timed out after {GIT_TIMEOUT_S} s")
    if check and p.returncode != 0:
        die(f"git {' '.join(args[:2])}: {last_line(p)}")
    return p


def last_line(p: subprocess.CompletedProcess) -> str:
    lines = (p.stderr or p.stdout or "").strip().splitlines()
    return lines[-1] if lines else "failed"


def has_upstream(team: paths.Team) -> bool:
    return git(team, "rev-parse", "--abbrev-ref", "@{u}", check=False).returncode == 0


def unpushed(team: paths.Team) -> int | None:
    """Commits not on the remote yet (None for a folder team)."""
    if team.transport != "git" or not is_checkout(team):
        return None
    if has_upstream(team):
        out = git(team, "rev-list", "--count", "@{u}..HEAD", check=False).stdout.strip()
    else:
        out = git(team, "rev-list", "--count", "HEAD", check=False).stdout.strip()
    return int(out) if out.isdigit() else 0


def commit(team: paths.Team, message: str, *files: Path) -> bool:
    """Stage the given paths and commit. Uses the member's git identity, or
    the team author when the checkout has none."""
    if team.transport != "git":
        return False
    git(team, "add", "-A", "--", *(str(f) for f in files))
    if git(team, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    ident = [] if git(team, "config", "user.email", check=False).stdout.strip() else [
        "-c", f"user.name={team.author}", "-c", f"user.email={team.author}@users.noreply.invalid"]
    git(team, *ident, "commit", "-q", "-m", message)
    return True


# ---------- folder layout ----------

def write_layout(notes: Path, team: str) -> list[Path]:
    """Create the team folder's skeleton; never overwrites a file."""
    made = []
    for folder in (*FOLDERS, RETRACTED):
        keep = notes / folder / ".gitkeep"
        if not keep.exists():
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_text("", encoding="utf-8")
            made.append(keep)
    files = {
        MANIFEST: f'team = "{team}"\nformat = {FORMAT}\n',
        ".gitattributes": "*.md text eol=lf\n",
        "README.md": (f"# {team}: Synapse team notes\n\nShared Decisions and Patterns. "
                      "Add notes with `/synapse:share`, which scrubs paths, secrets, and "
                      "session-local references first; retract with `synapse shared retract`. "
                      "Each member's index is local and rebuilt from this folder.\n"),
    }
    for name, text in files.items():
        f = notes / name
        if not f.exists():
            f.write_text(text, encoding="utf-8")
            made.append(f)
    return made


def title(f: Path) -> str | None:
    try:
        m = TITLE_RE.search(f.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return m.group(1).strip() if m else None


def note_files(notes: Path) -> tuple[list[Path], list[Path], int]:
    """(notes to index, conflict copies, cloud placeholders) under Decisions/
    and Patterns/. Retracted/ and dot-files are never indexed."""
    keep, conflicts, placeholders = [], [], 0
    for folder in FOLDERS:
        base = notes / folder
        if not base.is_dir():
            continue
        names = {f.name for f in base.iterdir()}
        for f in sorted(base.iterdir()):
            if f.name.startswith("."):
                placeholders += f.name.endswith(".icloud")
                continue
            if f.suffix != ".md" or not f.is_file():
                continue
            dup = DUPLICATE_RE.match(f.name)
            twin = base / f"{dup.group(1)}.md" if dup and f"{dup.group(1)}.md" in names else None
            # "Name 2.md" is a sync copy only when it is the same note as
            # "Name.md" (same title); "Use Swift 6.md" is a note of its own.
            if CONFLICT_RE.search(f.name) or (twin and title(twin) == title(f)):
                conflicts.append(f)
            else:
                keep.append(f)
    return keep, conflicts, placeholders


# ---------- config ----------

def check_names(team: str, author: str | None) -> None:
    if not paths.TEAM_NAME.fullmatch(team):
        die("team names use a-z, 0-9, - and _ (40 at most), starting with a letter or digit")
    if author is not None and not paths.AUTHOR.fullmatch(author):
        die("--author: letters, digits, space, . ' and - (40 at most)")


def toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def add_team_config(name: str, fields: dict) -> None:
    """Append a [shared.<name>] table to config.toml, keeping everything else."""
    cfg = paths.config_path()
    check_names(name, fields.get("author"))
    if name in paths.teams():
        die(f"team {name!r} is already in {cfg}")
    lines = [f"\n[shared.{name}]"]
    for k, v in fields.items():
        if v is not None:
            lines.append(f"{k} = {toml_str(v) if isinstance(v, str) else json.dumps(v)}")
    cfg.parent.mkdir(parents=True, exist_ok=True)
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    cfg.write_text(text.rstrip("\n") + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


# ---------- index ----------

def reindex(team: paths.Team) -> dict:
    """Bring the team's index in line with its folder: add new notes, replace
    changed ones, drop removed or retracted ones. Content-hash based, so an
    unchanged folder costs no embedding calls."""
    import extract  # lazy: the hook path must not start the venv

    import scrub

    keep, conflicts, placeholders = note_files(team.notes)
    held = []
    team.db.parent.mkdir(parents=True, exist_ok=True)
    conn = extract.db_connect(team.db)
    extract.db_init(conn, team.db)
    conn.execute("CREATE TABLE IF NOT EXISTS team_files (source_path TEXT PRIMARY KEY, content_hash TEXT)")
    known = dict(conn.execute("SELECT source_path, content_hash FROM team_files").fetchall())
    added = updated = removed = 0

    def drop(rel: str) -> None:
        ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE source_path = ?", (rel,))]
        extract.delete_chunks(conn, ids)
        conn.execute("DELETE FROM team_files WHERE source_path = ?", (rel,))

    seen = set()
    for f in keep:
        rel = f"{f.parent.name}/{f.name}"
        seen.add(rel)
        content = f.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode()).hexdigest()
        if known.get(rel) == digest:
            continue
        # The inbound gate: a note with a secret, an identifier, or text aimed
        # at an agent never reaches this member's prompts, whoever wrote it.
        bad = [x for x in scrub.lint(content) if x.outcome == scrub.BLOCKED or x.kind == "agent-directed"]
        if bad:
            held.append({"note": rel, "findings": sorted({x.kind for x in bad})})
            seen.discard(rel)
            continue
        fm, _ = extract.parse_frontmatter(content)
        author = fm.get("author") if paths.AUTHOR.fullmatch(fm.get("author") or "") else None
        chunks = extract.chunk_document(content=content, source_path=rel,
                                        source_type=fm.get("type") or f.parent.name.lower().rstrip("s"),
                                        session_id=None, project=fm.get("project") or None)
        status = "superseded" if fm.get("status") == "superseded" else "active"
        drop(rel)
        extract.store_chunks(conn, chunks, status=status, origin=team.name, author=author)
        conn.execute("INSERT OR REPLACE INTO team_files VALUES (?, ?)", (rel, digest))
        conn.commit()
        added += rel not in known
        updated += rel in known
    for rel in set(known) - seen:
        drop(rel)
        removed += 1
    conn.commit()
    return {"notes": len(keep) - len(held), "added": added, "updated": updated, "removed": removed,
            "conflicts": [str(c) for c in conflicts], "placeholders": placeholders, "held": held}


# ---------- state and locking ----------

def read_state(team: paths.Team) -> dict:
    try:
        return json.loads(team.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(team: paths.Team, **updates) -> None:
    state = {**read_state(team), **updates}
    team.state.parent.mkdir(parents=True, exist_ok=True)
    tmp = team.state.with_name(f"{team.state.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, team.state)


class Lock:
    """One sync per team at a time; a lock older than LOCK_STALE_S is broken."""

    def __init__(self, team: paths.Team, wait_s: float = 0):
        self.path, self.wait_s = team.dir / "sync.lock", wait_s

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                if time.time() - self.path.stat().st_mtime > LOCK_STALE_S:
                    self.path.unlink()
            except OSError:
                pass
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    die(f"another sync of {self.path.parent.name!r} is running; try again shortly")
                time.sleep(0.5)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


def sync(team: paths.Team) -> dict:
    """Pull (git, fast-forward only) and re-index. A failed pull is recorded
    and the local folder is still indexed."""
    with Lock(team):
        write_state(team, last_attempt=now_iso())
        result, error = {"pulled": False}, None
        if not team.notes.is_dir():
            error = f"notes folder missing: {team.notes}"
        elif team.transport == "git" and not is_checkout(team):
            error = f"{team.notes} is not a git clone"
        elif team.transport == "git" and has_upstream(team):
            p = git(team, "pull", "--ff-only", "-q", check=False)
            result["pulled"] = p.returncode == 0
            error = None if p.returncode == 0 else f"git pull: {last_line(p)}"
        if team.notes.is_dir():
            try:
                result.update(reindex(team))
            except SystemExit as e:  # Ollama down, no sqlite-vec: index next time
                error = error or str(e).removeprefix("error: ").splitlines()[0]
        write_state(team, last_error=error, **({} if error else {"last_success": now_iso()}),
                    conflicts=result.get("conflicts", []), held=result.get("held", []))
        return {**result, "error": error}


# ---------- commands ----------

def cmd_init(args) -> int:
    check_names(args.team, args.author)
    transport = args.transport or ("folder" if args.path and not args.remote else "git")
    if transport == "folder" and not args.path:
        die("a folder team needs --path <a folder your sync service shares>")
    notes = Path(args.path).expanduser().resolve() if args.path else paths.team_dir(args.team) / "notes"
    if notes.exists() and any(notes.iterdir()) and not (notes / MANIFEST).exists():
        die(f"{notes} is not empty and is not a Synapse team folder")
    notes.mkdir(parents=True, exist_ok=True)
    write_layout(notes, args.team)
    if transport == "git" and not (notes / ".git").exists():
        git(notes, "init", "-q", "-b", "main")
        if args.remote:
            git(notes, "remote", "add", "origin", args.remote)
    add_team_config(args.team, {"transport": transport, "remote": args.remote,
                                "path": str(notes) if args.path else None, "author": args.author})
    team = get_team(args.team)
    commit(team, f"Create Synapse team {args.team}", notes)
    sync(team)
    print(f"created team {args.team!r} ({transport}) at {notes}")
    if transport == "git" and args.remote:
        print(f"push it once you are ready: synapse shared push {args.team}")
    return 0


def cmd_join(args) -> int:
    check_names(args.team, args.author)
    if args.team in paths.teams():
        die(f"team {args.team!r} is already in {paths.config_path()}")
    src = args.source
    local = Path(src).expanduser()
    # A synced folder holds the manifest itself; anything else (a URL, a bare
    # repo, a clone) is a git source.
    is_folder = (local / MANIFEST).is_file() and not (local / ".git").exists()
    transport = args.transport or ("folder" if is_folder else "git")
    if transport == "folder":
        notes = Path(src).expanduser().resolve()
        if not (notes / MANIFEST).exists():
            die(f"{notes} has no {MANIFEST}: not a Synapse team folder")
        fields = {"transport": "folder", "path": str(notes), "author": args.author}
    else:
        notes = paths.team_dir(args.team) / "notes"
        if notes.exists() and any(notes.iterdir()):
            die(f"{notes} already exists")
        notes.parent.mkdir(parents=True, exist_ok=True)
        git(notes.parent, "clone", "-q", src, str(notes))
        if not (notes / MANIFEST).exists():
            # A bare repo made with another default branch: HEAD names a branch
            # that was never pushed. Check out the one that was (main first).
            branches = git(notes, "for-each-ref", "--format=%(refname:lstrip=3)", "refs/remotes/origin").stdout.split()
            branch = "main" if "main" in branches else next((b for b in branches if b != "HEAD"), None)
            if branch:
                git(notes, "checkout", "-q", "-B", branch, "--track", f"origin/{branch}", check=False)
        if not (notes / MANIFEST).exists():
            shutil.rmtree(notes)
            die(f"{src} has no {MANIFEST}: not a Synapse team repo")
        fields = {"transport": "git", "remote": src, "author": args.author}
    add_team_config(args.team, fields)
    res = sync(get_team(args.team))
    print(f"joined team {args.team!r} ({transport}): {res.get('notes', 0)} notes"
          + (f"; index later: {res['error']}" if res["error"] else ""))
    return 0


def cmd_sync(args) -> int:
    all_teams = paths.teams()
    names = args.teams or list(all_teams)
    failed = 0
    for name in names:
        team = all_teams.get(name) or get_team(name)
        try:
            res = sync(team)
        except SystemExit as e:
            res = {"error": str(e).removeprefix("error: ")}
        failed += bool(res["error"])
        if not args.quiet:
            line = (f"{name}: {res.get('notes', 0)} notes, +{res.get('added', 0)} "
                    f"~{res.get('updated', 0)} -{res.get('removed', 0)}"
                    + (", pulled" if res.get("pulled") else ""))
            print(line + (f"; error: {res['error']}" if res["error"] else ""))
            for c in res.get("conflicts", []):
                print(f"  conflict copy, not indexed: {c}")
            for h in res.get("held", []):
                print(f"  held back by the scrub gate ({', '.join(h['findings'])}): {h['note']}")
    return 1 if failed else 0


def team_status(team: paths.Team) -> dict:
    keep, conflicts, placeholders = note_files(team.notes) if team.notes.is_dir() else ([], [], 0)
    st = read_state(team)
    return {"team": team.name, "transport": team.transport, "notes_dir": str(team.notes),
            "notes": len(keep), "author": team.author, "remote": team.remote,
            "last_success": st.get("last_success"), "last_error": st.get("last_error"),
            "unpushed": unpushed(team), "conflicts": [str(c) for c in conflicts],
            "held": st.get("held", []), "placeholders": placeholders, "indexed": team.db.exists(),
            "auto_sync": team.auto_sync}


def cmd_status(args) -> int:
    rows = [team_status(t) for t in paths.teams().values()]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no teams (synapse shared init or synapse shared join)")
    for r in rows:
        print(f"{r['team']} ({r['transport']}, author {r['author']}): {r['notes']} notes in {r['notes_dir']}")
        print(f"  last sync: {r['last_success'] or 'never'}"
              + (f"; last error: {r['last_error']}" if r["last_error"] else ""))
        if r["unpushed"]:
            print(f"  {r['unpushed']} commit(s) not pushed: synapse shared push {r['team']}")
        for c in r["conflicts"]:
            print(f"  conflict copy, not indexed: {c}")
        for h in r["held"]:
            print(f"  held back by the scrub gate ({', '.join(h['findings'])}): {h['note']}")
    return 0


def find_note(team: paths.Team, ref: str) -> Path:
    """A note in the team's Decisions/ or Patterns/, by name or by a path that
    points there. Nothing outside the team folder can be retracted."""
    folders = [(team.notes / f).resolve() for f in FOLDERS]
    p = Path(ref).expanduser()
    if len(p.parts) > 1:
        p = p.resolve()
        if p.parent not in folders or not p.is_file():
            die(f"{ref!r} is not a note in team {team.name!r} ({team.notes})")
        return p
    name = ref if ref.endswith(".md") else f"{ref}.md"
    hits = [f / name for f in folders if (f / name).is_file()]
    if not hits:
        die(f"no note {ref!r} in {team.notes}/{{{','.join(FOLDERS)}}}")
    return hits[0]


def cmd_retract(args) -> int:
    import vault_write

    team = get_team(args.team)
    reason = args.reason.strip()
    if not reason or len(reason) > 200 or any(ord(c) < 32 for c in reason):
        die("--reason: one line, 200 characters at most")
    require_checkout(team)
    src = find_note(team, args.note)
    dest = team.notes / RETRACTED / src.name
    if dest.exists():
        dest = dest.with_name(f"{src.stem} ({datetime.now():%Y-%m-%d %H%M}).md")
    with Lock(team, wait_s=15):
        vault_write.set_frontmatter(src, {"status": "retracted", "retracted_at": now_iso(),
                                          "retracted_by": team.author, "reason": reason})
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dest)
        committed = commit(team, f"Retract: {src.stem} ({team.author})", src, dest)
    sync(team)
    print(f"retracted {src.name} -> {dest.relative_to(team.notes)}"
          + (f"; push to reach the team: synapse shared push {team.name}" if committed else ""))
    return 0


def cmd_push(args) -> int:
    team = get_team(args.team)
    if team.transport != "git":
        print(f"{team.name} is a folder team: the sync service carries changes; nothing to push")
        return 0
    if has_upstream(team):
        p = git(team, "pull", "--rebase", "-q", check=False)
        if p.returncode != 0:
            git(team, "rebase", "--abort", check=False)
            die(f"could not rebase onto the remote: {last_line(p)}")
        git(team, "push", "-q")
    else:
        git(team, "push", "-q", "-u", "origin", "HEAD")
    write_state(team, last_push=now_iso())
    print(f"pushed {team.name}")
    return 0


def spawn_sync(names: list[str]) -> None:
    """Start `synapse shared sync --quiet <names>` detached: the session never
    waits for the network or the embedder."""
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "cli.py"), "shared", "sync", "--quiet", *names]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
          "close_fds": True}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


def due(team: paths.Team, now: float) -> bool:
    last = read_state(team).get("last_attempt")
    try:
        return now - datetime.fromisoformat(last).timestamp() > SYNC_EVERY_S
    except (TypeError, ValueError):
        return True


def stale_note(team: paths.Team, now: float) -> str | None:
    st = read_state(team)
    if not st.get("last_error"):
        return None
    since = st.get("last_success") or st.get("first_attempt")
    try:
        if since and now - datetime.fromisoformat(since).timestamp() < STALE_AFTER_S:
            return None
    except ValueError:
        pass
    return (f"Synapse: team {team.name!r} has not synced since {since or 'it was added'} "
            f"({st['last_error']}). Mention it once; `synapse shared sync {team.name}` shows the error.")


def cmd_hook(args) -> int:
    """SessionStart: start a background sync for teams that are due, and
    mention a sync that has failed for days. Silent and fast otherwise."""
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        all_teams = list(paths.teams().values())
        if not all_teams:
            return 0
        now = time.time()
        for t in all_teams:
            if not read_state(t).get("first_attempt"):
                write_state(t, first_attempt=now_iso())
        due_now = [t for t in all_teams if t.auto_sync and due(t, now)]
        for t in due_now:
            write_state(t, last_attempt=now_iso())
        if due_now:
            spawn_sync([t.name for t in due_now])
        notes = [n for t in all_teams if (n := stale_note(t, now))] \
            if event.get("source", "startup") in REMIND_ON else []
    except (Exception, SystemExit):  # fail open: sharing must never break a session
        return 0
    if notes:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": "\n".join(notes)}}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a team folder (git repo or synced folder)")
    p.add_argument("team")
    p.add_argument("--author", required=True, help="your name, written into notes you share")
    p.add_argument("--remote", default=None, help="git remote URL (git teams)")
    p.add_argument("--path", default=None, help="folder for the notes (required for a folder team)")
    p.add_argument("--transport", choices=paths.TRANSPORTS, default=None)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("join", help="join a team from a git remote or a synced folder")
    p.add_argument("team")
    p.add_argument("source", help="git remote URL, or the team's synced folder")
    p.add_argument("--author", required=True)
    p.add_argument("--transport", choices=paths.TRANSPORTS, default=None)
    p.set_defaults(func=cmd_join)

    p = sub.add_parser("sync", help="pull (git) and re-index; all teams by default")
    p.add_argument("teams", nargs="*")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("status", help="teams, last sync, unpushed commits, conflict copies")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("retract", help="move a shared note to Retracted/")
    p.add_argument("team")
    p.add_argument("note", help="file path or note name")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_retract)

    p = sub.add_parser("push", help="push a git team's commits (ask the user first)")
    p.add_argument("team")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("hook", help="SessionStart handler: background sync")
    p.set_defaults(func=cmd_hook)

    args = parser.parse_args(argv)
    if args.cmd in ("init", "join", "sync", "retract"):
        # These index notes. Importing extract may re-exec this process under
        # the Synapse venv; do it before any side effect, or the command runs
        # twice (the hook path stays light and never imports it).
        import extract  # noqa: F401
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
