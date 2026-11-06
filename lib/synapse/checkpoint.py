#!/usr/bin/env python3
"""
checkpoint.py — stamp the time inside EXECUTION.md's Resume section.

  synapse checkpoint --stamp   # write "Checkpoint written: YYYY-MM-DD HH:MM +HH:MM"

Used by /synapse:checkpoint. Finds the work folder (.claude-work/current) from
the current folder, then puts the stamp line right after the "## Resume"
heading in EXECUTION.md, replacing an earlier stamp inside that section only.
Every other byte is kept, line endings included. The write is atomic. If the
file or the heading is missing, it says so on stderr, exits 1, and writes
nothing. Stdlib only.
"""

import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HEADING = re.compile(rb"^(?:\xef\xbb\xbf)?##[ \t]+Resume\b", re.IGNORECASE)
H2 = re.compile(rb"^##[ \t]")
FENCE = re.compile(rb"^(?:\xef\xbb\xbf)?[ \t]{0,3}(```|~~~)")
STAMP = re.compile(rb"^Checkpoint written:")


def stamp_text(now: datetime | None = None) -> str:
    now = (now or datetime.now()).astimezone()
    off = now.strftime("%z")
    return f"{now.strftime('%Y-%m-%d %H:%M')} {off[:3]}:{off[3:]}"


def outside_fences(lines: list[bytes]) -> list[bool]:
    """True for each line that is not inside (or on the edge of) a fenced code block."""
    flags, fence = [], None
    for l in lines:
        m = FENCE.match(l)
        if fence is None:
            flags.append(m is None)
            if m:
                fence = m.group(1)
        else:
            flags.append(False)
            if m and m.group(1) == fence:
                fence = None
    return flags


def apply(data: bytes, stamp: str) -> bytes | None:
    """Return data with the stamp placed in the Resume section, or None without the heading."""
    lines = data.splitlines(keepends=True)
    plain = outside_fences(lines)
    start = next((i for i, l in enumerate(lines) if plain[i] and HEADING.match(l)), None)
    if start is None:
        return None
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if plain[i] and H2.match(lines[i]):
            end = i
            break
    if not lines[start].endswith((b"\n", b"\r")):
        lines[start] += eol
    body = [l for l in lines[start + 1:end] if not STAMP.match(l)]
    new = f"Checkpoint written: {stamp}".encode() + eol
    return b"".join(lines[:start + 1] + [new] + body + lines[end:])


def main(argv: list[str]) -> int:
    if "--stamp" not in argv:
        print(__doc__.strip())
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import paths
    cwd = Path.cwd()
    target = paths.find_work_dir(cwd) / "EXECUTION.md"
    link = target
    target = Path(os.path.realpath(target)) if target.is_symlink() else target
    try:
        data = target.read_bytes()
    except OSError:
        print(f"error: {target} is missing; create it first (plan-session)", file=sys.stderr)
        return 1
    stamp = stamp_text()
    out = apply(data, stamp)
    if out is None:
        print(f"error: no '## Resume' section in {target}", file=sys.stderr)
        return 1
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".EXECUTION-", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(out)
        try:
            os.chmod(tmp, target.stat().st_mode & 0o777)
        except OSError:
            pass
        os.replace(tmp, target)
    except OSError as e:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        print(f"error: could not write {link}: {e.strerror or e}", file=sys.stderr)
        return 1
    try:
        shown = link.relative_to(cwd)
    except ValueError:
        shown = link
    print(f"Checkpoint stamped: {stamp} in {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
