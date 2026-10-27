#!/usr/bin/env python3
"""
share.py — put an approved, scrubbed note into a team's shared folder.

  synapse share scrub <note> [--json] [--out FILE]   # fix and flag (scrub.py)
  synapse share lint <path>... [--json]              # fail unless safe to share
  synapse share add <team> <file> [--source NOTE] [--json]

`add` takes the version the user approved (the /synapse:share skill writes
it), refuses it unless `lint` is clean, keeps only Decision and Pattern
notes, replaces personal front matter (session links, related notes) with
provenance (origin, author, shared_at, source_id), writes it to the team's
Decisions/ or Patterns/, commits for a git team, and re-indexes. It never
pushes: that is `synapse shared push`, after the user's OK.
"""

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import scrub  # noqa: E402
import shared  # noqa: E402

FOLDER_FOR = {"decision": "Decisions", "pattern": "Patterns"}
# Personal links and ids that mean nothing to a teammate, plus provenance
# fields that only `add` may set.
DROP_KEYS = {"session_id", "related", "supersedes", "superseded_by",
             "origin", "author", "shared_at", "source_id"}
FM_CLOSE = re.compile(r"\n---[ \t]*(?=\n|$)")


def without_keys(text: str, drop: set) -> str:
    """Remove front-matter keys (and their indented or list lines)."""
    text = text.removeprefix("﻿")
    close = FM_CLOSE.search(text, 3) if text.startswith("---\n") else None
    if not close:
        return text
    keep, skipping = [], False
    for line in text[4:close.start()].split("\n"):
        if line and not line[0].isspace() and not line.startswith("-"):
            skipping = line.split(":", 1)[0].strip() in drop
        if not skipping:
            keep.append(line)
    return "---\n" + "\n".join(keep) + text[close.start():]


def note_name(text: str, source: Path | None) -> str:
    """The shared file's name: the source note's, else the note's own title.
    A name is shared too, so it must pass the scrub gate like the text."""
    import vault_write

    if source is not None:
        name = source.stem if source.suffix == ".md" else source.name
    else:
        m = shared.TITLE_RE.search(text)
        if not m:
            shared.die("the note has no '# Title' line; pass --source <original note>")
        name = m.group(1).strip()
    found = scrub.lint(name)      # before safe_name, which would strip the '#' of "#17"
    if found:
        shared.die(f"the file name {name!r} fails the scrub gate; rename the note "
                   f"({', '.join(sorted({f.kind for f in found}))})")
    return vault_write.safe_name(name)


def shared_copies(team: paths.Team) -> dict[str, Path]:
    """source_id -> file, for every note in the team folder."""
    import extract

    out = {}
    for f in shared.note_files(team.notes)[0]:
        sid = extract.parse_frontmatter(f.read_text(encoding="utf-8"))[0].get("source_id")
        if sid:
            out[sid] = f
    return out


def cmd_add(args) -> int:
    import extract
    import vault_write

    team = shared.get_team(args.team)
    if not team.notes.is_dir():
        shared.die(f"{team.notes} is missing; run `synapse shared sync {team.name}`")
    shared.require_checkout(team)
    text = without_keys(Path(args.file).read_text(encoding="utf-8"), DROP_KEYS)
    problems = scrub.lint(text)
    if problems:
        for f in problems:
            print(f"line {f.line}: {f.outcome} {f.kind}: {f.message} ({f.excerpt})", file=sys.stderr)
        shared.die(f"{len(problems)} finding(s): fix them (synapse share scrub) before sharing")
    kind = extract.parse_frontmatter(text)[0].get("type", "")
    if kind not in FOLDER_FOR:
        shared.die(f"only Decision and Pattern notes can be shared (type: {kind or 'none'})")

    source = Path(args.source or args.file)
    sid = paths.source_id(team.author, paths.to_stored_path(source, paths.resolve()))
    previous = shared_copies(team).get(sid)
    name = note_name(text, source if args.source else None)
    dest = team.notes / FOLDER_FOR[kind] / f"{name}.md"
    if dest.exists() and dest != previous:
        dest = dest.with_name(f"{name} ({team.author}).md")
        if dest.exists() and dest != previous:
            shared.die(f"{dest.name} already exists in {team.name}; rename the note first")
    with shared.Lock(team, wait_s=15):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
        vault_write.set_frontmatter(dest, {"origin": team.name, "author": team.author,
                                           "shared_at": shared.now_iso(), "source_id": sid})
        if previous and previous != dest:
            previous.unlink()
        verb = "Update" if previous else "Share"
        committed = shared.commit(team, f"{verb}: {dest.stem} ({team.author})",
                                  *([dest] + ([previous] if previous and previous != dest else [])))
        try:
            indexed, index_error = shared.reindex(team), None
        except SystemExit as e:
            indexed, index_error = None, str(e).removeprefix("error: ").splitlines()[0]
    result = {"team": team.name, "path": str(dest), "replaced": bool(previous),
              "committed": committed, "unpushed": shared.unpushed(team), "index_error": index_error}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'updated' if previous else 'shared'} {dest.name} in {team.name}"
              + (f" (index at next sync: {index_error})" if index_error else ""))
        if team.transport == "git":
            print(f"{result['unpushed']} commit(s) to push: ask the user, then `synapse shared push {team.name}`")
        else:
            print("the sync service carries it to the team")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    scrub.add_parsers(sub)
    p = sub.add_parser("add", help="put an approved, scrubbed note into a team folder")
    p.add_argument("team")
    p.add_argument("file", help="the approved note (output of `synapse share scrub`, reviewed)")
    p.add_argument("--source", default=None,
                   help="the personal note it came from (keeps one shared copy per note)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_add)
    args = parser.parse_args(argv)
    if args.cmd == "add":
        import extract  # noqa: F401  (may re-exec under the venv: before any write)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
