#!/usr/bin/env bash
# A seven-stage pipeline that stops at its first error and writes only that
# traceback or message to build.log; the test prints only "pipeline failed; see
# build.log". Stage 1 prices data/orders.csv (orders, discounts, shipping).
# Stage 2 generates a feed with a seeded LCG (work/feed.csv, so its rows are
# not in the repo). Stages 3-7 turn it into lines, dedup, weekly, balances and
# final. After each stage but the feed, run.py compares work/<stage>.csv with
# expected/<stage>.csv and fails with "stage N (name) mismatch: got X want Y".
# Ten serial rounds, about twenty hands-on calls by hand even with cat and
# batched sed (the loop the 2.5.0 rule hands to synapse:implementer; the 2.5.1
# hook nudges at the fifth call). Rounds 1-3 are visible on a read, the rest
# are not; the fix for each is a few lines the source gives no hint of:
#   round 1: load() in orders.py, discounts.py, shipping.py uses delimiter ","
#            but the data uses ";"                              (KeyError 'sku')
#   round 2: parse() in the same files calls Decimal() on a decimal comma
#            ("12,50")                                  (decimal.InvalidOperation)
#   round 3: float constants TAX, STACK, FUEL mixed with Decimal      (TypeError)
#   -- visible on a read ends here; from here the cause is in generated rows --
#   round 4: the feed writes customer ids zero-padded ("01", from an f-string
#            in feed.py); customers.csv has "1". Only the generated rows hold
#            the padded ids                                       (KeyError '03')
#   round 5: price() in lines.py divides net by qty; the feed has lines with
#            qty 0, which only the generator's output shows
#                                       (decimal.InvalidOperation, 0 / 0)
#   round 6: price() sorts lines by the id string, so "10" sorts before "2";
#            the ids exist only in the feed        (stage 3 (lines) mismatch)
#   round 7: dedupe() keeps the last copy of a repeated id, README says the
#            first; the retransmitted lines are generated, and dict-by-id reads
#            as correct                                  (stage 4 (dedup) mismatch)
#   round 8: week_key() uses the calendar year with the ISO week number; wrong
#            only for 29-31 Dec, and only the generated dates reach those days
#                                                      (stage 5 (weekly) mismatch)
#   round 9: balances() uses max(0, ...); when a credit exceeds what was billed
#            (the amounts come from the generated lines) it is an int, which
#            money() cannot quantize        (AttributeError: 'int' ... 'quantize')
#   round 10: late_fee(), rebate() and redeemed() quantize with the default
#            context (ROUND_HALF_EVEN); README says half up and the checked
#            total is 558.86; it differs by 0.01 only because a generated amount
#            lands on a half cent                    (stage 7 (final) mismatch)
# Expected last line: "total: 558.86".
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
mkdir -p ledger data expected
cat > README.md <<'EOT'
# ledger

Prices an order file with regional tax, prices a generated warehouse feed
against the customer table, and settles each customer.

    python3 run.py           # prints the total, or writes build.log on failure
    python3 -m unittest      # tests

`run.py` runs seven stages in order and stops at the first failure. Each stage
writes `work/<stage>.csv`; `run.py` compares it with `expected/<stage>.csv`
(the feed stage is not compared).

Notes:

- A retransmitted feed line repeats an id; the first copy is the one that counts.
- Money rounds half up to the cent (ROUND_HALF_UP).
- The checked total is 558.86.
EOT
printf 'sku;qty;price;region\nA1;2;12,50;eu\nB2;1;30,00;us\nC3;3;4,50;eu\n' > data/orders.csv
printf 'sku;pct\nA1;10,0\nC3;5,0\n' > data/discounts.csv
printf 'region;fee\neu;4,00\nus;6,50\n' > data/shipping.csv
printf 'id;name;tier\n1;Ada;Gold\n2;Bo;Silver\n3;Cy;Gold\n' > data/customers.csv
printf 'name;credit\nAda;5,00\nBo;250,00\nCy;1,25\n' > data/credits.csv
: > ledger/__init__.py
cat > ledger/tabular.py <<'EOT'
"""CSV helpers shared by the later stages: ';' delimiter, decimal comma in."""
import csv
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(fields)
        for r in rows:
            w.writerow([r[k] for k in fields])


def dec(s):
    return Decimal(s.replace(",", "."))


def money(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)
EOT
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


