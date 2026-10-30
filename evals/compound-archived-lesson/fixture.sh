#!/usr/bin/env bash
# Needs EVAL_SYNAPSE_HOME pointing at a home built by
# tools/build_eval_home.py --hard. The cause (the warehouse silently drops
# batches over 200 rows) is not in this repo; it is in an archived session of
# the project "quarry", buried mid-document. The repo offers a plausible wrong
# culprit: export.py swallows WarehouseTimeout and logs the batch as sent.
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
printf 'project = "quarry"\n' > .synapse.toml
cat > README.md <<'EOF'
# quarry

Nightly job that copies the day's orders from the orders database (SQLite)
into the analytics warehouse.

    python3 export.py --since 2026-10-01      # real run
    python3 export.py --since 2026-10-01 --dry-run
    python3 -m unittest                        # tests

The warehouse client lives in `warehouse.py`; its URL is in `config.toml`.
EOF
cat > config.toml <<'EOF'
[warehouse]
url = "https://warehouse.internal.example/api"
timeout_s = 30
EOF
cat > warehouse.py <<'EOF'
"""Thin client for the analytics warehouse's HTTP API."""
import json
import socket
import urllib.request


class WarehouseTimeout(Exception):
    pass


class WarehouseError(Exception):
    pass


class Client:
    def __init__(self, url, timeout_s=30):
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    def insert_many(self, table, rows):
        """Bulk-load rows (a list of dicts) into a table. Raises WarehouseError
        on a non-2xx answer and WarehouseTimeout when the call times out."""
        body = json.dumps({"table": table, "rows": rows}).encode()
        req = urllib.request.Request(f"{self.url}/bulk", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                if not 200 <= resp.status < 300:
                    raise WarehouseError(f"bulk load failed: HTTP {resp.status}")
        except socket.timeout as e:
            raise WarehouseTimeout(str(e)) from e
EOF
cat > export.py <<'EOF'
"""Copy orders created since a date from the orders DB into the warehouse."""
import argparse
import logging
import sqlite3
import tomllib

from warehouse import Client, WarehouseTimeout

log = logging.getLogger("quarry.export")

BATCH_SIZE = 1000    # rows per insert_many call
PAGE_SIZE = 5000     # rows per database page


def fetch_orders(conn, since):
    """Yield order rows (dicts) created on or after `since`, page by page."""
    offset = 0
    while True:
        page = conn.execute(
            "SELECT id, customer_id, total_cents, created_at FROM orders "
            "WHERE created_at >= ? ORDER BY id LIMIT ? OFFSET ?",
            (since, PAGE_SIZE, offset)).fetchall()
        if not page:
            return
        for r in page:
            yield {"id": r[0], "customer_id": r[1], "total_cents": r[2], "created_at": r[3]}
        offset += PAGE_SIZE


def send(client, batch, n):
    try:
        client.insert_many("orders", batch)
    except WarehouseTimeout:
        pass  # the warehouse is slow at night; tomorrow's run picks these up
    log.info("batch %d sent (%d rows)", n, len(batch))


def run(conn, client, since):
    """Export every order since `since`. Returns the number of rows sent."""
    batch, n, total = [], 0, 0
    for row in fetch_orders(conn, since):
        batch.append(row)
        if len(batch) == BATCH_SIZE:
            n += 1
            send(client, batch, n)
            total += len(batch)
            batch = []
    if batch:
        n += 1
        send(client, batch, n)
        total += len(batch)
    log.info("export done: %d rows in %d batches", total, n)
    return total


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--since", required=True)
    p.add_argument("--db", default="orders.db")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    with open("config.toml", "rb") as f:
        cfg = tomllib.load(f)["warehouse"]
    client = Client(cfg["url"], cfg.get("timeout_s", 30))
    if args.dry_run:
        client.insert_many = lambda table, rows: None
    run(sqlite3.connect(args.db), client, args.since)


if __name__ == "__main__":
    main()
EOF
mkdir -p tests
: > tests/__init__.py
cat > tests/test_export.py <<'EOF'
import sqlite3
import unittest

import export


class FakeWarehouse:
    def __init__(self):
        self.batches = []

    def insert_many(self, table, rows):
        self.batches.append(list(rows))


def orders_db(n):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, "
                 "total_cents INTEGER, created_at TEXT)")
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)",
                     [(i, i % 50, 100 + i, "2026-10-02") for i in range(1, n + 1)])
    return conn


class ExportTests(unittest.TestCase):
    def test_sends_every_row(self):
        wh = FakeWarehouse()
        self.assertEqual(export.run(orders_db(2500), wh, "2026-10-01"), 2500)
        self.assertEqual(sum(len(b) for b in wh.batches), 2500)

    def test_respects_since(self):
        wh = FakeWarehouse()
        self.assertEqual(export.run(orders_db(10), wh, "2026-10-03"), 0)
        self.assertEqual(wh.batches, [])

    def test_rows_in_id_order(self):
        wh = FakeWarehouse()
        export.run(orders_db(1200), wh, "2026-10-01")
        ids = [r["id"] for b in wh.batches for r in b]
        self.assertEqual(ids, sorted(ids))
EOF
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "quarry: nightly orders export"
