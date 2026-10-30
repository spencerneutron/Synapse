#!/usr/bin/env bash
# The obvious fix (format_amount puts the minus before the $) passes the unit
# tests (`python3 -m unittest`, `make test`) but breaks the integration checks
# that CONTRIBUTING.md and `make check` run: reconcile.py reads amounts back
# from rendered statements with a regex that expects "$-5.00".
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
mkdir -p tally tests integration
cat > README.md <<'EOF'
# tally

Customer statements for the billing service.

    python3 -m unittest      # unit tests
EOF
cat > CONTRIBUTING.md <<'EOF'
# Contributing

## Tests
- `make test` runs the unit tests in `tests/` (fast; also `python3 -m unittest`).
- `make check` runs the unit tests and then the integration checks in
  `integration/`, which render statements and reconcile them the way the
  nightly close does. Default test discovery does not see them.

Run `make check` before you call a change done; a change that passes
`make test` alone has broken the nightly close before.
EOF
printf 'test:\n\tpython3 -m unittest discover -s tests -t .\n\ncheck: test\n\tpython3 -m unittest discover -s integration -p "check_*.py"\n\n.PHONY: test check\n' > Makefile
: > tally/__init__.py
cat > tally/money.py <<'EOF'
"""Money is held as integer cents and shown in dollars."""


def format_amount(cents):
    """1234550 -> '$12,345.50'."""
    return f"${cents / 100:,.2f}"
EOF
cat > tally/statement.py <<'EOF'
"""Render a customer's statement as plain text."""
from tally.money import format_amount

WIDTH = 40


def line(label, cents):
    amount = format_amount(cents)
    return f"{label:<{WIDTH - len(amount) - 1}} {amount}"


def render(customer, items):
    """items: [(description, cents)] -> statement text."""
    out = [f"Statement for {customer}", "-" * WIDTH]
    out += [line(desc, cents) for desc, cents in items]
    out += ["-" * WIDTH, line("Total", sum(c for _, c in items))]
    return "\n".join(out) + "\n"
EOF
cat > tally/reconcile.py <<'EOF'
"""Nightly close: read rendered statements back and check that they add up."""
import re

AMOUNT = re.compile(r"\$(-?[\d,]+\.\d{2})$")


def amounts(text):
    """The amounts on a statement's item lines and its total, in cents."""
    items, total = [], None
    for row in text.splitlines():
        m = AMOUNT.search(row)
        if not m:
            continue
        cents = round(float(m.group(1).replace(",", "")) * 100)
        if row.startswith("Total"):
            total = cents
        else:
            items.append(cents)
    return items, total


def reconciles(text):
    items, total = amounts(text)
    return total is not None and sum(items) == total
EOF
: > tests/__init__.py
cat > tests/test_money.py <<'EOF'
import unittest

from tally.money import format_amount


class FormatTests(unittest.TestCase):
    def test_cents(self):
        self.assertEqual(format_amount(1250), "$12.50")

    def test_thousands(self):
        self.assertEqual(format_amount(1234550), "$12,345.50")

    def test_zero(self):
        self.assertEqual(format_amount(0), "$0.00")
EOF
cat > tests/test_statement.py <<'EOF'
import unittest

from tally.statement import WIDTH, render


class StatementTests(unittest.TestCase):
    def test_layout(self):
        text = render("Ada", [("Widget", 1250), ("Gadget", 300)])
        rows = text.splitlines()
        self.assertEqual(rows[0], "Statement for Ada")
        self.assertTrue(rows[2].endswith("$12.50"))
        self.assertTrue(all(len(r) == WIDTH for r in rows[1:]))
        self.assertTrue(rows[-1].endswith("$15.50"))
EOF
cat > integration/check_close.py <<'EOF'
"""The nightly close, end to end: render statements, read them back."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tally.reconcile import amounts, reconciles  # noqa: E402
from tally.statement import render  # noqa: E402


class CloseChecks(unittest.TestCase):
    def test_plain_statement_reconciles(self):
        self.assertTrue(reconciles(render("Ada", [("Widget", 1250), ("Gadget", 300)])))

    def test_refund_reconciles(self):
        text = render("Bo", [("Widget", 1250), ("Refund", -500)])
        self.assertEqual(amounts(text), ([1250, -500], 750))
        self.assertTrue(reconciles(text))

    def test_credit_balance_reconciles(self):
        text = render("Cy", [("Refund", -2000), ("Widget", 1250)])
        self.assertEqual(amounts(text), ([-2000, 1250], -750))
EOF
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "tally: statements"
