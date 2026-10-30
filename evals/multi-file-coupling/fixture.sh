#!/usr/bin/env bash
# The payload key "total" is read in places a grep for "total" (noisy:
# subtotal, total_weight, totals) or the tests will not flag: a formatter
# found by name (fmt_<key>, silent str() fallback), a template placeholder
# (missing keys render blank), the CSV columns in config/export.ini (missing
# keys export empty), and a string-keyed check map that skips absent keys.
# Two more need more than a rename: the web invoice reads the camelCase wire
# form (shipq/api.py: total_cents -> totalCents), and the free-shipping
# threshold in shipping.py is in dollars. The README example is a doctest
# that the tests run.
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
mkdir -p shipq tests config templates web
cat > README.md <<'EOF'
# shipq

Order payloads for billing, invoices, and the CSV export.

    python3 -m unittest

## Payload

```
>>> from shipq.payload import Order, build_payload
>>> build_payload(Order("A1", "Ada", 1250, 1800, 3))
{'id': 'A1', 'customer': 'Ada', 'total': 12.5, 'total_weight': 1800, 'items': 3}

```

`total` is the order total in dollars; `total_weight` is in grams.
EOF
: > shipq/__init__.py
cat > shipq/payload.py <<'EOF'
"""The order payload: the one dict that billing, invoices, and exports read."""
from dataclasses import dataclass


@dataclass
class Order:
    id: str
    customer: str
    total_cents: int     # internal amounts are always cents
    weight_g: int
    items: int


def build_payload(order):
    return {
        "id": order.id,
        "customer": order.customer,
        "total": round(order.total_cents / 100, 2),
        "total_weight": order.weight_g,
        "items": order.items,
    }
EOF
cat > shipq/formatters.py <<'EOF'
"""Display formatting for payload fields, found by name: fmt_<key>."""


def fmt_total(value):
    return f"${value:,.2f}"


def fmt_total_weight(grams):
    return f"{grams / 1000:.1f} kg"


def fmt_items(n):
    return f"{n} item" + ("" if n == 1 else "s")


def format_field(key, value):
    """Format one payload field; fields without a formatter show as str()."""
    return globals().get(f"fmt_{key}", str)(value)
EOF
cat > templates/invoice.txt <<'EOF'
Invoice {{id}} for {{customer}}
Items:  {{items}}
Weight: {{total_weight}}
Total:  {{total}}
EOF
cat > shipq/render.py <<'EOF'
"""Fill invoice templates from a payload."""
import re
from pathlib import Path

from shipq.formatters import format_field

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def render(template_name, payload):
    """Replace each {{key}} with the formatted field; unknown keys render empty."""
    text = (TEMPLATES / template_name).read_text(encoding="utf-8")
    return re.sub(r"\{\{(\w+)\}\}",
                  lambda m: format_field(m.group(1), payload[m.group(1)])
                  if m.group(1) in payload else "", text)
EOF
cat > config/export.ini <<'EOF'
[csv]
# payload keys, in column order
columns = id, customer, items, total_weight, total
delimiter = ,
EOF
cat > shipq/export.py <<'EOF'
"""CSV export of order payloads; columns come from config/export.ini."""
import configparser
import csv
import io
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "export.ini"


def columns():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG, encoding="utf-8")
    return [c.strip() for c in cfg["csv"]["columns"].split(",")]


def to_csv(payloads):
    cols = columns()
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(cols)
    for p in payloads:
        w.writerow([p.get(c, "") for c in cols])
    return out.getvalue()
EOF
cat > shipq/checks.py <<'EOF'
"""Sanity checks run on every payload before it goes to billing."""


def nonempty(v):
    return isinstance(v, str) and v != ""


def positive(v):
    return v > 0


FIELD_CHECKS = {
    "id": nonempty,
    "customer": nonempty,
    "total": positive,
    "items": positive,
}


def problems(payload):
    """Names of fields that fail their check; absent optional fields are skipped."""
    return [k for k, check in FIELD_CHECKS.items() if k in payload and not check(payload[k])]
EOF
: > tests/__init__.py
cat > tests/test_payload.py <<'EOF'
import doctest
import unittest
from pathlib import Path

from shipq.checks import problems
from shipq.payload import Order, build_payload

README = Path(__file__).resolve().parent.parent / "README.md"


class PayloadTests(unittest.TestCase):
    def test_build(self):
        p = build_payload(Order("A1", "Ada", 1250, 1800, 3))
        self.assertEqual(p["id"], "A1")
        self.assertEqual(p["total_weight"], 1800)

    def test_checks_pass(self):
        self.assertEqual(problems(build_payload(Order("A1", "Ada", 1250, 1800, 3))), [])

    def test_readme_example(self):
        result = doctest.testfile(str(README), module_relative=False)
        self.assertEqual(result.failed, 0)
EOF
cat > tests/test_render.py <<'EOF'
import unittest

from shipq.render import render


class RenderTests(unittest.TestCase):
    def test_invoice(self):
        text = render("invoice.txt", {"id": "A1", "customer": "Ada", "items": 3,
                                      "total_weight": 1800, "total": 12.5})
        self.assertIn("Invoice A1 for Ada", text)
        self.assertIn("Weight: 1.8 kg", text)
EOF
cat > tests/test_export.py <<'EOF'
import unittest

from shipq.export import columns, to_csv


class ExportTests(unittest.TestCase):
    def test_header_matches_config(self):
        self.assertEqual(to_csv([]).strip(), ",".join(columns()))

    def test_row_count(self):
        rows = to_csv([{"id": "A1"}, {"id": "A2"}]).splitlines()
        self.assertEqual(len(rows), 3)
EOF
cat > shipq/report.py <<'EOF'
"""Daily totals report (reads orders, not payloads)."""


def totals(orders):
    subtotal = sum(o.total_cents for o in orders)
    total_items = sum(o.items for o in orders)
    return {"orders": len(orders), "total_cents": subtotal, "total_items": total_items}
EOF
cat > shipq/api.py <<'EOF'
"""Wire form of payloads for the web app: the same fields, camelCase keys."""


def camel(key):
    head, *rest = key.split("_")
    return head + "".join(w.capitalize() for w in rest)


def to_wire(payload):
    return {camel(k): v for k, v in payload.items()}
EOF
cat > web/invoice.js <<'EOF'
// Invoice summary line on the web app. `p` is a payload in wire form
// (shipq/api.py, to_wire).
export function summary(p) {
  const kg = (p.totalWeight / 1000).toFixed(1);
  return `${p.customer}: ${p.items} items, ${kg} kg, $${p.total.toFixed(2)}`;
}
EOF
cat > shipq/shipping.py <<'EOF'
"""Shipping fee for an order payload."""

FLAT_FEE = 7            # dollars
FREE_FROM = 100         # dollars


def shipping_fee(payload):
    """Flat fee, free once the order total reaches FREE_FROM."""
    return 0 if payload["total"] >= FREE_FROM else FLAT_FEE
EOF
cat > tests/test_shipping.py <<'EOF'
import unittest

from shipq.payload import Order, build_payload
from shipq.shipping import shipping_fee


class ShippingTests(unittest.TestCase):
    def test_big_order_ships_free(self):
        self.assertEqual(shipping_fee(build_payload(Order("A9", "Bo", 15000, 900, 4))), 0)
EOF
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "shipq: order payloads"
