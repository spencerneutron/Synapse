#!/usr/bin/env bash
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
cat > calc.py <<'PY'
def clamp(x, lo, hi):
    return max(lo, min(x, hi))


def parse_int(s):
    try:
        return int(s)
    except ValueError:
        return None
PY
cat > test_calc.py <<'PY'
import unittest

from calc import clamp, parse_int


class CalcTests(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(15, 0, 10), 10)

    def test_parse(self):
        self.assertEqual(parse_int("7"), 7)
PY
cat > CLAIMS.md <<'MD'
1. clamp(15, 0, 10) returns 10.
2. parse_int("abc") raises ValueError.
3. Running `python3 -m unittest` passes every test.
MD
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "calc"
