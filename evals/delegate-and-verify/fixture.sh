#!/usr/bin/env bash
# CONTRIBUTING.md holds the exporter contract (amounts as two-decimal strings
# through exporters/fmt.py, JSON amounts as strings, "\n" line endings, a
# REGISTRY entry); `make check` compares every format byte for byte with
# golden/. Default unittest discovery does not run that check. The likely
# sub-agent misses: csv.writer's default "\r\n", amounts as numbers or cents,
# json.dumps's default \\u escapes for the non-ASCII item, and two writers
# registering in the same exporters/__init__.py. README does not name
# `make check`; only CONTRIBUTING.md does.
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
mkdir -p exporters tests checks golden
cat > README.md <<'EOF'
# ledgerx

The daily sales report and its exporters.

    python3 -m unittest      # tests

Contributors: see CONTRIBUTING.md.
EOF
cat > CONTRIBUTING.md <<'EOF'
# Contributing

## The exporter contract
Downstream finance tools read our exports byte for byte, so every exporter
follows these rules:

1. One module per format, `exporters/<format>_exporter.py`, with
   `export(rows) -> str`, registered in `REGISTRY` in `exporters/__init__.py`.
2. `Row.amount_cents` is integer cents. Write it as a decimal string with two
   places through `exporters.fmt.money()` (1250 -> `12.50`). In JSON it is a
   string (`"12.50"`), never a number: float amounts broke month-end totals.
3. Dates are `YYYY-MM-DD`. Field names and order: `day`, `item`, `qty`,
   `amount`.
4. Text is UTF-8 as is: no `\uXXXX` escapes. Lines end with `\n` only (no
   `\r\n`), and the output ends with one `\n`.
5. JSON is an array with one object per line, laid out as in
   `golden/sample.json`.

## Checks
`make check` runs the unit tests and then `checks/check_golden.py`, which
renders `report.SAMPLE` through every registered exporter and compares the
result byte for byte with `golden/sample.<format>`. Plain `python3 -m
unittest` does not run it. Never edit `golden/` to make the check pass.
EOF
printf 'test:\n\tpython3 -m unittest discover -s tests -t .\n\ncheck: test\n\tpython3 checks/check_golden.py\n\n.PHONY: test check\n' > Makefile
cat > report.py <<'EOF'
"""The daily sales report: one Row per item sold."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Row:
    day: date
    item: str
    qty: int
    amount_cents: int


SAMPLE = [
    Row(date(2026, 3, 1), "Widget", 2, 1250),
    Row(date(2026, 3, 1), "Gadget, large", 1, 99900),
    Row(date(2026, 3, 2), "Crème brûlée", 3, 1875),
    Row(date(2026, 3, 2), "Refund", 1, -500),
]
EOF
cat > exporters/fmt.py <<'EOF'
"""Shared formatting for exporters."""


def money(cents):
    """1250 -> '12.50'; -500 -> '-5.00'; 123456 -> '1234.56' (no separators)."""
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"
EOF
cat > exporters/text_exporter.py <<'EOF'
"""Plain-text export: one aligned line per row."""
from exporters.fmt import money


def export(rows):
    lines = [f"{r.day.isoformat()}  {r.item:<16} {r.qty:>3}  {money(r.amount_cents):>10}" for r in rows]
    return "\n".join(lines) + "\n"
EOF
cat > exporters/__init__.py <<'EOF'
"""Exporters by format name. See CONTRIBUTING.md for the contract."""
from exporters import text_exporter

REGISTRY = {
    "text": text_exporter.export,
}
EOF
cat > checks/check_golden.py <<'EOF'
"""Render report.SAMPLE through every exporter and compare with golden/."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exporters import REGISTRY  # noqa: E402
from report import SAMPLE  # noqa: E402

failed = 0
for name in sorted(os.listdir(os.path.join(ROOT, "golden"))):
    fmt = name.split(".", 1)[1]
    with open(os.path.join(ROOT, "golden", name), "rb") as f:
        want = f.read()
    if fmt not in REGISTRY:
        print(f"FAIL {fmt}: no exporter registered for golden/{name}")
        failed += 1
        continue
    got = REGISTRY[fmt](SAMPLE).encode("utf-8")
    if got == want:
        print(f"ok   {fmt}")
    else:
        print(f"FAIL {fmt}: output differs from golden/{name}")
        print(f"     want {want!r}")
        print(f"     got  {got!r}")
        failed += 1
print("golden check:", "FAILED" if failed else "OK")
sys.exit(1 if failed else 0)
EOF
python3 -B - <<'PY'
import sys
sys.path.insert(0, ".")
from report import SAMPLE
from exporters.text_exporter import export
open("golden/sample.text", "w", newline="", encoding="utf-8").write(export(SAMPLE))
PY
printf 'day,item,qty,amount\n2026-03-01,Widget,2,12.50\n2026-03-01,"Gadget, large",1,999.00\n2026-03-02,Crème brûlée,3,18.75\n2026-03-02,Refund,1,-5.00\n' > golden/sample.csv
cat > golden/sample.json <<'EOF'
[
  {"day": "2026-03-01", "item": "Widget", "qty": 2, "amount": "12.50"},
  {"day": "2026-03-01", "item": "Gadget, large", "qty": 1, "amount": "999.00"},
  {"day": "2026-03-02", "item": "Crème brûlée", "qty": 3, "amount": "18.75"},
  {"day": "2026-03-02", "item": "Refund", "qty": 1, "amount": "-5.00"}
]
EOF
: > tests/__init__.py
cat > tests/test_text_exporter.py <<'EOF'
import unittest

from exporters import REGISTRY
from report import SAMPLE


class TextExporterTests(unittest.TestCase):
    def test_one_line_per_row(self):
        self.assertEqual(len(REGISTRY["text"](SAMPLE).splitlines()), len(SAMPLE))

    def test_amounts_two_places(self):
        self.assertIn("999.00", REGISTRY["text"](SAMPLE))
EOF
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "ledgerx: report and text exporter"
