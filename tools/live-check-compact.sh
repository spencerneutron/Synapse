#!/usr/bin/env bash
# Live check of what survives an automatic compaction, in a real headless
# session with this repo as the plugin. Costs about $0.30 per run (to be
# corrected after measuring), so it refuses to start without --yes.
#
#   tools/live-check-compact.sh --yes [runs]
#   tools/live-check-compact.sh --setup-only      (free: builds the fixture, no claude call)
#
# Each run plants three items ONLY in the conversation (never in a file): a
# user-stated fact (deploy target KESTREL-7, never on Fridays), a decision with
# its rationale and rejected option (SQLite over Postgres), and an open question
# (CSV or Parquet). Turn 2 resumes the session with a tiny auto-compact window
# and has Claude read large filler files, so auto-compaction fires. The script
# then counts compact_boundary lines in the transcript (exit 3 if none: the
# retention was not tested). Turn 3 resumes and asks, without reading any file,
# for the three items; the reply is graded by grep. It also reports, by count
# only, whether Synapse's PreCompact guidance reached the transcript and
# whether a "Synapse: work in progress" line appeared (expected 0: the fixture
# has no EXECUTION.md). Read each printed reply.
#
# Exit 0 only when compaction happened and every planted item was recalled.
# The installed Synapse is disabled for the claude runs. macOS and Linux only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETUP_ONLY=0; RUNS=1
case "${1:-}" in
    --yes) RUNS="${2:-1}" ;;
    --setup-only) SETUP_ONLY=1 ;;
    *) echo "usage: tools/live-check-compact.sh --yes [runs]   (about \$0.30 per run)" >&2
       echo "       tools/live-check-compact.sh --setup-only   (free; no claude call)" >&2
       exit 2 ;;
esac
PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v '/plugins/cache/synapse/' | paste -sd: -)"
export PATH

# Auto-compact window for turn 2 only, in tokens. Pick a value just above the
# session's starting context (system prompt, tools, Synapse rules, turn 1) so
# the filler files push it over; raise it if turn 1 alone compacts, lower it if
# turn 2 does not.
WINDOW="${COMPACT_WINDOW:-35000}"
TOOLS=(Read "Bash(wc *)" "Bash(ls *)")
SETTINGS='{"enabledPlugins":{"synapse@synapse":false}}'

TURN1="Project notes for this session, stated by me. (a) Our deploy target is the cluster named KESTREL-7; we never deploy on Fridays. (b) We chose SQLite over Postgres because the tool runs offline; Postgres was rejected for needing a server. (c) Still open: whether the export should be CSV or Parquet. Do not write or read any file. Reply with the single word: noted."
TURN2="Read each of these files in full, one at a time, with the Read tool: filler1.txt, filler2.txt, filler3.txt, filler4.txt. Then report each file's line count (you may check with wc -l)."
TURN3="From this conversation only, list the deploy target, the database decision with its reason and the rejected option, and any open question. Do not read or write any file."

TMPS=()
cleanup() { [ "${#TMPS[@]}" -eq 0 ] || rm -rf "${TMPS[@]}"; }
trap cleanup EXIT

# Builds $H (throwaway home, left without setup: the hooks stay silent) and $W
# (git project with four ~60 KB filler files; the planted items are not in them).
build() {
    H="$(mktemp -d)"; W="$(mktemp -d)"; TMPS+=("$H" "$W")
    (cd "$W" && git init -q)
    for n in 1 2 3 4; do
        python3 -c '
import sys
n = sys.argv[1]
for i in range(1, 1501):
    print(f"filler{n} line {i:04d}: lorem ipsum dolor sit amet")' "$n" > "$W/filler$n.txt"
    done
}

# claude_turn PROMPT [extra claude args...]: runs one headless turn in $W.
claude_turn() {
    local prompt="$1"; shift
    (cd "$W" && SYNAPSE_HOME="$H" claude -p "$prompt" \
        --plugin-dir "$ROOT" --settings "$SETTINGS" --model sonnet \
        --allowedTools "${TOOLS[@]}" --max-budget-usd 0.5 --output-format json "$@")
}
reply_of() { python3 -c 'import json,sys; print(json.load(sys.stdin).get("result",""))'; }

if [ "$SETUP_ONLY" = 1 ]; then
    build
    SID="00000000-0000-4000-8000-000000000000"
    echo "setup ok: project $W (removed on exit), home $H"
    wc -c "$W"/filler*.txt
    echo "planned commands (not run):"
    echo "  turn 1: claude -p <plant prompt> --session-id $SID --plugin-dir $ROOT --settings '$SETTINGS' --model sonnet --allowedTools ${TOOLS[*]} --max-budget-usd 0.5 --output-format json"
    echo "  turn 2: CLAUDE_CODE_AUTO_COMPACT_WINDOW=$WINDOW claude -p <read filler1-4> --resume $SID ... (same flags)"
    echo "  check : count type=system subtype=compact_boundary in ~/.claude/projects/*/$SID.jsonl (none: exit 3)"
    echo "  turn 3: claude -p <recall prompt> --resume $SID ... (same flags, no small window); grep KESTREL-7 Fridays SQLite offline Postgres CSV Parquet"
    exit 0
fi

fail=0
for i in $(seq 1 "$RUNS"); do
    build
    SID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
    claude_turn "$TURN1" --session-id "$SID" >/dev/null
    CLAUDE_CODE_AUTO_COMPACT_WINDOW="$WINDOW" claude_turn "$TURN2" --resume "$SID" >/dev/null

    T="$(find "$HOME/.claude/projects" -name "$SID.jsonl" 2>/dev/null | head -n 1)"
    if [ -z "$T" ]; then echo "== run $i: transcript for $SID not found" >&2; fail=1; continue; fi
    # Counts and trigger only; never message content.
    info="$(python3 - "$T" <<'PY'
import json, sys
n = 0; trig = set()
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except ValueError:
        continue
    if d.get("type") == "system" and d.get("subtype") == "compact_boundary":
        n += 1
        meta = d.get("compactMetadata") or d.get("compact_metadata") or {}
        trig.add(str(meta.get("trigger", "unknown")))
print(n, ",".join(sorted(trig)) or "none")
PY
)"
    n_compact="${info%% *}"; trigger="${info#* }"
    if [ "$n_compact" = 0 ]; then
        echo "== run $i: NO COMPACTION: retention not tested"
        fail=3; continue
    fi

    reply="$(claude_turn "$TURN3" --resume "$SID" | reply_of)"
    echo "== run $i: compactions: $n_compact (trigger: $trigger)"
    missing=0
    for w in KESTREL-7 Fridays SQLite offline Postgres CSV Parquet; do
        if printf '%s' "$reply" | grep -qi -- "$w"; then echo "  found:   $w"; else echo "  missing: $w"; missing=1; fi
    done
    guide="$(grep -c 'Guidance for this compaction summary' "$T" || true)"
    wip="$(grep -c 'Synapse: work in progress' "$T" || true)"
    echo "  PreCompact guidance lines in transcript: $guide (expected >= 1)"
    echo "  'work in progress' lines in transcript: $wip (expected 0: no EXECUTION.md)"
    printf '%s\n\n' "$reply"
    [ "$missing" = 0 ] || { [ "$fail" = 3 ] || fail=1; }
done
exit "$fail"
