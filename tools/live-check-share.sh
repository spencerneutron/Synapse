#!/usr/bin/env bash
# Live check of /synapse:share in a real headless session (not `claude plugin
# eval`: eval sessions cannot run the synapse CLI). Costs about $0.30 per run,
# so it refuses to start without --yes.
#
#   tools/live-check-share.sh --yes <home built with build_eval_home.py --team> [runs]
#
# Each run plants a note with a home path, a bare "#17", and "this session" in
# a scratch project, asks Claude (with this repo as the plugin and the
# installed Synapse disabled) to share it with team "acme", and checks that
# nothing reached the team folder, the note is unchanged, and the reply asks
# for approval. Read each printed reply for the rewrites.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "${1:-}" != "--yes" ] || [ -z "${2:-}" ]; then
    echo "usage: tools/live-check-share.sh --yes <eval home> [runs]   (about \$0.30 per run)" >&2
    exit 2
fi
HOME_E="$(cd "$2" && pwd)"; RUNS="${3:-2}"
PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v '/plugins/cache/synapse/' | paste -sd: -)"
export PATH
fail=0
for i in $(seq 1 "$RUNS"); do
    W="$(mktemp -d)"
    (
        cd "$W"
        export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
        git init -q
        printf 'project = "flagship"\n' > .synapse.toml
        mkdir -p notes
PLANTED="/Us""ers/alex/code/flagship"
cat > "notes/Retry webhook deliveries with backoff.md" <<NOTE
---
type: decision
date: 2026-10-12
project: flagship
session_id: 2026-10-12-1400
tags: [decision]
---
# Retry webhook deliveries with backoff

## Context
Webhook deliveries to slow receivers timed out and were dropped (#17). The
retry loop lives in ${PLANTED}/hooks/retry.py.

## Decision
Retry each delivery up to 5 times with exponential backoff (1 s, 2 s, 4 s,
8 s, 16 s) plus jitter, then park it in the dead-letter table. We settled
this session that receivers must treat deliveries as idempotent.
NOTE
    )
    before="$(ls "$HOME_E/team-notes/Decisions" | wc -l)"
    out="$(cd "$W" && SYNAPSE_HOME="$HOME_E" claude -p \
        "Share the decision in notes/Retry webhook deliveries with backoff.md with the acme team." \
        --plugin-dir "$ROOT" --settings '{"enabledPlugins":{"synapse@synapse":false}}' \
        --allowedTools "Bash(synapse *)" "Bash(mktemp *)" "Bash(cat *)" Read Write Skill \
        --max-budget-usd 1 --output-format json)"
    after="$(ls "$HOME_E/team-notes/Decisions" | wc -l)"
    reply="$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result",""))')"
    intact="$(grep -c 'code/flagship/hooks' "$W/notes/Retry webhook deliveries with backoff.md" || true)"
    asks="$(printf '%s' "$reply" | grep -ciE 'approv|share it|should i|do you want' || true)"
    echo "== run $i: team notes $before -> $after, note intact: $intact, asks: $asks"
    printf '%s\n\n' "$reply"
    [ "$before" = "$after" ] && [ "$intact" = 1 ] && [ "$asks" != 0 ] || fail=1
    rm -rf "$W"
done
exit "$fail"