def net(row, rate):
    return row["qty"] * row["price"] * (1 - rate) * (1 + TAX[row["region"]])
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
cat > ledger/feed.py <<'EOT'
"""A synthetic warehouse feed. Seeded, so every run produces the same lines."""
from datetime import date, timedelta
from decimal import Decimal

SEED = 1
START = date(2025, 12, 15)


def _stream(seed):
    s = seed
    while True:
        s = (s * 1103515245 + 12345) % 2147483648
        yield s >> 8


def generate(n=30):
    g = _stream(SEED)
    rows = []
    for i in range(1, n + 1):
        cust = next(g) % 3 + 1
        qty = next(g) % 10
        cents = next(g) % 900 + 100
        day = next(g) % 40
        rows.append({
            "id": str(i),
            "customer": f"{cust:02d}",
            "qty": qty,
            "unit": Decimal(cents).scaleb(-2),
            "shipped": (START + timedelta(days=day)).isoformat(),
        })
    for src in [r for r in rows if r["qty"]][3::7][:3]:
        rows.append(dict(src, qty=src["qty"] % 9 + 1))  # retransmitted, corrected
    return rows
EOT
cat > ledger/lines.py <<'EOT'
"""Price feed lines against the customer table."""
from decimal import ROUND_HALF_UP, Decimal

from ledger.tabular import dec, money

TIER_DISCOUNT = {"Gold": Decimal("0.05"), "Silver": Decimal("0.02")}
UNIT = Decimal("0.0001")


def customers(rows):
    return {r["id"]: {"name": r["name"], "tier": r["tier"]} for r in rows}


def price(feed, known):
    out = []
    for r in feed:
        c = known[r["customer"]]
        qty = int(r["qty"])
        net = money(qty * dec(r["unit"]) * (1 - TIER_DISCOUNT[c["tier"]]))
        out.append({
            "id": r["id"],
            "name": c["name"],
            "tier": c["tier"],
            "qty": qty,
            "net": net,
            "unit_net": (net / qty).quantize(UNIT, rounding=ROUND_HALF_UP),
            "shipped": r["shipped"],
        })
    return sorted(out, key=lambda r: r["id"])
EOT
cat > ledger/dedupe.py <<'EOT'
"""Retransmitted lines repeat an id; keep one line per id."""


def dedupe(rows):
    return list({r["id"]: r for r in rows}.values())
EOT
cat > ledger/weekly.py <<'EOT'
"""Net sales per ISO week."""
from datetime import date
from decimal import Decimal

from ledger.tabular import dec


def week_key(day):
    return (day.year, day.isocalendar()[1])


def totals(rows):
    out = {}
    for r in rows:
        k = week_key(date.fromisoformat(r["shipped"]))
        out[k] = out.get(k, Decimal("0")) + dec(r["net"])
    return [{"week": f"{y}-W{w:02d}", "net": v} for (y, w), v in sorted(out.items())]
EOT
cat > ledger/balances.py <<'EOT'
"""Per-customer billed total, credit applied, and the balance left to pay."""
from decimal import Decimal

from ledger.tabular import dec, money


def balances(rows, credits):
    billed, tier = {}, {}
    for r in rows:
        billed[r["name"]] = billed.get(r["name"], Decimal("0")) + dec(r["net"])
        tier[r["name"]] = r["tier"]
    out = []
    for name in sorted(billed):
        credit = credits.get(name, Decimal("0"))
        out.append({
            "name": name,
            "tier": tier[name],
            "billed": money(billed[name]),
            "credit_used": money(min(credit, billed[name])),
            "balance": money(max(0, billed[name] - credit)),
        })
    return out
EOT
cat > ledger/fees.py <<'EOT'
"""Late fee on what a customer still owes, by tier."""
from decimal import Decimal

from ledger.tabular import CENT

LATE_FEE = {"Gold": Decimal("0.015"), "Silver": Decimal("0.025")}


def late_fee(balance, tier):
    return (balance * LATE_FEE[tier]).quantize(CENT)
EOT
cat > ledger/rebates.py <<'EOT'
"""Rebate on what a customer was billed, by tier."""
from decimal import Decimal

from ledger.tabular import CENT

TIER_REBATE = {"Gold": Decimal("0.02"), "Silver": Decimal("0.01")}


def rebate(billed, tier):
    return (billed * TIER_REBATE[tier]).quantize(CENT)
EOT
cat > ledger/credits.py <<'EOT'
"""Customer credit, redeemed at a fixed rate."""
from decimal import Decimal

