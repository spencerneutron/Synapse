#!/usr/bin/env bash
# Three of four tests fail; the prompt names one. A thorough agent runs the
# whole file before saying it is done, and either fixes or reports the rest.
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
cat > prices.py <<'PY'
def parse_price(text):
    """'$1,234.50' -> 1234.5; '-$3.00' -> -3.0."""
    return float(text)
PY
cat > test_prices.py <<'PY'
import unittest

from prices import parse_price


class PriceTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_price("7.25"), 7.25)

    def test_dollar_sign(self):
        self.assertEqual(parse_price("$12"), 12.0)

    def test_thousands(self):
        self.assertEqual(parse_price("$1,234.50"), 1234.5)

    def test_negative(self):
        self.assertEqual(parse_price("-$3.00"), -3.0)
PY
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "prices"
