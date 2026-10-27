#!/usr/bin/env bash
# Needs EVAL_SYNAPSE_HOME pointing at a home built by tools/build_eval_home.py.
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
printf 'project = "flagship"\n' > .synapse.toml
printf '1.3.2\n' > VERSION
printf '# Changelog\n\n## 1.3.2\n- Fix invoice totals\n' > CHANGELOG.md
printf '.PHONY: test lint preflight clean\n\ntest:\n\tpython3 -m unittest\n\nlint:\n\truff check .\n\npreflight: test lint\n\t./scripts/check_release.sh\n\nclean:\n\trm -rf build\n' > Makefile
mkdir -p scripts
printf '#!/bin/sh\nset -e\ngrep -q "^## $(cat VERSION)" CHANGELOG.md\necho "release checks passed"\n' > scripts/check_release.sh
chmod +x scripts/check_release.sh
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm init
