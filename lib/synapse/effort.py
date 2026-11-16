#!/usr/bin/env python3
"""
effort.py — per-effort planning folders in .claude-work/efforts/<slug>/.

  synapse effort list [--all] [--json]       open efforts (the SessionEnd index text); --all adds parked and closed
  synapse effort start SLUG [--title T]      new folder with PLAN.md and EXECUTION.md; binds this session
  synapse effort resume SLUG                 make an open effort active and bind this session to it
  synapse effort wait SLUG --on TEXT         record what the effort waits on
  synapse effort park SLUG [--reason T]      set the effort aside
  synapse effort done SLUG [--reason T] [--json]   archive it and close it
  synapse effort cancel SLUG --reason T [--json]   archive it and close it, cancelled
  synapse effort migrate ...                 split .claude-work/current into efforts (effort_migrate.py)

An effort is a folder with an effort.json (status active, waiting, parked, done,
cancelled), its own PLAN.md and EXECUTION.md, and optional NOTES, REPORT and
ARTIFACTS. A session is bound to one effort through a small file in the Synapse
home; the hooks read it so the planning files they touch are that effort's.
Library functions used by hooks never raise. Nothing here deletes a user's file:
a closed effort's folder is moved to efforts/_closed/ (os.rename, retried later
by sweep_closed when it fails). Stdlib only.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive  # noqa: E402
import paths  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
BIND_FILES = ("plan.md", "execution.md", "notes.md")
INDEX_LIMIT = 15
INDEX_CAP = 4000
INDEX_MORE = "- more not shown: `synapse effort list`"
SWEEP_AFTER_S = 3600
CLAIM_STALE_S = 60


class EffortError(Exception):
    """A user-facing failure: main prints `error: <message>` and exits 1."""


# ---- files -----------------------------------------------------------------

def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _write_bytes(path: Path, data: bytes) -> None:
    """Atomic: a temp file in the same folder, then os.replace (retried on
    Windows when another process holds the target open)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _write_text(path: Path, text: str) -> None:
    _write_bytes(path, text.encode("utf-8"))


def _json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def read(root, slug: str) -> dict | None:
    return _json(paths.effort_file(root, slug))


