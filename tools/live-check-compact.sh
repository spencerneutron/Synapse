#!/usr/bin/env bash
# Live check of what survives an automatic compaction, in a real headless
# session with this repo as the plugin. Costs about $0.55 per run of one arm
# (measured 2026-11-06: $0.52 on Sonnet; both arms about $1.04 per run pair), so
# it refuses to start without --yes.
#
#   tools/live-check-compact.sh --yes [runs] [--arms on|off|both]
#   tools/live-check-compact.sh --setup-only      (free: builds the fixture, no claude call)
#
# Arms: "on" (default) runs with the PreCompact hook (synapse compact-guide
# --hook) as shipped. "off" writes [continuation] compact_guide = false into the
# fixture home's config.toml before turn 1, so the hook prints nothing and
# Claude Code's default summary is all that carries the items. Hook stdout is
# not recorded in transcripts, so only the off arm shows what the hook adds:
# run "both" and compare the side-by-side summary printed at the end.
#
# Each run plants three items ONLY in the conversation (never in a file): a
# user-stated fact (deploy target KESTREL-7, never on Fridays), a decision with
# its rationale and rejected option (SQLite over Postgres), and an open question
# (CSV or Parquet). Turn 2 resumes the session with a tiny auto-compact window
# and has Claude read large filler files, so auto-compaction fires. The script
# then counts compact_boundary lines in the transcript (exit 3 if none: the
# retention was not tested). Turn 3 resumes and asks, without reading any file,
# for the three items; the reply is graded by grep. It also reports, by count
# only, the summary's size and the session's cost. Read each printed reply.
#
# Exit 0 only when compaction happened and every planted item was recalled.
# Otherwise the worst code over all runs of all arms (the off arm counts the
# same: it also exits 1 when an item is missing, which only says the default
# summary lost it): 1 (an item missing or the transcript
# not found), else 3 (no compaction), else 4 (a claude turn failed, e.g. over
# budget). Usage errors exit 2.
# The installed Synapse is disabled for the claude runs. macOS and Linux only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETUP_ONLY=0; RUNS=1; ARMS=on
usage() {
    echo "usage: tools/live-check-compact.sh --yes [runs] [--arms on|off|both]   (about \$0.55 per run per arm; both: \$1.04)" >&2
    echo "       tools/live-check-compact.sh --setup-only   (free; no claude call)" >&2
    exit 2
}
case "${1:-}" in
    --yes)
        shift
        case "${1:-}" in ''|--*) ;; *) RUNS="$1"; shift ;; esac
        case "${1:-}" in
            '') ;;
            --arms) case "${2:-}" in on|off|both) ARMS="$2" ;; *) usage ;; esac; shift 2 ;;
            *) usage ;;
        esac
        [ "$#" -eq 0 ] || usage
        case "$RUNS" in ''|*[!0-9]*|0*) usage ;; esac ;;
    --setup-only) [ "$#" -eq 1 ] || usage; SETUP_ONLY=1 ;;
    *) usage ;;
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

OFF_CONFIG=$'[continuation]\ncompact_guide = false'

TURN1="Project notes for this session, stated by me. (a) Our deploy target is the cluster named KESTREL-7; we never deploy on Fridays. (b) We chose SQLite over Postgres because the tool runs offline; Postgres was rejected for needing a server. (c) Still open: whether the export should be CSV or Parquet. Do not write or read any file. Reply with the single word: noted."
TURN2="Read each of these files in full, one at a time, with the Read tool: filler1.txt, filler2.txt, filler3.txt, filler4.txt. Then report each file's line count (you may check with wc -l)."
TURN3="From this conversation only, list the deploy target, the database decision with its reason and the rejected option, and any open question. Do not read or write any file."

TMPS=()
cleanup() { [ "${#TMPS[@]}" -eq 0 ] || rm -rf "${TMPS[@]}"; }
trap cleanup EXIT

# build ARM: $H (throwaway home, left without setup: the other hooks stay
# silent, compact-guide still prints) and $W (git project with four ~60 KB
# filler files; the planted items are not in them). Arm "off" writes the switch.
build() {
    H="$(mktemp -d)"; W="$(mktemp -d)"; TMPS+=("$H" "$W")
    if [ "${1:-on}" = off ]; then printf '%s\n' "$OFF_CONFIG" > "$H/config.toml"; fi
    # Fail before any paid call if the switch does not do what the arm claims.
    local hook_out
    hook_out="$(SYNAPSE_HOME="$H" python3 "$ROOT/lib/synapse/cli.py" compact-guide --hook </dev/null 2>/dev/null || true)"
    if [ "${1:-on}" = off ] && [ -n "$hook_out" ]; then
        echo "error: hook-off arm: compact-guide --hook still prints guidance; aborting before any claude call" >&2; exit 2
    elif [ "${1:-on}" != off ] && [ -z "$hook_out" ]; then
        echo "error: hook-on arm: compact-guide --hook printed nothing; aborting before any claude call" >&2; exit 2
    fi
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
    build off
    SID="00000000-0000-4000-8000-000000000000"
    echo "setup ok: project $W (removed on exit), home $H"
    wc -c "$W"/filler*.txt
    echo "arms: on (hook as shipped) and off (config.toml in the home gets: [continuation] compact_guide = false)"
    echo "  off-arm config written to $H/config.toml:"; sed 's/^/    /' "$H/config.toml"
    echo "planned commands (not run; each arm runs these, in a fresh fixture):"
    echo "  turn 1: claude -p <plant prompt> --session-id $SID --plugin-dir $ROOT --settings '$SETTINGS' --model sonnet --allowedTools ${TOOLS[*]} --max-budget-usd 0.5 --output-format json"
    echo "  turn 2: CLAUDE_CODE_AUTO_COMPACT_WINDOW=$WINDOW claude -p <read filler1-4> --resume $SID ... (same flags)"
    echo "  check : count type=system subtype=compact_boundary in ${CLAUDE_CONFIG_DIR:-~/.claude}/projects/*/$SID.jsonl (none: exit 3)"
    echo "  turn 3: claude -p <recall prompt> --resume $SID ... (same flags, no small window); grep KESTREL-7 Fridays SQLite offline Postgres CSV Parquet"
    exit 0
fi

# Worst exit code over the runs and arms: any 1 -> 1, else any 3 -> 3, else any 4 -> 4.
fail=0
note() {
    local c="$1" rank_new rank_old
    rank() { case "$1" in 1) echo 3 ;; 3) echo 2 ;; 4) echo 1 ;; *) echo 0 ;; esac; }
    rank_new="$(rank "$c")"; rank_old="$(rank "$fail")"
    [ "$rank_new" -le "$rank_old" ] || fail="$c"
}