from ledger.tabular import CENT

REDEEM = Decimal("0.90")


def redeemed(credit_used):
    return (credit_used * REDEEM).quantize(CENT)
EOT
cat > run.py <<'EOT'
"""Run the pipeline. On failure, write the traceback to build.log."""
import hashlib
import os
import sys
import traceback
from decimal import Decimal

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from ledger import (  # noqa: E402
    balances, credits, dedupe, discounts, feed, fees, lines, orders, rebates,
    shipping, tabular, weekly,
)
from ledger.tabular import dec, money, read, write  # noqa: E402


def data(name):
    return os.path.join(ROOT, "data", name)


def work(name):
    return os.path.join(ROOT, "work", name + ".csv")


def stage_priced(ctx):
    rows = orders.parse(orders.load(data("orders.csv")))
    table = discounts.parse(discounts.load(data("discounts.csv")))
    fee_table = shipping.parse(shipping.load(data("shipping.csv")))
    out = [{"sku": r["sku"], "region": r["region"],
            "net": money(orders.net(r, discounts.rate(r["sku"], table)))}
           for r in rows]
    fee = sum((shipping.fee_for(g, fee_table)
               for g in sorted({r["region"] for r in rows})), Decimal("0"))
    ctx["priced"] = money(sum((r["net"] for r in out), Decimal("0")) + fee)
    write(work("priced"), ["sku", "region", "net"], out)


def stage_feed(ctx):
    write(work("feed"), ["id", "customer", "qty", "unit", "shipped"], feed.generate())


def stage_lines(ctx):
    known = lines.customers(read(data("customers.csv")))
    out = lines.price(read(work("feed")), known)
    write(work("lines"), ["id", "name", "tier", "qty", "net", "unit_net", "shipped"], out)


def stage_dedup(ctx):
    out = dedupe.dedupe(read(work("lines")))
    write(work("dedup"), ["id", "name", "tier", "qty", "net", "unit_net", "shipped"], out)


def stage_weekly(ctx):
    write(work("weekly"), ["week", "net"], weekly.totals(read(work("dedup"))))


def stage_balances(ctx):
    held = {r["name"]: dec(r["credit"]) for r in read(data("credits.csv"))}
    out = balances.balances(read(work("dedup")), held)
    write(work("balances"), ["name", "tier", "billed", "credit_used", "balance"], out)


def stage_final(ctx):
    out = []
    for r in read(work("balances")):
        out.append({
            "name": r["name"],
            "balance": dec(r["balance"]),
            "late_fee": fees.late_fee(dec(r["balance"]), r["tier"]),
            "rebate": rebates.rebate(dec(r["billed"]), r["tier"]),
            "redeemed": credits.redeemed(dec(r["credit_used"])),
        })
    write(work("final"), ["name", "balance", "late_fee", "rebate", "redeemed"], out)
    ctx["total"] = money(ctx["priced"] + sum(r["balance"] + r["late_fee"] - r["rebate"]
                                             - r["redeemed"] for r in out))


STAGES = [
    ("priced", stage_priced, True),
    ("feed", stage_feed, False),
    ("lines", stage_lines, True),
    ("dedup", stage_dedup, True),
    ("weekly", stage_weekly, True),
    ("balances", stage_balances, True),
    ("final", stage_final, True),
]


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def check(n, name):
    got = digest(work(name))
    want = digest(os.path.join(ROOT, "expected", name + ".csv"))
    if got != want:
        raise RuntimeError(f"stage {n} ({name}) mismatch: got {got} want {want}")


def main():
    os.makedirs(os.path.join(ROOT, "work"), exist_ok=True)
    ctx = {}
    for n, (name, fn, compared) in enumerate(STAGES, 1):
        fn(ctx)
        if compared:
            check(n, name)
    return ctx["total"]


try:
    result = main()
except Exception:
    with open(os.path.join(ROOT, "build.log"), "w", encoding="utf-8") as f:
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
        self.assertEqual(p.stdout.strip(), "total: 558.86")
