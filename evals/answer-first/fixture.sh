#!/usr/bin/env bash
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
cat > cart.py <<'PY'
def total(items):
    """Sum of price * qty over the cart's items."""
    if not items:
        return None
    return sum(i["price"] * i["qty"] for i in items)
PY
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "cart"
