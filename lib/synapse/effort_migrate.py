#!/usr/bin/env python3
"""
effort_migrate.py — split .claude-work/current/ into effort folders.

  synapse effort migrate                      propose a split as JSON (read-only)
  synapse effort migrate --apply FILE         snapshot current/, then write the (edited) proposal
  synapse effort migrate --retire-current     move current/'s planning files to efforts/_closed/<snapshot id>/
  synapse effort migrate --apply FILE --retire-current
  synapse effort migrate [--apply FILE] --again   split again although current/ was already split

A successful apply writes efforts/.split.json (snapshot ID and the hashes of the files
split); while current/ still matches it, propose and apply refuse unless given --again.

The proposal lists line ranges of PLAN.md and EXECUTION.md per effort; every line
lands in exactly one effort or in the closed `history` effort. Apply copies the
ranges verbatim, never edits or deletes current/, and removes only the folders it
created if it fails. Retiring renames files one by one (os.rename); a file that
cannot be moved is left and named. Stdlib only.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive  # noqa: E402
import effort  # noqa: E402
import paths  # noqa: E402

EffortError = effort.EffortError
VERSION = 1
STANDARD = ("purpose", "constraints", "session hooks", "decision log", "backlog", "progress", "outcome")
CONTAINERS = ("strategy", "phases", "roadmap", "workstreams")
FILES = ("PLAN.md", "EXECUTION.md")
RETIRE = ("PLAN.md", "EXECUTION.md", "NOTES.md", "REPORT.md", "ARTIFACTS.md")
HISTORY_TITLE = "Finished work before the split"
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEAD = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
BULLET = re.compile(r"^[-*+][ \t]+(?:\[[ xX]\][ \t]+)?\*\*(.+?)\*\*")
CHECK = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[([ xX])\]")
LISTITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(.*\S)")
DONE = re.compile(r"✅|\[[xX]\]|(?i:\(done\)|\bcomplete[d]?\b|\bshipped\b|\bcancell?ed\b)|\bDONE\b")
PHASE = re.compile(r"\bPhase[ \t]+([A-Za-z0-9]+)", re.I)
TITLE = re.compile(r"^(Phase[ \t]+[A-Za-z0-9]+)[ \t]*[—–:.\-]+[ \t]*(.+)$", re.I)


# ---- reading ---------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(raw: bytes) -> list[str]:
    return [l.decode("utf-8", errors="replace").rstrip("\r\n") for l in raw.splitlines(keepends=True)]


def _clean(text: str) -> str:
    text = re.sub(r"✅|\[[xX]\]|\((?:done|cancell?ed)\)|\*\*|__|`", "", text, flags=re.I)
    return " ".join(text.split()).strip(" .:-—–")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")


def _unique(base: str, taken) -> str:
    """base, or base-2, base-3 ... that is a valid slug and not in `taken` (a set or predicate)."""
    is_taken = taken if callable(taken) else taken.__contains__
    base = base if paths.valid_slug(base) else (_slugify(f"{base}-effort") or "effort")
    cand, n = base, 2
    while not paths.valid_slug(cand) or is_taken(cand):
        suffix = f"-{n}"
        cand, n = base[:40 - len(suffix)].rstrip("-") + suffix, n + 1
    return cand


def _ranges(numbers) -> list[list[int]]:
    out = []
    for n in sorted(numbers):
        if out and out[-1][1] == n - 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


# ---- the proposal ----------------------------------------------------------

def parse_plan(lines: list[str]) -> tuple[list[dict], list[dict]]:
    """(units, fact candidates). A unit: start, end (0-based, end exclusive), name, finished."""
    code, fence = [], None
    for line in lines:
        m = FENCE.match(line)
        if fence:
            code.append(True)
            if m and set(line.strip()) == {fence[0]} and len(line.strip()) >= len(fence):
                fence = None
        elif m:
            fence = m.group(1)
            code.append(True)
        else:
            code.append(False)

    starts, sect, facts, progress = [], None, [], []
    for i, line in enumerate(lines):
        if code[i]:
            continue
        m = HEAD.match(line)
        if m and len(m.group(1)) <= 2:
            name = m.group(2)
            low = _clean(name).lower()
            if len(m.group(1)) == 1:
                sect = None
                starts.append({"at": i, "label": None})
            elif low.startswith(STANDARD):
                sect = ("progress" if low.startswith("progress")
                        else "constraints" if low.startswith("constraints") else "std")
                starts.append({"at": i, "label": None})
            elif low.startswith(CONTAINERS):
                sect = "container"
                starts.append({"at": i, "label": None})
            else:
                sect = "other"
                starts.append({"at": i, "label": name, "first": line})
        elif m and len(m.group(1)) == 3 and sect == "container":
            starts.append({"at": i, "label": m.group(2), "first": line})
        elif sect == "container" and BULLET.match(line):
            starts.append({"at": i, "label": BULLET.match(line).group(1), "first": line})
        elif sect == "progress":
            c = CHECK.match(line)
            if c and c.group(1) in "xX":
                progress.append(line)
        elif sect == "constraints":
            li = LISTITEM.match(line)
            if li:
                facts.append({"line": i + 1, "text": li.group(1)})

    units = []
    for k, s in enumerate(starts):
        if s["label"] is None:
            continue
        end = starts[k + 1]["at"] if k + 1 < len(starts) else len(lines)
        label, first = s["label"], s["first"]
        body = [lines[j] for j in range(s["at"], end) if not code[j]]
        boxes = [CHECK.match(l).group(1) for l in body if CHECK.match(l)]
        finished = bool(DONE.search(label) or re.search(r"✅|\[[xX]\]", first)
                        or (boxes and all(b in "xX" for b in boxes)))
        ph = PHASE.search(label)
        if ph and not finished:
            ref = re.compile(rf"\bPhase[ \t]+{re.escape(ph.group(1))}(?![A-Za-z0-9])", re.I)
            finished = any(ref.search(l) for l in progress)
        units.append({"start": s["at"], "end": end, "name": _clean(label), "finished": finished})
    return units, facts


def _marker(root) -> dict | None:
    """The split marker when it is readable and every recorded hash still equals the
    file on disk; None when absent, unreadable or current/ changed since the split."""
    try:
        m = json.loads(paths.split_marker(root).read_text(encoding="utf-8-sig"))
        sid, srcs = m["snapshot_id"], m["sources"]
        if not isinstance(sid, str) or not sid or not isinstance(srcs, dict) or not srcs:
            return None
        cur = paths.work_dir(root)
        for name, want in srcs.items():
            raw = _read(cur / name)
            if name not in FILES or raw is None or _sha(raw) != want:
                return None
        return {"snapshot_id": sid}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _refuse_if_split(root, again: bool) -> None:
    m = None if again else _marker(root)
    if m:
        raise EffortError(f".claude-work/current/ was already split into efforts (snapshot {m['snapshot_id']}) "
                          "and has not changed since. Move it away with `synapse effort migrate "
                          "--retire-current`, or pass --again to split it once more.")


def propose(root, again: bool = False) -> dict:
    _refuse_if_split(root, again)
    cur = paths.work_dir(root)
    plan_raw = _read(cur / "PLAN.md")
    if plan_raw is None:
        raise EffortError("no .claude-work/current/PLAN.md to split")
    exec_raw = _read(cur / "EXECUTION.md")
    plan_lines = plan_raw.splitlines(keepends=True)
    units, facts = parse_plan(_text(plan_raw))
    source = {"PLAN.md": {"sha256": _sha(plan_raw), "lines": len(plan_lines)}}
    exec_n = 0
    if exec_raw is not None:
        exec_n = len(exec_raw.splitlines(keepends=True))
        source["EXECUTION.md"] = {"sha256": _sha(exec_raw), "lines": exec_n}

    used, efforts, taken = set(), [], set()
    free = lambda s: s in used or paths.effort_dir(root, s).exists()  # noqa: E731
    for u in units:
        if u["finished"]:
            continue
        slug = _unique(_slugify(u["name"]), free)
        used.add(slug)
        t = TITLE.match(u["name"])
        title = (t.group(2) if t else u["name"]).strip(" .:-—–") or slug
        efforts.append({"slug": slug, "title": title, "status": "active", "waiting_on": "",
                        "plan": [[u["start"] + 1, u["end"]]], "execution": []})
        taken.update(range(u["start"] + 1, u["end"] + 1))
    hist = _unique("history", free)
    history = {"slug": hist, "title": HISTORY_TITLE,
               "plan": _ranges(set(range(1, len(plan_lines) + 1)) - taken),
               "execution": [[1, exec_n]] if exec_n else []}
    covered = sum(b - a + 1 for e in efforts for a, b in e["plan"]) + sum(b - a + 1 for a, b in history["plan"])
    if covered != len(plan_lines):
        raise EffortError("internal error: the proposal does not cover every line of PLAN.md once")
    notes = [f"{len(efforts)} open unit(s) became efforts; {len(units) - len(efforts)} finished unit(s) "
             "and the standard sections are listed under history."]
    if not efforts:
        notes.append("No open unit was found; edit the proposal to name the efforts, or start one with "
                     "`synapse effort start`.")
    if exec_n:
        notes.append("EXECUTION.md is not split: all of it is listed under history. Assign its parts "
                     "(its `## Resume` among them) to the effort they belong to by moving their line "
                     "ranges into that effort's `execution` list.")
    return {"version": VERSION, "source": source, "efforts": efforts, "history": history,
            "fact_candidates": facts, "notes": notes}


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


# ---- apply -----------------------------------------------------------------

def _ranges_of(entry, key, total, where):
    out = []
    val = entry.get(key) or []
    if not isinstance(val, list):
        raise EffortError(f"{where}: {key} must be a list of [first, last] line ranges")
    for r in val:
        if (not isinstance(r, (list, tuple)) or len(r) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) for x in r)
                or not 1 <= r[0] <= r[1] <= total):
            raise EffortError(f"{where}: bad {key} range {r!r} (lines 1-{total})")
        out.append((r[0], r[1]))
    return out


def validate(root, prop) -> dict:
    """The proposal checked against the files now on disk; the normalized plan, or EffortError."""
    if not isinstance(prop, dict) or prop.get("version") != VERSION:
        raise EffortError(f"not a version {VERSION} proposal")
    cur = paths.work_dir(root)
    src = prop.get("source")
    if not isinstance(src, dict) or "PLAN.md" not in src:
        raise EffortError("the proposal has no source hash for PLAN.md")
    raws, totals = {}, {}
    for name in FILES:
        raw = _read(cur / name)
        want = src.get(name)
        have = _sha(raw) if raw is not None else None
        if name in src and not (isinstance(want, dict) and isinstance(want.get("sha256"), str)):
            raise EffortError(f"source {name}: needs an object with a sha256 string")
        wanted = want["sha256"] if name in src else None
        if wanted != have:
            raise EffortError(f"{name} changed since the proposal; run `synapse effort migrate` again")
        raws[name] = raw
        totals[name] = len(raw.splitlines(keepends=True)) if raw is not None else 0
    efforts = prop.get("efforts")
    history = prop.get("history")
    if not isinstance(efforts, list) or not isinstance(history, dict):
        raise EffortError("the proposal needs an efforts list and a history object")
    seen, plan_used, exec_used, out = set(), set(), set(), []
    for e in efforts + [history]:
        is_hist = e is history
        where = f"history" if is_hist else f"effort {e.get('slug')!r}" if isinstance(e, dict) else "an effort"
        if not isinstance(e, dict):
            raise EffortError(f"{where}: not an object")
        slug = e.get("slug")
        if not paths.valid_slug(slug):
            raise EffortError(f"{where}: invalid slug {slug!r} (1-40 lower-case letters, digits and dashes)")
        if slug in seen:
            raise EffortError(f"slug {slug!r} is used twice")
        seen.add(slug)
        if paths.effort_dir(root, slug).exists():
            raise EffortError(f"a folder for {slug!r} exists in .claude-work/efforts/; pick another slug")
        status = "done" if is_hist else e.get("status")
        if not is_hist and not (isinstance(status, str) and status in paths.EFFORT_OPEN):
            raise EffortError(f"{where}: status must be active, waiting or parked, not {status!r}")
        waiting = " ".join(str(e.get("waiting_on") or "").split())
        if status == "waiting" and not waiting:
            raise EffortError(f"{where}: a waiting effort needs waiting_on")
        for field in ("title", "waiting_on"):
            v = e.get(field)
            if v is not None and not isinstance(v, str):
                raise EffortError(f"{where}: {field} must be text")
            try:
                (v or "").encode("utf-8")
            except UnicodeEncodeError:
                raise EffortError(f"{where}: {field} holds characters that cannot be written as UTF-8")
        item = {"slug": slug, "title": " ".join(str(e.get("title") or slug).split()), "status": status,
                "waiting_on": waiting if status == "waiting" else "", "hist": is_hist}
        for key, name, used in (("plan", "PLAN.md", plan_used), ("execution", "EXECUTION.md", exec_used)):
            rs = _ranges_of(e, key, totals[name], where)
            for a, b in rs:
                span = set(range(a, b + 1))
                if span & used:
                    raise EffortError(f"{where}: {name} lines {a}-{b} overlap another effort's ranges")
                used |= span
            item[key] = rs
        out.append(item)
    for key, name, used in (("plan", "PLAN.md", plan_used), ("execution", "EXECUTION.md", exec_used)):
        rest = _ranges(set(range(1, totals[name] + 1)) - used)
        out[-1][key] = sorted(out[-1][key] + [tuple(r) for r in rest])
    return {"efforts": out, "raw": raws}


def _chunks(lines: list[bytes], ranges, eol: bytes) -> bytes:
    parts = []
    for a, b in ranges:
        seg = b"".join(lines[a - 1:b])
        if seg and not seg.endswith((b"\n", b"\r")):
            seg += eol
        parts.append(seg)
    return b"".join(parts)


def _snapshot(root, r, now) -> str:
    """Copy current/'s files to the archive as <date>-pre-split. ARTIFACTS is copied whole
    and not marked archived (that would write to current/), so a later ordinary archive of
    current/ may repeat those artifact links once."""
    cur = paths.work_dir(root)
    sources = {p: cur / f"{p}.md" for p in archive.PREFIXES
               if p != "ARTIFACTS" and (cur / f"{p}.md").is_file()}
    try:
        sid, _ = archive.copy_to_archive(cur, r, f"{now:%Y-%m-%d-%H%M}-pre-split", sources)
        if (cur / "ARTIFACTS.md").is_file():
            archive.put(r.archive_dir / f"ARTIFACTS_{sid}.md", cur / "ARTIFACTS.md")
    except (OSError, ValueError) as e:
        raise EffortError(f"snapshot failed, nothing else written: {e}")
    return sid


def _write_marker(root, sid, raws, now) -> None:
    sources = {n: _sha(raws[n]) for n in FILES if raws[n] is not None}
    data = json.dumps({"snapshot_id": sid, "sources": sources, "time": effort._iso(now)}, indent=2) + "\n"
    effort._write_bytes(paths.split_marker(root), data.encode("utf-8"))


def apply(root, prop, now, again: bool = False) -> dict:
    _refuse_if_split(root, again)
    plan = validate(root, prop)
    cur = paths.work_dir(root)
    r = paths.resolve(cwd=root)
    sid = _snapshot(root, r, now)
    raws = plan["raw"]
    lines = {n: (raws[n] or b"").splitlines(keepends=True) for n in FILES}
    eol = b"\r\n" if b"\r\n" in raws["PLAN.md"] else b"\n"
    enc = lambda s: s.replace("\n", eol.decode()).encode("utf-8")  # noqa: E731
    today, stamp = f"{now:%Y-%m-%d}", effort._iso(now)
    created = []
    made_efforts = not paths.efforts_dir(root).exists()
    try:
        for e in plan["efforts"]:
            slug, title = e["slug"], e["title"]
            # exclusive create: a folder another session started since validate is an error,
            # and is not ours to remove.
            paths.effort_dir(root, slug).mkdir(parents=True, exist_ok=False)
            created.append(slug)
            if e["hist"]:
                meta = {"title": title, "status": "done", "waiting_on": "", "archive_id": sid,
                        "reason": "finished before the split", "created": stamp}
            else:
                meta = {"title": title, "status": e["status"], "waiting_on": e["waiting_on"],
                        "reason": "", "archive_id": "", "created": stamp}
            effort.write(root, slug, meta)
            folder = paths.effort_dir(root, slug)
            head = enc(f"# PLAN — {title}\n<!-- Split from .claude-work/current/PLAN.md on {today}; "
                       f"snapshot {sid}. -->\n\n")
            effort._write_bytes(folder / "PLAN.md", head + _chunks(lines["PLAN.md"], e["plan"], eol))
            if e["execution"]:
                head = enc(f"# EXECUTION — {title} ({today})\n\n")
                body = head + _chunks(lines["EXECUTION.md"], e["execution"], eol)
            else:
                body = enc(effort._template("EXECUTION.md", title, today))
            effort._write_bytes(folder / "EXECUTION.md", body)
            if e["hist"] and (cur / "NOTES.md").is_file():
                effort._write_bytes(folder / "NOTES.md", (cur / "NOTES.md").read_bytes())
        _write_marker(root, sid, raws, now)   # last, so a rollback never leaves one
    except Exception as ex:
        for slug in created:
            shutil.rmtree(paths.effort_dir(root, slug), ignore_errors=True)
        try:
            paths.split_marker(root).unlink()
        except OSError:
            pass
        if made_efforts:   # an empty efforts/ would switch the project's layout
            try:
                os.rmdir(paths.efforts_dir(root))
            except OSError:
                pass
        raise EffortError(f"apply failed, the folders it created were removed (snapshot {sid} stays): {ex}")
    hist = next(e["slug"] for e in plan["efforts"] if e["hist"])
    return {"snapshot_id": sid, "created": [s for s in created if s != hist], "history": hist,
            "retired": False, "current": effort._rel(cur)}


# ---- retire ----------------------------------------------------------------

def _pre_split_id(root, r) -> str | None:
    """The newest archived -pre-split session whose files equal current/ now, else None."""
    cur = paths.work_dir(root)
    now_files = {p: cur / f"{p}.md" for p in archive.PREFIXES if (cur / f"{p}.md").is_file()}
    snaps = [s for s in archive.discover_sessions(r.archive_dir) if re.search(r"-pre-split(?:-v\d+)?$", s["id"])]
    if snaps and archive.content_hash(snaps[-1]["files"]) == archive.content_hash(now_files):
        return snaps[-1]["id"]
    return None


def retire(root, sid, result: dict) -> dict:
    cur, closed = paths.work_dir(root), paths.closed_dir(root)
    target, n = closed / sid, 1
    while target.exists():
        target = closed / (f"{sid}-current" + (f"-{n}" if n > 1 else ""))
        n += 1
    moved, left = [], []
    for name in RETIRE:
        if not (cur / name).is_file():
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
            os.rename(cur / name, target / name)
            moved.append(name)
        except OSError:
            left.append(name)
    if not left:
        try:
            paths.split_marker(root).unlink()
        except OSError:
            pass
    return {**result, "snapshot_id": sid, "retired": True, "moved": moved, "left": left,
            "folder": effort._rel(target), "current": effort._rel(cur)}


def retire_alone(root, now) -> dict:
    if not paths.efforts_dir(root).is_dir():
        raise EffortError("this project has no efforts folder; run `synapse effort migrate` first")
    cur = paths.work_dir(root)
    if not any((cur / n).is_file() for n in RETIRE):
        raise EffortError("no planning files left in .claude-work/current/")
    r = paths.resolve(cwd=root)
    m = _marker(root)
    sid = (m and m["snapshot_id"]) or _pre_split_id(root, r) or _snapshot(root, r, now)
    return retire(root, sid, {})


# ---- command line ----------------------------------------------------------

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="synapse effort migrate",
        description="Split .claude-work/current into effort folders. With no flags: print a JSON "
                    "proposal (read-only) with line ranges per effort. Edit it, then --apply it.")
    p.add_argument("--apply", metavar="FILE", help="snapshot current/, then write the proposal in FILE")
    p.add_argument("--retire-current", action="store_true",
                   help="move current/'s planning files to efforts/_closed/<snapshot id>/")
    p.add_argument("--again", action="store_true",
                   help="split current/ even though it was already split and has not changed")
    args = p.parse_args(argv)
    try:
        root = paths.work_root(Path.cwd())
        if root is None:
            raise EffortError("no .claude-work folder here; nothing to split")
        now = effort._now()
        if args.apply:
            try:
                prop = json.loads(Path(args.apply).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as e:
                raise EffortError(f"cannot read the proposal {args.apply}: {e}")
            out = apply(root, prop, now, args.again)
            if args.retire_current:
                out = retire(root, out["snapshot_id"], out)
        elif args.retire_current:
            out = retire_alone(root, now)
        else:
            out = propose(root, args.again)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    except EffortError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
