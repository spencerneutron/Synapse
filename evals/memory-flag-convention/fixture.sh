#!/usr/bin/env bash
# Needs EVAL_SYNAPSE_HOME pointing at a home built by tools/build_eval_home.py.
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
printf 'project = "flagship"\n' > .synapse.toml
printf '"""Feature flags for the app."""\n\nFLAGS = {}\n' > flags.py
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm init
