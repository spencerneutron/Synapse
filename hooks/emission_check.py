#!/usr/bin/env python3
"""
emission_check.py — Stop hook that enforces the mechanical part of the
emission contract on the final message of a turn.

Reads the Stop event JSON on stdin, checks `last_assistant_message` against
emission_patterns.json (next to this file), and blocks the stop once with a
rewrite instruction when any pattern matches. The judgment part of the contract
lives in the emission-contract skill; this script never decides style.

Guards:
  - stop_hook_active is true: this stop was already forced once; allow it.
  - Any internal error: allow the stop. A broken hook must never trap a session.

Registered in hooks/hooks.json. Stdlib only; runs on Python 3.9+.
"""

import json
import re
import sys
from pathlib import Path

# Force UTF-8 for stdout/stderr. Windows PowerShell defaults to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


PATTERNS_FILE = Path(__file__).with_name("emission_patterns.json")

FENCED_CODE = re.compile(r"(```|~~~).*?\1", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
QUOTE_LINE = re.compile(r"^[ \t]*>.*$", re.M)


def prose(text: str) -> str:
    """Strip code and quotes, which may legitimately hold banned words."""
    text = FENCED_CODE.sub("", text)
    text = INLINE_CODE.sub("", text)
    return QUOTE_LINE.sub("", text)


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def violations(message: str, patterns: list[dict]) -> list[str]:
    paras = paragraphs(prose(message))
    if not paras:
        return []
    regions = {"start": paras[0], "end": paras[-1], "anywhere": "\n\n".join(paras)}
    found = []
    for p in patterns:
        flags = re.I if p.get("ignore_case", True) else 0
        if re.search(p["regex"], regions[p["where"]], flags):
            found.append(p["message"])
    return list(dict.fromkeys(found))


def main() -> int:
    try:
        # Decode stdin as UTF-8 explicitly; Windows would otherwise use cp1252.
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if event.get("stop_hook_active"):
            return 0
        message = event.get("last_assistant_message") or ""
        if not message.strip():
            return 0
        patterns = json.loads(PATTERNS_FILE.read_text(encoding="utf-8"))["patterns"]
        found = violations(message, patterns)
    except Exception as e:  # fail open
        print(f"emission_check: skipped ({e})", file=sys.stderr)
        return 0

    if found:
        reason = (
            "Emission contract: rewrite your final message. Keep every fact; "
            "fix only these: " + "; ".join(found) + ". "
            "Load the synapse:emission-contract skill first if it is not loaded."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
