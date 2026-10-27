#!/usr/bin/env bash
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
mkdir -p lib
printf 'x = 1  # TODO rename x\n\ny = 2  # TODO validate y\n' > a.py
printf 'def b():\n    # TODO log failures\n    return 1\n' > b.py
printf '# TODO split module\nA = 1\n# TODO drop A\n\n# TODO add tests\n' > lib/c.py
printf 'Release notes\nTODO write the summary\n' > notes.txt
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "todos"
