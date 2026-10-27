#!/usr/bin/env bash
# Find a working Python (3.11+ unless SYNAPSE_MIN_PY says otherwise) and exec
# the given script with it.
#
# Adapted from the launcher in Anthropic's security-guidance plugin. It handles
# the cases that break a bare `python3` in a hook command:
#   - Windows: `python3` is often the Microsoft Store stub, which exits silently
#     in a non-TTY subprocess. Each candidate is probed before use, so the stub
#     falls through to `python` or the `py -3` launcher.
#   - Git Bash hands script paths over in POSIX form (/c/Users/...), which a
#     Windows python.exe misreads; absolute paths are converted with cygpath.
#   - macOS ships Python 3.9 as /usr/bin/python3; versioned binaries from
#     Homebrew or python.org are tried when the bare name is too old.
# PYTHONUTF8=1 keeps file and pipe I/O in UTF-8 on Windows (no-op elsewhere).
#
# Usage: bash lib/py.sh <script.py> [args...]
#        SYNAPSE_MIN_PY=3.9 bash lib/py.sh <script.py>   (lower the floor)
#        SYNAPSE_OPTIONAL=1 bash lib/py.sh <script.py>   (no Python: exit 0 silently)
set -e
export PYTHONUTF8=1
MIN="${SYNAPSE_MIN_PY:-3.11}"

if command -v cygpath >/dev/null 2>&1; then
    converted=()
    for a in "$@"; do
        case "$a" in
            /*) converted+=("$(cygpath -w "$a")") ;;
            *) converted+=("$a") ;;
        esac
    done
    set -- "${converted[@]}"
fi

# True when the interpreter runs, meets $MIN, and can read the target script.
ok() {
    "$@" -c 'import os, sys; t, m = sys.argv[1], tuple(map(int, sys.argv[2].split("."))); sys.exit(0 if sys.version_info[:2] >= m and os.access(t, os.R_OK) else 1)' \
        "$SYNAPSE_TARGET" "$MIN" >/dev/null 2>&1
}

SYNAPSE_TARGET="${1:-}"
for cmd in "python3" "python" "py -3" \
           "python3.14" "python3.13" "python3.12" "python3.11" \
           "python3.15" "python3.16" "python3.17" "python3.18" "python3.19"; do
    # shellcheck disable=SC2086
    command -v ${cmd%% *} >/dev/null 2>&1 || continue
    # shellcheck disable=SC2086
    if ok $cmd; then
        # shellcheck disable=SC2086
        exec $cmd "$@"
    fi
done

# Optional hooks (recall hints, reminders) must never surface an error.
[ -n "${SYNAPSE_OPTIONAL:-}" ] && exit 0
echo "synapse: no Python $MIN+ found (tried python3, python, py -3, python3.11-3.19)." >&2
echo "  macOS: brew install python   Windows: install from https://python.org (not the Microsoft Store)" >&2
exit 1
