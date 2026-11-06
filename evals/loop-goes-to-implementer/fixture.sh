#!/usr/bin/env bash
# A pipeline over three input files (orders, discounts, shipping) that stops
# at its first error and writes the traceback to build.log; the test prints
# only "see build.log". Three bugs, each repeated in all three modules under
# orders/, and each shows up only after the one before it is fixed, so getting
# to green takes about three run-test, read-log, fix rounds (the loop the 2.5.0
# rule hands to synapse:implementer). By hand that is nine one-line Edits:
#   round 1: load() in orders.py, discounts.py, shipping.py uses delimiter ","
#            but the data files use ";"
#   round 2: parse() in the same three files calls Decimal() on a decimal
#            comma ("12,50")
#   round 3: the float constants TAX (orders.py), STACK (discounts.py) and
#            FUEL (shipping.py) are mixed with Decimal and raise TypeError
# Expected last line: "total: 85.89".
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
printf 'sku;pct\nA1;10,0\nC3;5,0\n' > data/discounts.csv
printf 'region;fee\neu;4,00\nus;6,50\n' > data/shipping.csv
: > orders/__init__.py
cat > orders/orders.py <<'EOT'
"""Order lines: read, parse, and price with regional tax."""
import csv
from decimal import Decimal

TAX = {"eu": 0.20, "us": 0.10}


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=","))


def parse(rows):
    return [
        {
            "sku": r["sku"],
            "qty": int(r["qty"]),
            "price": Decimal(r["price"]),
            "region": r["region"],
        }
        for r in rows
    ]


def net_total(rows, rates):
    out = Decimal("0")
    for r in rows:
        out += r["qty"] * r["price"] * (1 - rates[r["sku"]]) * (1 + TAX[r["region"]])
    return out
EOT
cat > orders/discounts.py <<'EOT'
"""Per-sku discounts, given as a percentage."""
import csv
from decimal import Decimal

STACK = 1.0  # share of the listed discount that applies


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=","))


def parse(rows):
    return {r["sku"]: Decimal(r["pct"]) / 100 for r in rows}


def rate(sku, table):
    return table.get(sku, Decimal("0")) * STACK
EOT
cat > orders/shipping.py <<'EOT'
"""Flat shipping fee per region."""
import csv
from decimal import Decimal

FUEL = 1.0  # fuel-cost multiplier


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=","))


def parse(rows):
    return {r["region"]: Decimal(r["fee"]) for r in rows}


def fee_for(region, fees):
    return fees[region] * FUEL
EOT
cat > run.py <<'EOT'
"""Run the pipeline. On failure, write the traceback to build.log."""
import os
import sys
import traceback
from decimal import Decimal

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from orders import discounts, orders, shipping  # noqa: E402


def data(name):
    return os.path.join(ROOT, "data", name)


def main():
    raw = (orders.load(data("orders.csv")),
           discounts.load(data("discounts.csv")),
           shipping.load(data("shipping.csv")))
    rows = orders.parse(raw[0])
    table = discounts.parse(raw[1])
    fees = shipping.parse(raw[2])
    rates = {r["sku"]: discounts.rate(r["sku"], table) for r in rows}
    fee = sum(shipping.fee_for(g, fees) for g in sorted({r["region"] for r in rows}))
    return (orders.net_total(rows, rates) + fee).quantize(Decimal("0.01"))


try:
    result = main()
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
        self.assertEqual(p.stdout.strip(), "total: 85.89")
EOT
printf 'build.log\n__pycache__/\n' > .gitignore
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "ordersum: pipeline and test"
python3 -B -m unittest >/dev/null 2>&1 || true