def write(root, slug: str, meta: dict) -> None:
    meta = dict(meta)
    meta["slug"] = slug
    meta["updated"] = _iso(_now())
    f = paths.effort_file(root, slug)
    f.parent.mkdir(parents=True, exist_ok=True)
    _write_text(f, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


def _folders(root):
    base = paths.efforts_dir(root)
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return []
    return [e for e in entries
            if e.is_dir() and not e.name.startswith(("_", ".")) and paths.valid_slug(e.name)]


def _touched(folder: Path) -> float:
    return max(_mtime(folder / n) for n in ("EXECUTION.md", "PLAN.md", "effort.json"))


def _collect(root, statuses) -> list[dict]:
    out = []
    for folder in _folders(root):
        meta = _json(paths.effort_file(root, folder.name))
        if meta and meta.get("status") in statuses:
            out.append({**meta, "slug": folder.name, "touched": _touched(folder)})
    return out


def open_efforts(root) -> list[dict]:
    """Active and waiting efforts."""
    return _collect(root, ("active", "waiting"))


def parked_efforts(root) -> list[dict]:
    return _collect(root, ("parked",))


def all_efforts(root) -> list[dict]:
    """Open, parked, closed-in-place and efforts moved to _closed/ (key closed_folder)."""
    out = _collect(root, (*paths.EFFORT_OPEN, *paths.EFFORT_CLOSED))
    try:
        moved = sorted(paths.closed_dir(root).iterdir())
    except OSError:
        moved = []
    for folder in moved:
        meta = _json(folder / "effort.json") if folder.is_dir() else None
        if meta and meta.get("status") in paths.EFFORT_CLOSED:
            slug = meta.get("slug") or re.sub(r"^\d{4}-\d{2}-\d{2}-\d{4}-|-(?:v?\d+)$", "", folder.name)
            out.append({**meta, "slug": slug, "touched": _touched(folder), "closed_folder": str(folder)})
    return out


# ---- bindings and handoff --------------------------------------------------

def _usable(session_id) -> bool:
    """A session ID that survives sanitizing; one that sanitizes to nothing binds nothing."""
    return isinstance(session_id, str) and bool(paths._safe_id(session_id))


def _bound(root, session_id) -> str | None:
    return paths.bound_effort(root, session_id) if _usable(session_id) else None


def bind(session_id: str, root, slug: str) -> None:
    if not _usable(session_id):
        return
    f = paths.effort_state(session_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    _write_text(f, json.dumps({"root": os.path.abspath(str(root)), "slug": slug, "time": _iso(_now())}))


def touch(session_id) -> None:
    try:
        if _usable(session_id):
            os.utime(paths.effort_state(session_id), None)
    except Exception:
        pass


def others_on(root, slug: str, session_id, within_s: float = 1800) -> float | None:
    """Seconds since the freshest other session bound to this effort was active, within the window."""
    try:
        own = paths.effort_state(session_id) if _usable(session_id) else None
        ages = []
        for f in paths.effort_states():
            if f == own:
                continue
            d = _json(f)
            if d and d.get("slug") == slug and paths.same_path(d.get("root", ""), root):
                age = time.time() - _mtime(f)
                if age <= within_s:
                    ages.append(max(age, 0.0))
        return min(ages) if ages else None
    except Exception:
        return None


def handoff_write(root, slug: str, session_id: str) -> None:
    try:
        f = paths.effort_handoff(root, session_id)
        f.parent.mkdir(parents=True, exist_ok=True)
        _write_text(f, json.dumps({"slug": slug, "from": session_id, "time": time.time()}))
    except Exception:
        pass


def handoff_claim(root, session_id, max_age_s: float = 20) -> str | None:
    """The effort a session that just ended with /clear was on, when exactly one
    such session ended within max_age_s. Claimed once: the file is renamed, read, deleted."""
    try:
        fresh = []
        for f in paths.effort_handoffs(root):
            d = _json(f)
            if (d and isinstance(d.get("time"), (int, float)) and time.time() - d["time"] <= max_age_s
                    and d.get("from") != session_id):
                fresh.append(f)
        if len(fresh) != 1:
            return None
        claimed = fresh[0].with_name(f"{fresh[0].stem}.{os.getpid()}.claimed")
        os.replace(fresh[0], claimed)
        d = _json(claimed)
        try:
            claimed.unlink()
        except OSError:
            pass
        slug = d.get("slug") if d else None
        meta = read(root, slug) if paths.valid_slug(slug) else None
        return slug if meta and meta.get("status") in paths.EFFORT_OPEN else None
    except Exception:
        return None


# ---- the index -------------------------------------------------------------

def _age(seconds: float) -> str:
    minutes = int(max(seconds, 0) // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 48 * 60:
        return f"{minutes // 60}h ago"
    return f"{minutes // 1440}d ago"


def _clip(text, n: int = 80) -> str:
    return " ".join(str(text or "").split())[:n]


def _status_label(e: dict) -> str:
    if e.get("status") == "waiting":
        return f"waiting on: {_clip(e.get('waiting_on'))}"
    return str(e.get("status"))


def _sibling_lines(root, now: float) -> list[str]:
    rows = []
    for s in paths.sibling_roots(root):
        for e in open_efforts(s):
            rows.append((e["touched"], s.name, e))
    if not rows:
        return []
    rows.sort(key=lambda r: r[0], reverse=True)
    lines = ["Other checkouts of this repository (their own folders; not resumable from here):"]
    for touched, name, e in rows[:5]:
        lines.append(f"- {name}: {e['slug']} [{e['status']}] {_clip(e.get('title'))} ({_age(now - touched)})")
    if len(rows) > 5:
        lines.append(f"- and {len(rows) - 5} more")
    return lines


def _current_line(root) -> str:
    """The index line about a current/ that still holds planning files."""
    try:
        marker = paths._json_dict(paths.split_marker(root))
        snap = marker.get("snapshot_id") if marker else None
        if isinstance(snap, str) and snap:
            return (f"- (no effort) .claude-work/current/ is the pre-split copy (snapshot {_clip(snap, 60)}); "
                    "read the efforts, not it. `synapse effort migrate --retire-current` moves it away "
                    "on the user's word.")
    except Exception:
        pass
    return ("- (no effort) .claude-work/current/ still holds planning files; "
            "`synapse effort migrate` proposes a split.")


def index_text(root, session_id=None, now=None, full: bool = False) -> str:
    """What SessionEnd-to-start shows the model about a project's efforts. "" for a
    project with no efforts folder. Cut to INDEX_CAP unless `full`. Never raises."""
    try:
        if not root or not paths.efforts_dir(root).is_dir():
            return ""
        now = time.time() if now is None else now
        opened = sorted(open_efforts(root), key=lambda e: e["touched"], reverse=True)
        parked = parked_efforts(root)
        wd = paths.work_dir(root)
        legacy = (wd / "PLAN.md").is_file() or (wd / "EXECUTION.md").is_file()
        if not opened and not parked and not legacy:
            return ("Synapse efforts in this project: 0 open, 0 parked. "
                    "Start new work with `synapse effort start <slug> --title \"...\"`.")
        bound = _bound(root, session_id)
        head = [f"Synapse efforts in this project: {len(opened)} open, {len(parked)} parked. "
                f"This session is on {bound or 'none yet'}."]
        if bound:
            head.append(f"Its files are in .claude-work/efforts/{bound}/; read no other effort's files. "
                        "Switch with `synapse effort resume <slug>`.")
        elif not opened and parked:
            head.append("Parked efforts: `synapse effort list --all`; start new work with "
                        "`synapse effort start <slug> --title \"...\"`.")
        else:
            head.append("Take one up with `synapse effort resume <slug>`, or start new work with "
                        "`synapse effort start <slug> --title \"...\"`; read only that effort's files "
                        "(.claude-work/efforts/<slug>/).")
        body = []
        for e in opened[:INDEX_LIMIT]:
            extra = ""
            other = others_on(root, e["slug"], session_id) if e["slug"] != bound else None
            if other is not None:
                extra = f"; another session {_age(other)}"
            line = (f"- {e['slug']} [{_status_label(e)}] {_clip(e.get('title'))} "
                    f"({_age(now - e['touched'])}{extra})")
            if e["slug"] == bound:
                line += " (this session)"
            body.append(line)
        tail = []
        if len(opened) > INDEX_LIMIT:
            tail.append(f"- and {len(opened) - INDEX_LIMIT} more: `synapse effort list`")
        if legacy:
            tail.append(_current_line(root))
        tail.extend(_sibling_lines(root, now))

        def join(lines, hint):
            return "\n".join(head + lines + ([INDEX_MORE] if hint else []) + tail)

        text = join(body, False)
        if full or len(text) <= INDEX_CAP:
            return text
        while body and len(join(body, True)) > INDEX_CAP:
            body.pop()
        text = join(body, True)
        if len(text) > INDEX_CAP:   # the tail alone is too long
            text = text[:INDEX_CAP].rsplit("\n", 1)[0]
        return text
    except Exception:
        return ""


# ---- hooks -----------------------------------------------------------------

def hook_bind(data) -> None:
    """PostToolUse fallback: a main-session write to an open effort's PLAN, EXECUTION
    or NOTES binds a session that is on no effort."""
    try:
        if not isinstance(data, dict) or data.get("agent_id") or data.get("tool_name") not in EDIT_TOOLS:
            return
        sid = data.get("session_id")
        inp = data.get("tool_input") or {}
        p = inp.get("file_path") or inp.get("notebook_path")
        if not _usable(sid) or not isinstance(p, str):
            return
        norm = p.replace("\\", "/")
        marker = "/" + "/".join(paths.efforts_dir(Path("x")).parts[-2:]) + "/"
        if marker not in norm:
            return
        prefix, rest = norm.split(marker, 1)
        parts = rest.split("/")
        if len(parts) != 2 or parts[1].lower() not in BIND_FILES or not paths.valid_slug(parts[0]):
            return
        root = Path(prefix or "/")
        meta = read(root, parts[0])
        if meta and meta.get("status") in paths.EFFORT_OPEN and not _bound(root, sid):
            bind(sid, root, parts[0])
    except Exception:
        pass


def stale_notice(session_id, cwd) -> str:
    """A line for a session whose bound effort was closed (by it or another session); drops the
    binding. An effort.json that cannot be read leaves the binding alone and says nothing."""
    try:
        if not _usable(session_id):
            return ""
        f = paths.effort_state(session_id)
        state = _json(f)
        root = paths.work_root(Path(cwd))
        if not state or not root or not paths.same_path(state.get("root", ""), root):
            return ""
        slug = state.get("slug")
        if not paths.valid_slug(slug) or _bound(root, session_id):
            return ""
        meta = read(root, slug)
        if meta is None and paths.effort_dir(root, slug).exists():
            return ""   # unreadable effort.json (typo, a file locked for a moment)
        if meta is not None and meta.get("status") not in paths.EFFORT_CLOSED:
            return ""
        if meta is None:
            found = [e for e in all_efforts(root) if e["slug"] == slug and e.get("closed_folder")]
            meta = max(found, key=lambda e: e["touched"]) if found else None
        try:
            f.unlink()
        except OSError:
            pass
        tail = ("Take up another with `synapse effort resume <slug>` or `synapse effort start <slug>` "
                "before more planning.")
        if not meta or meta.get("status") not in paths.EFFORT_CLOSED:
            return f"Synapse: effort '{slug}' that this session was on is no longer open. {tail}"
        archive_id = meta.get("archive_id")
        detail = f"{meta['status']}, archive {archive_id}" if archive_id else str(meta["status"])
        return f"Synapse: effort '{slug}' that this session was on is closed ({detail}). {tail}"
    except Exception:
        return ""


# ---- closing ---------------------------------------------------------------

def _claim_fresh(path: Path) -> bool:
    return time.time() - _mtime(path) < CLAIM_STALE_S


def sweep_closed(root, force_slug: str | None = None) -> None:
    """Move closed efforts' folders to _closed/. Retried by every start and close. Never raises."""
    try:
        for folder in _folders(root):
            meta = _json(paths.effort_file(root, folder.name))
            if not meta or meta.get("status") not in paths.EFFORT_CLOSED:
                continue
            claim = paths.effort_claim(root, folder.name)
            if claim.exists() and _claim_fresh(claim):
                continue
            try:
                updated = datetime.fromisoformat(str(meta.get("updated")))
            except ValueError:
                updated = datetime.fromtimestamp(_mtime(folder / "effort.json")).astimezone()
            if folder.name != force_slug and time.time() - updated.timestamp() <= SWEEP_AFTER_S:
                continue
            base = meta.get("archive_id")
            if not (isinstance(base, str) and archive.SAFE_ID_RE.fullmatch(base)):
                base = f"{updated:%Y-%m-%d-%H%M}-{folder.name}"   # missing or unsafe: never a path
            try:
                paths.closed_dir(root).mkdir(parents=True, exist_ok=True)
                target, n = paths.closed_dir(root) / base, 2
                while target.exists():
                    target = paths.closed_dir(root) / f"{base}-{n}"
                    n += 1
                os.rename(folder, target)
            except OSError:
                continue
    except Exception:
        pass


def _outcome_line(status: str, reason: str, now: datetime) -> str:
    word = "Done" if status == "done" else "Cancelled"
    text = " ".join((reason or "").split()) or ("completed" if status == "done" else "")
    return f"- ({now:%Y-%m-%d}) {word}: {text}"


def add_outcome(data: bytes, line: str) -> bytes:
    """PLAN text with the Outcome line under `## Outcome` (heading added at the end if
    missing). Line endings are kept; a line already present is not added again."""
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    new = line.encode("utf-8")
    lines = data.splitlines(keepends=True)
    if any(l.rstrip(b"\r\n") == new for l in lines):
        return data
    head = next((i for i, l in enumerate(lines) if re.match(rb"^##[ \t]+Outcome[ \t]*$", l.rstrip(b"\r\n"))), None)
    if head is None:
        if data and not data.endswith(b"\n"):
            data += eol
        return data + (eol if data else b"") + b"## Outcome" + eol + new + eol
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith(b"## ")), len(lines))
    at = end
    while at > head + 1 and not lines[at - 1].strip():
        at -= 1
    if not lines[at - 1].endswith(b"\n"):
        lines[at - 1] += eol
    lines.insert(at, new + eol)
    return b"".join(lines)


def _notes_to_archive(folder: Path) -> bool:
    f = folder / "NOTES.md"
    if not f.is_file():
        return False
    last = [l for l in f.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    return not (last and last[-1].startswith("<!-- merged into NOTES_"))


def _claim_id(claim: Path) -> str:
    """The archive ID a crashed close left in its claim, else ""."""
    try:
        text = claim.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text if archive.SAFE_ID_RE.fullmatch(text) else ""


def _take_claim(claim: Path, slug: str) -> str:
    """Create the close claim exclusively. Returns the archive ID of a stale
    claim taken over ("" when none). The new claim has a fresh mtime."""
    stale_id = ""
    if claim.exists():
        if _claim_fresh(claim):
            raise EffortError(f"effort {slug!r} is being closed by another session")
        stale_id = _claim_id(claim)
        try:
            claim.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            raise EffortError(f"cannot close {slug!r}: {e}")
    try:
        os.close(os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise EffortError(f"effort {slug!r} is being closed by another session")
    except OSError as e:
        raise EffortError(f"cannot close {slug!r}: {e}")
    return stale_id


def close(root, slug: str, status: str, reason: str, r=None, now: datetime | None = None) -> dict:
    """Archive an effort's files and mark it done or cancelled. Raises EffortError
    with effort.json and PLAN.md untouched when the claim or the archive fails. A
    crash after the archive copy leaves the claim holding the archive ID; the rerun
    that takes the stale claim over reuses that archive."""
    now = now or _now()
    folder = paths.effort_dir(root, slug)
    meta = read(root, slug)
    if not meta:
        raise EffortError(f"no effort {slug!r}")
    if meta.get("status") not in paths.EFFORT_OPEN:
        raise EffortError(f"effort {slug!r} is already closed ({meta.get('status')})")
    r = r or paths.resolve(cwd=Path(root))
    claim = paths.effort_claim(root, slug)
    stale_id = _take_claim(claim, slug)
    release = True
    try:
        meta = read(root, slug)   # another closer may have finished between the first read and the claim
        if not meta:
            raise EffortError(f"no effort {slug!r}")
        if meta.get("status") not in paths.EFFORT_OPEN:
            raise EffortError(f"effort {slug!r} is already closed ({meta.get('status')})")
        line = _outcome_line(status, reason, now)
        plan = folder / "PLAN.md"
        sources = {}
        try:
            if plan.is_file():
                sources["PLAN"] = add_outcome(plan.read_bytes(), line)
            gathered = archive.gather(folder, ("EXECUTION", "REPORT", "ARTIFACTS"))
            if _notes_to_archive(folder):
                gathered["NOTES"] = folder / "NOTES.md"
            sources.update({p: gathered[p] for p in archive.PREFIXES if p in gathered})
            archive_id, copied = "", []
            if sources.keys() & {"PLAN", "EXECUTION", "REPORT"}:
                if stale_id and (r.archive_dir / f"PLAN_{stale_id}.md").is_file():
                    archive_id = stale_id
                    copied = [str(r.archive_dir / f"{p}_{stale_id}.md") for p in sources
                              if (r.archive_dir / f"{p}_{stale_id}.md").is_file()]
                else:
                    archive_id, copied = archive.copy_to_archive(
                        folder, r, f"{now:%Y-%m-%d-%H%M}-{slug}", sources)
                release = False   # from here a crash leaves the claim, and the ID in it
                _write_text(claim, archive_id + "\n")
                archive.mark_effort(r, archive_id, slug)
        except (OSError, ValueError) as e:
            if not release:
                release = True
            raise EffortError(f"archive failed, {slug!r} left open: {e}")
        write(root, slug, {**meta, "status": status, "reason": reason or "", "archive_id": archive_id})
        release = True
        try:
            if plan.is_file():
                data = plan.read_bytes()
                new = add_outcome(data, line)
                if new != data:
                    _write_bytes(plan, new)
        except OSError:
            pass
    finally:
        if release:
            try:
                claim.unlink()
            except OSError:
                pass
    sweep_closed(root)
    shown = folder
    if not folder.exists() and archive_id:
        shown = paths.closed_dir(root) / archive_id
    return {"slug": slug, "status": status, "session_id": archive_id, "project": r.project,
            "store": r.store, "archive_dir": str(r.archive_dir), "copied": copied,
            "missing": [p for p in ("PLAN", "EXECUTION") if p not in sources],
            "notes_path": str(r.archive_dir / f"NOTES_{archive_id}.md") if archive_id else "",
            "folder": str(shown)}


# ---- command line ----------------------------------------------------------

def _rel(path) -> str:
    try:
        return Path(os.path.relpath(path)).as_posix()
    except ValueError:   # another drive on Windows
        return Path(path).as_posix()


def _session(args) -> str | None:
    sid = getattr(args, "session", None) or os.environ.get("CLAUDE_CODE_SESSION_ID") or None
    return sid if _usable(sid) else None   # an ID that sanitizes to nothing binds nothing


def _root() -> Path | None:
    cwd = Path.cwd()
    return paths.work_root(cwd)


def _open_slugs(root) -> str:
    slugs = [e["slug"] for e in sorted(open_efforts(root) + parked_efforts(root), key=lambda e: e["slug"])]
    return f" (open: {', '.join(slugs)})" if slugs else " (no open efforts)"


def _need(root, slug: str) -> dict:
    meta = read(root, slug) if root and paths.valid_slug(slug) else None
    if meta is None:
        raise EffortError(f"no effort {slug!r}{_open_slugs(root) if root else ''}")
    if meta.get("status") not in paths.EFFORT_OPEN:
        raise EffortError(f"effort {slug!r} is closed ({meta.get('status')}); "
                          f"start new work with `synapse effort start <slug>`")
    return meta


def _template(name: str, title: str, today: str) -> str:
    try:
        text = (PLUGIN_ROOT / "templates" / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError:
        text = f"# {name[:-3]}\n"
    first, _, rest = text.partition("\n")
    stem = name[:-3]
    if re.match(rf"#\s+{stem}\b", first):
        first = f"# {stem} — {title}" + (f" ({today})" if stem == "EXECUTION" else "")
        return first + "\n" + rest
    return text


def cmd_list(args) -> int:
    root = _root()
    if root is None:
        if args.json:
            print("[]")
            return 0
        print("No effort folders in this project. Start one with "
              "`synapse effort start <slug> --title \"...\"`.")
        return 0
    now = time.time()
    if args.json:
        entries = all_efforts(root) if args.all else open_efforts(root) + parked_efforts(root)
        print(json.dumps([{
            "slug": e["slug"], "title": e.get("title", ""), "status": e.get("status"),
            "waiting_on": e.get("waiting_on", ""), "reason": e.get("reason", ""),
            "archive_id": e.get("archive_id", ""),
            "folder": _rel(e.get("closed_folder") or paths.effort_dir(root, e["slug"])),
            "touched": e["touched"]} for e in entries], indent=2))
        return 0
    lines = []
    text = index_text(root, _session(args), full=True)
    if text:
        lines.append(text)
    elif not args.all:
        lines.append("No open efforts. Start one with `synapse effort start <slug> --title \"...\"`.")
    if args.all:
        for e in sorted(parked_efforts(root), key=lambda e: e["touched"], reverse=True):
            why = f": {_clip(e['reason'])}" if e.get("reason") else ""
            lines.append(f"- {e['slug']} [parked] {_clip(e.get('title'))} ({_age(now - e['touched'])}){why}")
        for e in sorted((x for x in all_efforts(root) if x.get("status") in paths.EFFORT_CLOSED),
                        key=lambda e: e["touched"], reverse=True):
            arch = f"archive {e['archive_id']}" if e.get("archive_id") else "no archive"
            lines.append(f"- {e['slug']} [{e['status']}] {_clip(e.get('title'))} ({arch})")
    print("\n".join(lines))
    return 0


def _bound_lines(session, root, slug, folder) -> None:
    print(f"folder: {_rel(folder)}")
    if session:
        bind(session, root, slug)
        print("bound: this session")
    else:
        print("bound: no session ID in this shell; pass --effort <slug> to "
              "`synapse checkpoint --stamp` and `synapse archive`")


def cmd_start(args) -> int:
    slug = args.slug
    if not paths.valid_slug(slug):
        raise EffortError(f"invalid slug {slug!r}: use 1-40 lower-case letters, digits and dashes "
                          "(no leading or trailing dash, no names like con or v2)")
    root = _root()
    if root is None:
        git = paths.find_upwards(Path.cwd(), ".git")
        root = git.parent if git else Path.cwd()
    sweep_closed(root)
    folder = paths.effort_dir(root, slug)
    if folder.exists():
        meta = read(root, slug)
        if meta and meta.get("status") in paths.EFFORT_CLOSED:
            sweep_closed(root, force_slug=slug)
            if folder.exists():
                raise EffortError(f"a closed effort still holds {_rel(folder)}/ (a file in it may be "
                                  "open); close the file or pick another slug")
        elif meta is None:
            raise EffortError(f"{_rel(folder)}/ exists but has no readable effort.json; "
                              "pick another slug or restore effort.json")
        else:
            raise EffortError(f"effort {slug!r} exists; `synapse effort resume {slug}`")
    title = " ".join((args.title or slug).split())
    today = f"{datetime.now():%Y-%m-%d}"
    folder.mkdir(parents=True)
    stamp = _iso(_now())
    write(root, slug, {"title": title, "status": "active", "waiting_on": "", "reason": "",
                       "archive_id": "", "created": stamp})
    for name in ("PLAN.md", "EXECUTION.md"):
        _write_text(folder / name, _template(name, title, today))
    print(f"Synapse effort started: {slug}")
    _bound_lines(_session(args), root, slug, folder)
    return 0


def cmd_resume(args) -> int:
    root = _root()
    meta = _need(root, args.slug)
    session = _session(args)
    other = others_on(root, args.slug, session)
    write(root, args.slug, {**meta, "status": "active", "waiting_on": "", "reason": ""})
    print(f"Synapse effort resumed: {args.slug}")
    _bound_lines(session, root, args.slug, paths.effort_dir(root, args.slug))
    if other is not None:
        print(f"note: another session was active on this effort {_age(other)}; "
              "two sessions on one effort can overwrite each other's edits")
    return 0


def _update(args, verb: str, **changes) -> int:
    root = _root()
    meta = _need(root, args.slug)
    write(root, args.slug, {**meta, **changes})
    print(f"Synapse effort {verb}: {args.slug}")
    return 0


def cmd_wait(args) -> int:
    return _update(args, "waiting", status="waiting", waiting_on=" ".join(args.on.split()))


def cmd_park(args) -> int:
    return _update(args, "parked", status="parked", reason=" ".join((args.reason or "").split()))


def _drop_own_binding(session, root, slug) -> None:
    """The closing session needs no "your effort was closed" notice for its own close."""
    try:
        f = paths.effort_state(session) if session else None
        state = _json(f) if f else None
        if state and state.get("slug") == slug and paths.same_path(state.get("root", ""), root):
            f.unlink()
    except Exception:
        pass


def cmd_close(args) -> int:
    status = "done" if args.verb == "done" else "cancelled"
    if status == "cancelled" and not " ".join((args.reason or "").split()):
        raise EffortError("cancel needs a reason: --reason \"...\"")
    root = _root()
    _need(root, args.slug)
    out = close(root, args.slug, status, args.reason or "")
    _drop_own_binding(_session(args), root, args.slug)
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"Synapse effort {status}: {args.slug}")
    if out["session_id"]:
        print(f"archive: {out['session_id']}")
    print(f"folder: {_rel(out['folder'])}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="synapse effort", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="verb", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name, **kw)
        sp.set_defaults(fn=fn)
        return sp

    sp = add("list", cmd_list, help="open efforts; --all adds parked and closed")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--session", default=None, help="session ID (default: CLAUDE_CODE_SESSION_ID)")
    sp = add("start", cmd_start, help="create an effort folder and bind this session")
    sp.add_argument("slug")
    sp.add_argument("--title", default=None)
    sp.add_argument("--session", default=None, help="session ID (default: CLAUDE_CODE_SESSION_ID)")
    sp = add("resume", cmd_resume, help="make an open effort active and bind this session")
    sp.add_argument("slug")
    sp.add_argument("--session", default=None, help="session ID (default: CLAUDE_CODE_SESSION_ID)")
    sp = add("wait", cmd_wait, help="record what an effort waits on")
    sp.add_argument("slug")
    sp.add_argument("--on", required=True)
    sp = add("park", cmd_park, help="set an effort aside")
    sp.add_argument("slug")
    sp.add_argument("--reason", default=None)
    for verb, need in (("done", False), ("cancel", True)):
        sp = add(verb, cmd_close, help=f"archive and close an effort as {'done' if verb == 'done' else 'cancelled'}")
        sp.set_defaults(verb=verb)
        sp.add_argument("slug")
        sp.add_argument("--reason", required=need, default=None)
        sp.add_argument("--json", action="store_true")
    add("migrate", None, help="split .claude-work/current into efforts")
    return p


def migrate(rest: list[str]) -> int:
    import effort_migrate
    return effort_migrate.main(rest)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["migrate"]:
        return migrate(argv[1:])
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except EffortError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
