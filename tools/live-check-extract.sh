#!/usr/bin/env bash
# Live check of the extractor's prior-note check in a real headless session
# (not `claude plugin eval`: eval sessions cannot run the synapse CLI). Costs
# about $0.30 per run, so it refuses to start without --yes.
#
#   tools/live-check-extract.sh --yes [runs]
#   tools/live-check-extract.sh --setup-only      (free: builds the fixture, no claude call)
#
# Each run builds a throwaway Synapse home with one prior Decision ("The e2e
# workflow runs nightly on a schedule", embedded) and an archived session
# whose Decision Log decides the opposite (every push, not nightly). It asks
# Claude (this repo as the plugin, the installed Synapse disabled) to extract
# that session and checks that the reply names the prior note as superseded,
# ends with the "Proceed?" question, and that nothing was written to the vault
# before approval. Read each printed reply. Needs Ollama with nomic-embed-text.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETUP_ONLY=0; RUNS=1
case "${1:-}" in
    --yes) RUNS="${2:-1}" ;;
    --setup-only) SETUP_ONLY=1 ;;
    *) echo "usage: tools/live-check-extract.sh --yes [runs]   (about \$0.30 per run)" >&2
       echo "       tools/live-check-extract.sh --setup-only   (free; no claude call)" >&2
       exit 2 ;;
esac
PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v '/plugins/cache/synapse/' | paste -sd: -)"
export PATH
if ! curl -fsS -m 3 http://localhost:11434/api/tags 2>/dev/null | grep -q 'nomic-embed-text'; then
    echo "error: Ollama is not running or lacks nomic-embed-text (ollama pull nomic-embed-text)" >&2
    exit 1
fi

PROJECT="flagship"; SESSION="2026-11-06-1200"
PRIOR="Run the e2e workflow nightly on a schedule"
TMPS=()
cleanup() { [ "${#TMPS[@]}" -eq 0 ] || rm -rf "${TMPS[@]}"; }
trap cleanup EXIT

syn() { SYNAPSE_HOME="$H" "$ROOT/bin/synapse" "$@"; }

# Builds $H (home) and $W (scratch project) for one run.
build() {
    H="$(mktemp -d)"; W="$(mktemp -d)"; TMPS+=("$H" "$W")
    rm -rf "$H"  # setup wants a new folder
    syn setup >/dev/null
    printf 'default_store = "main"\n\n[stores.main]\nvault = "Fixture"\nvault_path = "%s"\n\n[recall]\nauto = false\n' \
        "$H/vault" > "$H/config.toml"
    mkdir -p "$H/vault/Decisions"
    cat > "$H/vault/Decisions/$PRIOR.md" <<NOTE
---
type: decision
date: 2026-09-15
project: $PROJECT
session_id: 2026-09-15-1000
status: active
tags: [decision]
---
# $PRIOR

## Context
The e2e workflow is slow and its trigger schedule was open.

## Decision
The e2e workflow runs nightly on a schedule, not on pushes.

## Rationale
- It takes 40 minutes; nightly keeps CI fast.
NOTE
    syn extract embed-note "$H/vault/Decisions/$PRIOR.md" >/dev/null
    (cd "$W" && git init -q && printf 'project = "%s"\n' "$PROJECT" > .synapse.toml)
    A="$(syn where --project "$PROJECT" --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["archive_dir"])')"
    mkdir -p "$A"
    cat > "$A/PLAN_$SESSION.md" <<'FILE'
# PLAN - CI triggers
## Purpose
Decide when the e2e workflow runs.
## Progress
- [x] Compare nightly against per-push runs
- [x] Update the workflow trigger
FILE
    cat > "$A/EXECUTION_$SESSION.md" <<'FILE'
# EXECUTION - CI triggers (2026-11-06)
## Decision Log
- The e2e workflow runs on every push, not nightly. Rationale: a nightly run
  let two regressions merge and sit for a day; the suite now takes 6 minutes,
  so per-push is cheap.
## Done
- Changed the e2e workflow trigger from `schedule` to `push`.
FILE
    cat > "$A/NOTES_$SESSION.md" <<'FILE'
# NOTES - CI triggers
## Open questions
- None.
## User-stated facts
- The release manager signs off every Friday; merges to main freeze at noon.
FILE
}

# Prints the candidate check for the planted concept; returns 0 if >= 0.70.
score_check() {
    local f="$W/cands.json"
    printf '[{"type":"decision","title":"Run the e2e workflow on every push","concept":"e2e workflow trigger schedule"}]\n' > "$f"
    local out
    out="$(cd "$W" && SYNAPSE_HOME="$H" "$ROOT/bin/synapse" extract check-candidates "$f" --session "$SESSION")"
    printf '%s\n' "$out"
    printf '%s' "$out" | python3 -c '
import json,sys
hits=[h for c in json.load(sys.stdin)["candidates"] for h in c["hits"]]
sys.exit(0 if any(h["score"]>=0.70 for h in hits) else 1)'
}

if [ "$SETUP_ONLY" = 1 ]; then
    build
    score_check || { echo "FAIL: the planted note scored below 0.70" >&2; exit 1; }
    echo "setup ok: home $H, archive $A (removed on exit)"
    exit 0
fi

fail=0
for i in $(seq 1 "$RUNS"); do
    build
    score_check >/dev/null || { echo "== run $i: setup failed, planted note scores below 0.70" >&2; fail=1; continue; }
    before="$(ls "$H/vault/Decisions" | wc -l)"
    out="$(cd "$W" && SYNAPSE_HOME="$H" claude -p \
        "Extract session $SESSION for project $PROJECT." \
        --plugin-dir "$ROOT" --settings '{"enabledPlugins":{"synapse@synapse":false}}' \
        --allowedTools "Bash(synapse *)" "Bash(mktemp *)" "Bash(cat *)" "Bash(ls *)" Read Write Skill Agent Task \
        --max-budget-usd 1 --output-format json)"
    after="$(ls "$H/vault/Decisions" | wc -l)"
    reply="$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result",""))')"
    sup="$(printf '%s' "$reply" | grep -iE 'supersede' | grep -ciE 'nightly' || true)"
    asks="$(printf '%s' "$reply" | tail -n 3 | grep -c 'Proceed?' || true)"
    echo "== run $i: Decisions $before -> $after, supersession named: $sup, ends with Proceed?: $asks"
    printf '%s\n\n' "$reply"
    [ "$before" = "$after" ] && [ "$sup" != 0 ] && [ "$asks" != 0 ] || fail=1
done
exit "$fail"
