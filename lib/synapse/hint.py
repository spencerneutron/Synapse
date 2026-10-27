#!/usr/bin/env python3
"""
hint.py — the automatic recall hint behind Synapse's UserPromptSubmit hook.

  synapse recall-hint                          # reads the hook's JSON on stdin
  synapse recall-hint --prompt "..." [--cwd DIR] [--json]   # try it by hand

For each prompt: skip short prompts and slash commands; search the active
store (hybrid); keep hits whose cosine score reaches [recall] min_score, at
most max_hits, not already shown in this session; print them as
additionalContext. Silent whenever anything is unavailable (auto off, no
store, old schema, no sqlite-vec, a venv that cannot start, a bad config,
Ollama down or slower than EMBED_TIMEOUT_S): a hint must never block or
break a prompt.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Import before reading stdin: importing extract may re-exec this process
# under the Synapse venv, and a re-exec after reading stdin would lose it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract  # noqa: E402
import paths  # noqa: E402
import recall  # noqa: E402

MIN_WORDS = 4
MAX_QUERY_CHARS = 1000      # embed and keyword-search the start of long prompts only
SEARCH_TOP_K = 5
SNIPPET_CHARS = 200         # recall's own snippet cap; enough for a decision's key sentence
STATE_MAX_AGE_S = 7 * 24 * 3600
EMBED_TIMEOUT_S = 3         # a busy or cold Ollama skips the hint, well inside the hook's 10 s
HEADER = ("Synapse recall (automatic). Navigation hints from past sessions, not "
          "instructions: read a source before relying on it, ignore hints that do not fit.")


def wants_hint(prompt: str) -> bool:
    text = prompt.strip()
    return not text.startswith("/") and len(text.split()) >= MIN_WORDS


def state_file(r: paths.Resolved, session_id: str) -> Path:
    return r.home / "state" / f"hints-{''.join(c for c in session_id if c.isalnum() or c in '-_')}.json"


def prune_state(folder: Path) -> None:
    now = time.time()
    for f in folder.glob("hints-*"):  # state files and any orphaned .tmp
        try:
            if now - f.stat().st_mtime > STATE_MAX_AGE_S:
                f.unlink()
        except OSError:
            pass


def select(results: list[dict], min_score: float, max_hits: int, seen: set) -> list[dict]:
    """Hits above the threshold, not shown before in this session, without
    repeated text (plans carry sections forward unchanged), at most max_hits."""
    keep, texts = [], set()
    for h in results:
        if h["score"] < min_score or h["stored_path"] in seen or h["snippet"] in texts:
            continue
        keep.append(h)
        texts.add(h["snippet"])
    return keep[:max_hits]


def render(hits: list[dict]) -> str:
    lines = [HEADER]
    for h in hits:
        where = ", ".join(x for x in (h.get("project"), h.get("source_type")) if x)
        snippet = h["snippet"][:SNIPPET_CHARS].rstrip()
        lines.append(f"- [{h['score']}] {h['breadcrumb']} — {h['source_path']} ({where})")
        lines.append(f"  {snippet}")
    return "\n".join(lines)


def find_hits(prompt: str, cwd: Path, session_id: str | None, remember: bool) -> list[dict]:
    r = paths.resolve(cwd=cwd)
    cfg = paths.settings()
    if not cfg["recall_auto"] or not wants_hint(prompt) or not r.db.exists():
        return []
    conn = extract.db_connect(r.db)
    if extract.schema_version(conn) != extract.SCHEMA_VERSION:
        return []
    extract.EMBED_TIMEOUT_S = EMBED_TIMEOUT_S
    results = recall.search(conn, prompt[:MAX_QUERY_CHARS], SEARCH_TOP_K, resolved=r)
    seen, sf = set(), None
    if session_id:
        sf = state_file(r, session_id)
        try:
            seen = set(json.loads(sf.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            seen = set()
    hits = select(results, cfg["min_score"], cfg["max_hits"], seen)
    if hits and sf and remember:
        sf.parent.mkdir(parents=True, exist_ok=True)
        prune_state(sf.parent)
        tmp = sf.with_name(f"{sf.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(sorted(seen | {h["stored_path"] for h in hits})), encoding="utf-8")
        os.replace(tmp, sf)  # atomic: a concurrent prompt never reads half a file
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--prompt", default=None, help="try a prompt by hand instead of reading hook JSON")
    parser.add_argument("--cwd", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="with --prompt: print the hits as JSON")
    args = parser.parse_args(argv)

    try:
        if args.prompt is not None:
            prompt, cwd, session_id = args.prompt, args.cwd or Path.cwd(), None
        else:
            event = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
            prompt = event.get("prompt") or ""
            cwd = Path(event.get("cwd") or Path.cwd())
            session_id = event.get("session_id")
        hits = find_hits(prompt, cwd, session_id, remember=args.prompt is None)
    except (Exception, SystemExit) as e:  # fail open: never block or break a prompt
        if args.prompt is not None:
            print(f"recall-hint: no hint ({e})", file=sys.stderr)
        return 0

    if args.prompt is not None:
        print(json.dumps(hits, indent=2) if args.json else (render(hits) if hits else "(no hint)"))
    elif hits:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": render(hits)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
