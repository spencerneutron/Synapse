#!/usr/bin/env bash
# Run the Synapse eval suite with safe defaults. It spends model calls, so it
# refuses to start without --yes.
#
#   tools/run-evals.sh --yes [extra claude plugin eval flags, e.g. --case review-planted-bug]
#
# Always: --no-publish (reports stay local), --max-cost-usd (default 12, set
# EVAL_MAX_COST_USD to change), --ablation none, --runs 2; later flags (such
# as --ablation with-without) override these. The whole suite is 15 cases x 2
# runs, about $2.50-3.00; the memory cases need EVAL_SYNAPSE_HOME, so
# tools/run-bench.sh is the way to run all of it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${1:-}" != "--yes" ]; then
    echo "This runs the eval suite: real Claude sessions that cost money (about \$2.50-3.00 for all of it)." >&2
    echo "Reports stay local. Re-run with --yes to start, for example:" >&2
    echo "  tools/run-evals.sh --yes" >&2
    echo "  tools/run-evals.sh --yes --case review-planted-bug" >&2
    exit 2
fi
shift

cd "$ROOT"
# Run from inside a Claude Code session, PATH carries the installed Synapse's
# bin/; an eval must call the plugin under test, so drop installed copies.
PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v '/plugins/cache/synapse/' | paste -sd: -)"
export PATH
exec claude plugin eval . \
    --runs 2 --ablation none --scaffold \
    --allow-tools Bash Edit Write Agent \
    --trust-plugin --no-publish --threshold 0 -j 2 \
    --max-cost-usd "${EVAL_MAX_COST_USD:-12}" \
    "$@" < /dev/null