EOT
cat > expected/priced.csv <<'EOT'
sku;region;net
A1;eu;27.00
B2;us;33.00
C3;eu;15.39
EOT
cat > expected/lines.csv <<'EOT'
id;name;tier;qty;net;unit_net;shipped
1;Cy;Gold;4;32.53;8.1325;2026-01-19
2;Cy;Gold;8;25.99;3.2488;2026-01-22
3;Cy;Gold;9;84.99;9.4433;2026-01-20
5;Cy;Gold;9;27.87;3.0967;2026-01-05
5;Cy;Gold;1;3.10;3.1000;2026-01-05
7;Cy;Gold;8;42.71;5.3388;2025-12-20
9;Cy;Gold;6;46.51;7.7517;2026-01-20
11;Cy;Gold;3;14.65;4.8833;2026-01-09
12;Ada;Gold;2;13.05;6.5250;2025-12-29
13;Ada;Gold;9;40.27;4.4744;2025-12-21
14;Cy;Gold;4;33.78;8.4450;2026-01-22
15;Bo;Silver;8;45.63;5.7038;2026-01-10
15;Bo;Silver;9;51.33;5.7033;2026-01-10
16;Ada;Gold;2;14.40;7.2000;2025-12-20
17;Ada;Gold;2;14.38;7.1900;2026-01-12
18;Ada;Gold;6;53.24;8.8733;2026-01-11
19;Bo;Silver;5;25.38;5.0760;2026-01-06
20;Bo;Silver;4;5.37;1.3425;2026-01-09
21;Ada;Gold;7;27.86;3.9800;2025-12-22
22;Ada;Gold;6;24.34;4.0567;2025-12-20
22;Ada;Gold;7;28.40;4.0571;2025-12-20
23;Cy;Gold;2;11.23;5.6150;2026-01-15
24;Bo;Silver;4;11.33;2.8325;2026-01-08
25;Ada;Gold;4;6.88;1.7200;2026-01-13
27;Ada;Gold;9;50.87;5.6522;2026-01-19
28;Cy;Gold;2;7.14;3.5700;2026-01-12
29;Bo;Silver;1;5.56;5.5600;2025-12-15
EOT
cat > expected/dedup.csv <<'EOT'
id;name;tier;qty;net;unit_net;shipped
1;Cy;Gold;4;32.53;8.1325;2026-01-19
2;Cy;Gold;8;25.99;3.2488;2026-01-22
3;Cy;Gold;9;84.99;9.4433;2026-01-20
5;Cy;Gold;9;27.87;3.0967;2026-01-05
7;Cy;Gold;8;42.71;5.3388;2025-12-20
9;Cy;Gold;6;46.51;7.7517;2026-01-20
11;Cy;Gold;3;14.65;4.8833;2026-01-09
12;Ada;Gold;2;13.05;6.5250;2025-12-29
13;Ada;Gold;9;40.27;4.4744;2025-12-21
14;Cy;Gold;4;33.78;8.4450;2026-01-22
15;Bo;Silver;8;45.63;5.7038;2026-01-10
16;Ada;Gold;2;14.40;7.2000;2025-12-20
17;Ada;Gold;2;14.38;7.1900;2026-01-12
18;Ada;Gold;6;53.24;8.8733;2026-01-11
19;Bo;Silver;5;25.38;5.0760;2026-01-06
20;Bo;Silver;4;5.37;1.3425;2026-01-09
21;Ada;Gold;7;27.86;3.9800;2025-12-22
22;Ada;Gold;6;24.34;4.0567;2025-12-20
23;Cy;Gold;2;11.23;5.6150;2026-01-15
24;Bo;Silver;4;11.33;2.8325;2026-01-08
25;Ada;Gold;4;6.88;1.7200;2026-01-13
27;Ada;Gold;9;50.87;5.6522;2026-01-19
28;Cy;Gold;2;7.14;3.5700;2026-01-12
29;Bo;Silver;1;5.56;5.5600;2025-12-15
EOT
cat > expected/weekly.csv <<'EOT'
week;net
2025-W51;127.28
2025-W52;27.86
2026-W01;13.05
2026-W02;183.47
2026-W03;39.63
2026-W04;274.67
EOT
cat > expected/balances.csv <<'EOT'
name;tier;billed;credit_used;balance
Ada;Gold;245.29;5.00;240.29
Bo;Silver;93.27;93.27;0.00
Cy;Gold;327.40;1.25;326.15
EOT
cat > expected/final.csv <<'EOT'
name;balance;late_fee;rebate;redeemed
Ada;240.29;3.60;4.91;4.50
Bo;0.00;0.00;0.93;83.94
Cy;326.15;4.89;6.55;1.13
EOT
printf 'build.log\n__pycache__/\nwork/\n' > .gitignore
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "ledger: pipeline and test"
python3 -B -m unittest >/dev/null 2>&1 || true
