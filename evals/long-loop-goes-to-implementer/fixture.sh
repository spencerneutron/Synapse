#!/usr/bin/env bash
# A two-stage pipeline that stops at its first error and writes the traceback
# to build.log; the test prints only "see build.log". Stage 1 prices orders
# (orders, discounts, shipping under ledger/). Stage 2 reads invoices,
# customers and credits (same package), joins them, and settles. Nine bugs,
# each repeated in two or three modules and each shown only after the one
# before it is fixed (later ones live in code that runs only after the earlier
# stages succeed), so getting to green takes nine run-test, read-log, fix
# rounds, about twenty hands-on calls by hand (the loop the 2.5.0 rule hands to
# synapse:implementer; the 2.5.1 hook nudges at the fifth call):
#   round 1: load() in orders.py, discounts.py, shipping.py uses delimiter ","
#            but the data files use ";"                       (KeyError 'sku')
#   round 2: parse() in the same three files calls Decimal() on a decimal
#            comma ("12,50")                          (decimal.InvalidOperation)
#   round 3: the float constants TAX (orders.py), STACK (discounts.py) and FUEL
#            (shipping.py) are mixed with Decimal                    (TypeError)
#   round 4: customers.csv, invoices.csv and credits.csv start with a UTF-8
#            BOM; load() in customers.py, invoices.py, credits.py opens them
#            as plain utf-8, so the first header carries an invisible BOM
#                                  (KeyError: 'customer_id', BOM unprinted)
#   round 5: wrong column names: customers.py reads "tier" (column is
#            "segment"), invoices.py reads "cust" (column is "customer_id"),
#            credits.py reads "amount" (column is "credit")     (KeyError 'tier')
#   round 6: iso() in invoices.py and credits.py slices the date at [7:9]
#            instead of [8:10]                      (ValueError: day -1 must be in range)
#   round 7: customers.py and credits.py key by int(customer_id) while
#            invoices.py keeps the id as str, so the join misses  (KeyError '1')
#   round 8: LATE_FEE (invoices.py) and TIER_REBATE (report.py) are keyed
#            "gold"/"silver"; the data says "Gold"/"Silver"     (KeyError 'Gold')
#   round 9: late_fee() (invoices.py), rebate() (report.py) and apply()
#            (credits.py) quantize with ROUND_HALF_EVEN; the expected total
#            uses ROUND_HALF_UP (no error: the test shows total: 80.81 not 80.80)
# Expected last line: "total: 80.80".
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
mkdir -p ledger data
cat > README.md <<'EOT'
# ledger

Prices an order file with regional tax, then settles invoices against
customer credits.

    python3 run.py           # prints the total, or writes build.log on failure
    python3 -m unittest      # tests
EOT
BOM='\357\273\277'
printf 'sku;qty;price;region\nA1;2;12,50;eu\nB2;1;30,00;us\nC3;3;4,50;eu\n' > data/orders.csv
printf 'sku;pct\nA1;10,0\nC3;5,0\n' > data/discounts.csv
printf 'region;fee\neu;4,00\nus;6,50\n' > data/shipping.csv
printf "${BOM}customer_id;name;segment\n1;Ada;Gold\n2;Bo;Silver\n3;Cy;Gold\n" > data/customers.csv
printf "${BOM}invoice_id;customer_id;due;amount\n101;1;2024-03-15;40.00\n102;2;2024-04-02;22.50\n103;3;2024-02-28;11.00\n" > data/invoices.csv
printf "${BOM}customer_id;credit;expires\n1;5.00;2024-12-31\n3;1.25;2025-01-31\n" > data/credits.csv
: > ledger/__init__.py
cat > ledger/orders.py <<'EOT'
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
cat > ledger/discounts.py <<'EOT'
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
cat > ledger/shipping.py <<'EOT'
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
cat > ledger/customers.py <<'EOT'
"""Customers and their tier."""
import csv


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def parse(rows):
    return {
        int(r["customer_id"]): {"name": r["name"], "tier": r["tier"]}
        for r in rows
    }
EOT
cat > ledger/invoices.py <<'EOT'
"""Invoices, due dates, and late fees."""
import csv
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

AS_OF = date(2024, 3, 31)
LATE_FEE = {"gold": Decimal("0.015"), "silver": Decimal("0.025")}


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def iso(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[7:9]))


def parse(rows):
    return [
        {
            "id": r["invoice_id"],
            "customer": r["cust"],
            "due": iso(r["due"]),
            "amount": Decimal(r["amount"]),
        }
        for r in rows
    ]


def late_fee(inv, tier):
    if inv["due"] >= AS_OF:
        return Decimal("0")
    return (inv["amount"] * LATE_FEE[tier]).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN)
EOT
cat > ledger/credits.py <<'EOT'
"""Customer credits, redeemed at a fixed rate until they expire."""
import csv
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

AS_OF = date(2024, 3, 31)
REDEEM = Decimal("0.90")


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def iso(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[7:9]))


def parse(rows):
    return {
        int(r["customer_id"]): {
            "credit": Decimal(r["amount"]),
            "expires": iso(r["expires"]),
        }
        for r in rows
    }


def apply(entry):
    if entry["expires"] < AS_OF:
        return Decimal("0")
    return (entry["credit"] * REDEEM).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN)
EOT
cat > ledger/report.py <<'EOT'
"""Join invoices to customers; on-time rebates by tier."""
from decimal import ROUND_HALF_EVEN, Decimal

from ledger.invoices import AS_OF

TIER_REBATE = {"gold": Decimal("0.02"), "silver": Decimal("0.01")}


def attach(invoices, customers):
    return [dict(inv, customer=customers[inv["customer"]]) for inv in invoices]


def rebate(inv, tier):
    if inv["due"] < AS_OF:
        return Decimal("0")
    return (inv["amount"] * TIER_REBATE[tier]).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN)
EOT
cat > run.py <<'EOT'
"""Run the pipeline. On failure, write the traceback to build.log."""
import os
import sys
import traceback
from decimal import Decimal

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from ledger import credits, customers, discounts, invoices, orders, report, shipping  # noqa: E402


def data(name):
    return os.path.join(ROOT, "data", name)


def price_orders():
    raw = (orders.load(data("orders.csv")),
           discounts.load(data("discounts.csv")),
           shipping.load(data("shipping.csv")))
    rows = orders.parse(raw[0])
    table = discounts.parse(raw[1])
    fees = shipping.parse(raw[2])
    rates = {r["sku"]: discounts.rate(r["sku"], table) for r in rows}
    fee = sum(shipping.fee_for(g, fees) for g in sorted({r["region"] for r in rows}))
    return orders.net_total(rows, rates) + fee


def settle():
    cust = customers.parse(customers.load(data("customers.csv")))
    invs = invoices.parse(invoices.load(data("invoices.csv")))
    creds = credits.parse(credits.load(data("credits.csv")))
    joined = report.attach(invs, cust)
    late = sum(invoices.late_fee(i, i["customer"]["tier"]) for i in joined)
    rebates = sum(report.rebate(i, i["customer"]["tier"]) for i in joined)
    redeemed = sum(credits.apply(e) for c, e in sorted(creds.items()) if cust[c])
    return late - rebates - redeemed


def main():
    return (price_orders() + settle()).quantize(Decimal("0.01"))


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
        self.assertEqual(p.stdout.strip(), "total: 80.80")
EOT
printf 'build.log\n__pycache__/\n' > .gitignore
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "ledger: pipeline and test"
python3 -B -m unittest >/dev/null 2>&1 || true
