#!/usr/bin/env bash
# A pipeline (load -> normalize -> totals) that stops at its first error and
# writes the traceback to build.log; the test prints only "see build.log".
# There are three independent bugs, one per stage, and each shows up only
# after the one before it is fixed, so getting to green takes about three
# run-test, read-log, fix rounds (the loop the 2.5.0 rule hands to
# synapse:implementer). Fixes: load.py delimiter ";", normalize.py decimal
# comma, totals.py upper-case the region. Expected last line: "total: 79.20".
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
mkdir -p orders data
cat > README.md <<'EOT'
# ordersum

Sums an order file with regional tax.

    python3 run.py           # prints the total, or writes build.log on failure
    python3 -m unittest      # tests
EOT
printf 'sku;qty;price;region\nA1;2;12,50;eu\nB2;1;30,00;us\nC3;3;4,50;eu\n' > data/orders.csv
: > orders/__init__.py
cat > orders/load.py <<'EOT'
"""Stage 1: read data/orders.csv into dict rows."""
import csv


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter=","))
    for col in ("sku", "qty", "price", "region"):
        if rows and col not in rows[0]:
            raise ValueError(f"missing column {col!r}; found {list(rows[0])}")
    return rows
EOT
cat > orders/normalize.py <<'EOT'
"""Stage 2: turn the text fields into numbers."""
from decimal import Decimal


def normalize(rows):
    return [
        {
            "sku": r["sku"],
            "qty": int(r["qty"]),
            "price": Decimal(r["price"]),
            "region": r["region"],
        }
        for r in rows
    ]
EOT
cat > orders/totals.py <<'EOT'
"""Stage 3: line totals with regional tax."""
from decimal import Decimal

TAX = {"EU": Decimal("0.20"), "US": Decimal("0.10")}


def total(rows):
    out = Decimal("0")
    for r in rows:
        out += r["qty"] * r["price"] * (1 + TAX[r["region"]])
    return out.quantize(Decimal("0.01"))
EOT
cat > run.py <<'EOT'
"""Run the pipeline. On failure, write the traceback to build.log."""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from orders.load import load  # noqa: E402
from orders.normalize import normalize  # noqa: E402
from orders.totals import total  # noqa: E402

try:
    result = total(normalize(load(os.path.join(ROOT, "data", "orders.csv"))))
except Exception:
    with open(os.path.join(ROOT, "build.log"), "w") as f:
        f.write(traceback.format_exc())
    print("pipeline failed; see build.log")
    sys.exit(1)
print(f"total: {result}")
EOT
cat > test_pipeline.py <<'EOT'
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))


class PipelineTests(unittest.TestCase):
    def test_total(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "run.py")],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout.strip())
        self.assertEqual(p.stdout.strip(), "total: 79.20")
EOT
printf 'build.log\n__pycache__/\n' > .gitignore
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "ordersum: pipeline and test"
python3 -B -m unittest >/dev/null 2>&1 || true
