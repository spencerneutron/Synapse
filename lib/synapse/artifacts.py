#!/usr/bin/env python3
"""
artifacts.py — which Artifact pages a session published (stdlib only, no I/O but ARTIFACTS.md).

Called from the Stop gate (gate.capture_artifacts); it never prints.
  from_turn(entries)           [(url, title)] for the Artifacts this turn published, oldest first
  from_message(text, entries)  Artifact URLs in the final message that the tool results missed
  record(work_dir, items)      merge [(url, title or None)] into ARTIFACTS.md, one line per URL
                               within the current segment (after the last archive marker)
  segment_text(text)           the link lines after the last `<!-- archived: id -->` marker
  merge_text(old, new)         link lines of old then new, one per URL, newer title wins
  mark_archived(work_dir, id)  append the marker line (the file stays)

entries are what continuation.scan collects: assistant entries with an Artifact
tool_use, and user entries with tool_result blocks. ARTIFACTS.md holds only
lines of the form `- [title](url)`.
"""

import os
import re
from pathlib import Path

URL_RE = re.compile(r"https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+")
PUBLISHED_RE = re.compile(r"Published\b.*?\bat\s+(https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+)",
                          re.S)
LINE_RE = re.compile(r"^- \[(.*)\]\((https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+)\)$")
MARKER_RE = re.compile(r"^<!-- archived: .* -->$")
TITLE_CAP = 200
FILE = "ARTIFACTS.md"


def _segment_start(lines) -> int:
    """Index of the first line after the last archive marker (0 when none)."""
    for i in range(len(lines) - 1, -1, -1):
        if MARKER_RE.match(lines[i].strip()):
            return i + 1
    return 0


def _link_lines(lines):
    return [ln.strip() for ln in lines if LINE_RE.match(ln.strip())]


def segment_text(text: str) -> str:
    """The valid link lines after the last archive marker, newline-terminated;
    "" when the current segment has none."""
    lines = text.split("\n")
    out = _link_lines(lines[_segment_start(lines):])
    return "\n".join(out) + "\n" if out else ""


def merge_text(old: str, new: str) -> str:
    """The link lines of old then new, one per URL: order of first appearance,
    the newer title winning."""
    found = {}
    for ln in _link_lines(old.split("\n")) + _link_lines(new.split("\n")):
        m = LINE_RE.match(ln)
        found[m.group(2)] = m.group(1)
    return "".join(f"- [{t}]({u})\n" for u, t in found.items())


def _write_atomic(f: Path, text: str) -> None:
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, f)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def mark_archived(work_dir, session_id) -> None:
    """Append `<!-- archived: id -->` to work_dir/ARTIFACTS.md (atomic; no-op when
    the file is missing). Later records start a new segment after it."""
    f = Path(work_dir) / FILE
    if not f.is_file():
        return
    text = f.read_text("utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    _write_atomic(f, text + f"<!-- archived: {session_id} -->\n")


def _blocks(entry):
    msg = entry.get("message") if isinstance(entry, dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _text(block) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict)
                         and isinstance(x.get("text"), str))
    return ""


def _is_publish(inp) -> bool:
    return isinstance(inp, dict) and not inp.get("asset") \
        and inp.get("action") in (None, "publish")


