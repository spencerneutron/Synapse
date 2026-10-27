#!/usr/bin/env bash
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
cat > app.py <<'PY'
def greet(name):
    return f"Helo, {name}!"
PY
cat > utils.py <<'PY'
def add(a,b): return a+b  # TODO tidy
PY
printf 'Call greet() to recieve a greeting.\n' > README.md
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "app"
