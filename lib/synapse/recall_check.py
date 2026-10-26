#!/usr/bin/env python3
"""
recall_check.py — score recall against a golden set of queries.

  synapse recall-check <golden.toml> [--top-k 5] [--mode hybrid] [--json]

A golden file lists cases whose right answers were chosen from the data, not
from what recall returned:

    [[case]]
    query = "QuickAddTracker"
    kind = "identifier"                      # free label; results group by it
    expect = ["archive/Choreganize/EXECUTION_2026-09-27-2316.md"]
    type = "decision"                        # optional, as recall --type
    project = "VeilMX"                       # optional, as recall --project

`expect` holds fnmatch patterns over stored paths. A case hits when any of
the top-k results matches any pattern. The report gives the hit rate and the
mean reciprocal rank (MRR), overall and per kind. A golden file that quotes a
personal store belongs in that store, not in a repository.
"""

import argparse
import fnmatch
import inspect
import json
import sys
import tomllib
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract  # noqa: E402  (re-execs under the Synapse venv when needed)
import paths  # noqa: E402
import recall  # noqa: E402


def score_case(case: dict, results: list[dict]) -> int | None:
    """1-based rank of the first result matching an expected pattern."""
    for rank, r in enumerate(results, 1):
        stored = r.get("stored_path", r["source_path"])
        if any(fnmatch.fnmatchcase(stored, pat) for pat in case["expect"]):
            return rank
    return None


def summarize(rows: list[dict]) -> dict:
    def stats(group):
        n = len(group)
        return {"cases": n,
                "hit_rate": round(sum(r["rank"] is not None for r in group) / n, 3) if n else 0.0,
                "mrr": round(sum(1 / r["rank"] for r in group if r["rank"]) / n, 3) if n else 0.0}
    kinds = sorted({r["kind"] for r in rows})
    return {"overall": stats(rows), **{k: stats([r for r in rows if r["kind"] == k]) for k in kinds}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("golden", type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--mode", default=None, help="passed to recall when it supports modes")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    cases = tomllib.loads(args.golden.read_text(encoding="utf-8")).get("case", [])
    if not cases:
        sys.exit(f"error: no [[case]] entries in {args.golden}")

    r = paths.resolve()
    conn = extract.db_connect(r.db)
    extract.require_current(conn, r.db)
    accepts = inspect.signature(recall.search).parameters
    rows = []
    for case in cases:
        kwargs = {"top_k": args.top_k, "project": case.get("project"), "source_type": case.get("type")}
        if args.mode and "mode" in accepts:
            kwargs["mode"] = args.mode
        results = recall.search(conn, case["query"], **kwargs)
        rows.append({"query": case["query"], "kind": case.get("kind", "case"),
                     "rank": score_case(case, results)})

    summary = summarize(rows)
    if args.json:
        print(json.dumps({"store": r.store, "top_k": args.top_k, "mode": args.mode,
                          "summary": summary, "cases": rows}, indent=2))
    else:
        print(f"recall-check: {len(rows)} cases, top-{args.top_k}, store {r.store!r}"
              + (f", mode {args.mode}" if args.mode else ""))
        for row in rows:
            print(f"  {str(row['rank'] or '-'):>2}  {row['kind']:<11} {row['query']}")
        for name, s in summary.items():
            print(f"{name:<12} hit@{args.top_k} {s['hit_rate']:.3f}   MRR {s['mrr']:.3f}   ({s['cases']} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
