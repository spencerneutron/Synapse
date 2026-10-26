#!/usr/bin/env python3
"""
build_context.py — build the SessionStart payloads from instructions/*.md.

  python3 tools/build_context.py          # write hooks/context/*.json
  python3 tools/build_context.py --check  # fail if stale or over the cap

Claude Code inserts a SessionStart hook's additionalContext as-is up to 10,000
characters; past that it saves the text to a file and shows only a preview.
Each instructions file therefore has to stay under the cap. The payloads are
prebuilt so hooks/session_start.sh needs nothing but bash and cat.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ("core", "platform-macos", "platform-windows")
CAP = 10_000
HEADROOM = 9_500


def payload(text: str) -> str:
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    problems = []
    for name in SOURCES:
        text = (ROOT / "instructions" / f"{name}.md").read_text(encoding="utf-8")
        size = len(text)
        if size > CAP:
            problems.append(f"{name}.md is {size} characters; the cap is {CAP}")
        elif size > HEADROOM:
            print(f"warning: {name}.md is {size} characters, close to the {CAP} cap")
        out = ROOT / "hooks" / "context" / f"{name}.json"
        want = payload(text)
        if args.check:
            if not out.exists() or out.read_text(encoding="utf-8") != want:
                problems.append(f"{out.relative_to(ROOT)} is stale; run tools/build_context.py")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(want, encoding="utf-8")
        print(f"{name}: {size} characters")

    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