# One result line per graded run: "arm<TAB>compactions<TAB>recalled<TAB>missing<TAB>chars"
RESULTS=()

# run_arm ARM RUN-NUMBER: one full check; returns 0 always (failures go through note).
run_arm() {
    local arm="$1" i="$2" label="run $2 [hook $1]"
    build "$arm"
    SID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
    if ! claude_turn "$TURN1" --session-id "$SID" >/dev/null; then
        echo "== $label: turn 1 (plant) failed" >&2; note 4; return 0
    fi
    turn2_failed=0
    CLAUDE_CODE_AUTO_COMPACT_WINDOW="$WINDOW" claude_turn "$TURN2" --resume "$SID" >/dev/null || turn2_failed=1

    T="$(find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects" -name "$SID.jsonl" 2>/dev/null | head -n 1)" || T=""
    if [ -z "$T" ]; then
        if [ "$turn2_failed" = 1 ]; then echo "== $label: turn 2 (filler reads) failed" >&2; note 4
        else echo "== $label: transcript for $SID not found" >&2; note 1; fi
        return 0
    fi
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
)" || info=""
    if [ -z "$info" ]; then echo "== $label: could not read the transcript" >&2; note 1; return 0; fi
    n_compact="${info%% *}"; trigger="${info#* }"
    if [ "$n_compact" = 0 ]; then
        if [ "$turn2_failed" = 1 ]; then
            echo "== $label: turn 2 (filler reads) failed, no compaction" >&2; note 4
        else
            echo "== $label: NO COMPACTION: retention not tested"; note 3
        fi
        return 0
    fi
    if [ "$turn2_failed" = 1 ]; then
        echo "== $label: turn 2 stopped early (e.g. budget); compaction happened, recall still tested"
    fi

    if ! out="$(claude_turn "$TURN3" --resume "$SID")"; then
        echo "== $label: turn 3 (recall) failed" >&2; note 4; return 0
    fi
    reply="$(printf '%s' "$out" | reply_of)" || reply=""
    echo "== $label: compactions: $n_compact (trigger: $trigger)"
    missing=0; miss_list=""; got=0
    for w in KESTREL-7 Fridays SQLite offline Postgres CSV Parquet; do
        if printf '%s' "$reply" | grep -qi -- "$w"; then echo "  found:   $w"; got=$((got + 1))
        else echo "  missing: $w"; missing=1; miss_list="$miss_list${miss_list:+,}$w"; fi
    done
    # Hook output is not recorded in transcripts; report the summary's size
    # and the session cost.
    sinfo="$(python3 - "$T" <<'PY'
import json, sys
chars, cost = 0, None
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    try:
        e = json.loads(line)
    except ValueError:
        continue
    if e.get("isCompactSummary"):
        c = e.get("message", {}).get("content")
        chars = len(c if isinstance(c, str) else json.dumps(c))
    if e.get("type") == "cost-state" and isinstance(e.get("totalCostUSD"), (int, float)):
        cost = e["totalCostUSD"]
print(chars, "unknown" if cost is None else f"${cost:.2f}")
PY
)" || sinfo="0 unknown"
    echo "  compaction summary: ${sinfo%% *} characters; session cost: ${sinfo#* }"
    RESULTS+=("$arm"$'\t'"$n_compact"$'\t'"$got"$'\t'"${miss_list:-none}"$'\t'"${sinfo%% *}")
    printf '%s\n\n' "$reply"
    [ "$missing" = 0 ] || note 1
    return 0
}

for i in $(seq 1 "$RUNS"); do
    case "$ARMS" in on|both) run_arm on "$i" ;; esac
    case "$ARMS" in off|both) run_arm off "$i" ;; esac
done

# Side by side: one row per arm; recalled, missing and characters list each graded run.
if [ "${#RESULTS[@]}" -gt 0 ]; then
    python3 - "${RESULTS[@]}" <<'PY'
import sys
rows = [a.split("\t") for a in sys.argv[1:]]
print("== summary by arm (hook on = PreCompact guidance printed; hook off = default summary only)")
print(f"{'arm':<6}{'runs':<6}{'compactions':<13}{'recalled /7':<14}{'missing':<26}summary chars")
for arm in ("on", "off"):
    rs = [r for r in rows if r[0] == arm]
    if rs:
        print(f"{arm:<6}{len(rs):<6}{sum(int(r[1]) for r in rs):<13}"
              f"{','.join(r[2] for r in rs):<14}{'; '.join(r[3] for r in rs):<26}{','.join(r[4] for r in rs)}")
PY
fi
exit "$fail"
