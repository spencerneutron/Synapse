#!/usr/bin/env bash
# Run the whole eval suite in two arms, with Synapse and without it, and print
# what Synapse adds. It spends model calls (about $6 at 2 runs per case), so it
# refuses to start without --yes.
#
#   tools/run-bench.sh --yes [extra claude plugin eval flags, e.g. --runs 1]
#
# Builds the fixture homes the memory cases need (Ollama must be running),
# runs each tag with its home through tools/run-evals.sh (local reports, a
# cost cap per tag: $13.50 in all), then tools/eval-report.py. Results go to
# BENCH_OUT, or a new temp folder; the path is printed at the end.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${1:-}" != "--yes" ]; then
    echo "This runs every eval case twice (with and without Synapse): real Claude sessions," >&2
    echo "about \$6 at 2 runs per case, capped at \$13.50. Reports stay local. Re-run with --yes." >&2
    exit 2
fi
shift

OUT="${BENCH_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/synapse-bench.XXXXXX")}"
mkdir -p "$OUT"
echo "reports: $OUT" >&2
home() {  # name, build flags: build into a temp folder, keep it only when complete
    [ -d "$OUT/$1" ] && return
    rm -rf "$OUT/$1.tmp"
    python3 "$ROOT/tools/build_eval_home.py" "$OUT/$1.tmp" "${@:2}" && mv "$OUT/$1.tmp" "$OUT/$1"
}
home home-d --triggers on
home home-e --triggers on --team

failed=0
run() {   # tag, Synapse home ("" for none), cost cap
    local tag="$1" home="$2" cap="$3"; shift 3
    echo "== $tag" >&2
    if ! EVAL_SYNAPSE_HOME="$home" EVAL_MAX_COST_USD="$cap" "$ROOT/tools/run-evals.sh" --yes \
            --ablation with-without --tag "$tag" --json "$OUT/$tag.json" "$@" > "$OUT/$tag.log" 2>&1; then
        echo "   $tag did not finish cleanly; see $OUT/$tag.log" >&2
        failed=1
    fi
}
run slice-c "" 7 "$@"
run core "" 2 "$@"
run slice-d "$OUT/home-d" 3 "$@"
run slice-e "$OUT/home-e" 1.5 "$@"

shopt -s nullglob
results=("$OUT"/*.json)
if [ ${#results[@]} -eq 0 ]; then
    echo "no results to report; see the logs in $OUT" >&2
    exit 1
fi
python3 "$ROOT/tools/eval-report.py" "${results[@]}" || failed=1
echo "reports: $OUT"
exit "$failed"
