#!/usr/bin/env bash
# A two-minute fix (wc.py counts empty strings from split(" ") as words) in a
# project with planning files, and a .synapse.toml that sets the context
# window to 30000 tokens: an eval session starts near that size, so the 2.7.0
# Stop gate (60% and 90% of the window) asks for /synapse:checkpoint at the
# first stop. EXECUTION.md has no ## Resume section until a checkpoint writes
# one. The `synapse` CLI is not on an eval session's PATH, so the stamp step
# fails and the gate falls back to EXECUTION.md's modification time.
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
cat > wc.py <<'PY'
import sys


def count_words(text):
    """Number of words: runs of non-space characters."""
    return len(text.split(" "))


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        print(count_words(f.read()))
PY
printf 'the quick  brown fox\njumps over  the dog\n' > notes.txt
mkdir -p .claude-work/current
cat > .claude-work/current/PLAN.md <<'MD'
# PLAN

## Objective
Keep the small text tools in this repo correct.

## Decision Log
- wc.py stays stdlib only.
MD
cat > .claude-work/current/EXECUTION.md <<'MD'
# EXECUTION

## Active task
Fix the word count reported by wc.py.

## Next steps
- Reproduce with notes.txt, fix count_words, re-run.
MD
cat > .synapse.toml <<'TOML'
[nudge]
context_window = 30000
TOML
printf '.claude-work/\n' > .gitignore
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "wc"