def _facts(entries):
    """(items, ids, types): the publishes of the turn as (url, title); the artifact_ids
    its results carried; the template URLs it only looked at (type_url, quickstart)."""
    uses = {}
    for e in entries or []:
        if isinstance(e, dict) and e.get("type") == "assistant":
            for b in _blocks(e):
                if b.get("type") == "tool_use" and b.get("name") == "Artifact" \
                        and isinstance(b.get("id"), str) and isinstance(b.get("input"), dict):
                    uses[b["id"]] = b["input"]
    items, ids, types = [], set(), set()
    for e in entries or []:
        if not isinstance(e, dict) or e.get("type") != "user":
            continue
        tur = e.get("toolUseResult")
        tur = tur if isinstance(tur, dict) else {}
        for b in _blocks(e):
            inp = uses.get(b.get("tool_use_id"))
            if b.get("type") != "tool_result" or inp is None:
                continue
            text = _text(b)
            if isinstance(inp.get("type_url"), str):
                types.update(URL_RE.findall(inp["type_url"]))
            if inp.get("action") == "quickstart":
                types.update(URL_RE.findall(text))
                continue
            if inp.get("action") in ("read", "open"):
                # looked at, not published: a final message repeating it is no publish
                if isinstance(inp.get("url"), str):
                    types.update(URL_RE.findall(inp["url"]))
                aid = tur.get("artifact_id")
                if isinstance(aid, str) and aid:
                    ids.add(aid)
                continue
            if b.get("is_error") or not _is_publish(inp):
                continue
            aid = tur.get("artifact_id")
            if isinstance(aid, str) and aid:
                ids.add(aid)
            url = None
            for cand in (tur.get("url"), inp.get("url")):
                m = URL_RE.fullmatch(cand) if isinstance(cand, str) else None
                if m:
                    url = m.group(0)
                    break
            if url is None:
                m = PUBLISHED_RE.search(text)
                url = m.group(1) if m else None
            if url is None:
                continue
            title = None
            for cand in (inp.get("title"), tur.get("title")):
                if isinstance(cand, str) and cand.strip():
                    title = cand
                    break
            if title is None and isinstance(inp.get("file_path"), str):
                title = _Weak(re.split(r"[\\/]", inp["file_path"].rstrip("\\/"))[-1]) or None
            items.append((url, title))
    return items, ids, types


class _Weak(str):
    """A title taken from the file name: names a new line, never renames a known one."""


def from_turn(entries):
    """[(url, title or None)] for the successful publishes in the turn, oldest first."""
    return _facts(entries)[0]


def from_message(text, entries=()):
    """Artifact URLs in the final message, in order, without repeats. Left out: a
    code/artifact/<uuid> link to an artifact this turn published (same artifact_id),
    and a URL the turn only met as a template (type_url, quickstart result) or only
    read or opened (unless it also published that URL)."""
    if not isinstance(text, str) or not text:
        return []
    items, ids, types = _facts(entries)
    published = {u for u, _ in items}
    out = []
    for u in URL_RE.findall(text):
        if u in out:
            continue
        if u not in published:
            if u in types or u.rsplit("/", 1)[-1] in ids:
                continue
        out.append(u)
    return out


def _clean(title) -> str:
    t = re.sub(r"\s+", " ", str(title or "")).replace("[", "(").replace("]", ")").strip()
    return t[:TITLE_CAP].strip()


def record(work_dir, items) -> bool:
    """Merge items into the current segment of work_dir/ARTIFACTS.md (the lines after
    the last archive marker; a URL known only from an archived segment is new); True
    when the file changed. A new URL adds a line; a known URL with a real title (not a
    file name) updates that line's title; an item without a title (a link only the
    final message names) keeps the existing one, else shows the URL's last segment,
    and is skipped when the link is already archived. Nothing is created when items
    is empty."""
    items = [(u, t) for u, t in items or [] if isinstance(u, str) and URL_RE.fullmatch(u)]
    if not items:
        return False
    f = Path(work_dir) / FILE
    try:
        old = f.read_text("utf-8").splitlines() if f.is_file() else []
    except OSError:
        return False
    lines, where = list(old), {}
    start = _segment_start(lines)
    archived = {m.group(2) for ln in lines[:start] if (m := LINE_RE.match(ln))}
    for i in range(start, len(lines)):
        m = LINE_RE.match(lines[i])
        if m:
            where[m.group(2)] = i
    for url, title in items:
        t = _clean(title)
        if title is None and url in archived and url not in where:
            continue   # a message only mentions an archived link (end-session's summary)
        if url in where:
            if t and not isinstance(title, _Weak):
                lines[where[url]] = f"- [{t}]({url})"
        else:
            where[url] = len(lines)
            lines.append(f"- [{t or url.rsplit('/', 1)[-1]}]({url})")
    if lines == old:
        return False
    _write_atomic(f, "\n".join(lines) + "\n")
    return True
