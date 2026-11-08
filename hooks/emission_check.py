#!/usr/bin/env python3
"""
emission_check.py — Stop hook that enforces the mechanical part of the
emission contract on the final message of a turn.

Reads the Stop event JSON on stdin, checks `last_assistant_message` against
emission_patterns.json (next to this file), and blocks the stop once when any
pattern matches. The block reason carries the contract's directive in compact
form (from the same file) plus the violations found, so the rewrite needs no
skill load. skills/emission-contract/SKILL.md is the reference text; the
judgment-only rules there are not checked here.

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
    words = len(regions["anywhere"].split())
    found = []
    for p in patterns:
        flags = re.I if p.get("ignore_case", True) else 0
        if p.get("multiline"):
            flags |= re.M
        region = regions[p["where"]]
        if "max_count" in p:
            hit = (len(re.findall(p["regex"], region, flags)) > p["max_count"]
                   and words < p.get("max_words", float("inf")))
        else:
            hit = re.search(p["regex"], region, flags)
        if hit:
            found.append(p["message"])
    return list(dict.fromkeys(found))


def block_reason(found: list[str], directive: list[str]) -> str:
    return "\n".join(
        ["Emission contract: rewrite your final message, keeping every fact.", "Found:"]
        + [f"- {f}" for f in found]
        + ["The contract:"]
        + [f"{i}. {d}." for i, d in enumerate(directive, 1)]
        + ["Write only the rewritten message, with no preface."]
    )


def main() -> int:
    try:
        # Decode stdin as UTF-8 explicitly; Windows would otherwise use cp1252.
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if event.get("stop_hook_active"):
            return 0
        message = event.get("last_assistant_message") or ""
        if not message.strip():
            return 0
        spec = json.loads(PATTERNS_FILE.read_text(encoding="utf-8"))
        found = violations(message, spec["patterns"])
        if found:
            reason = block_reason(found, spec["directive"])
            print(json.dumps({"decision": "block", "reason": reason}))
    except Exception as e:  # fail open, but say why
        print(f"emission_check: skipped ({type(e).__name__}: {e})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
