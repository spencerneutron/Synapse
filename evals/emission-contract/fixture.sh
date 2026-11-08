#!/usr/bin/env bash
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
cat > text.py <<'PY'
import re


def slugify(title):
    """URL slug: lowercase words joined by single hyphens."""
    return re.sub(r"[^a-z0-9]", "-", title.lower())
PY
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "slugify"
