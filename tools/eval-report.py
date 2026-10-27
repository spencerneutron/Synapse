#!/usr/bin/env python3
"""
eval-report.py — read `claude plugin eval --json` results and print what
Synapse adds.

  python3 tools/eval-report.py RUN.json [RUN.json ...]      # with vs without
  python3 tools/eval-report.py --compare OLD.json NEW.json  # the with arms of two runs

The first form needs runs made with `--ablation with-without`. Per case: the
mean score in each arm and the delta; per grader: passes in each arm.
Graders marked `arm: with-only` are shown as signs the plugin fired and stay
out of the scores. `claude plugin eval` does the same, except in a case where
every grader is with-only: it then scores them all, in both arms. Scores here
are computed from the graders that count, so such a case is a signal only.
Runs that errored or skipped paid graders at the cost cap are left out and
listed; a partial file is named. Several files (one per tag, as
tools/run-bench.sh writes them) are reported together.
"""

import argparse
import json
import sys
from collections import defaultdict


def load(paths: list[str]) -> tuple[list[dict], float]:
    by_name, cost = {}, 0.0
    for p in paths:
        with open(p, encoding="utf-8") as f:
            run = json.load(f)
        if run.get("partial"):
            print(f"note: {p} is partial (a cost cap or an abort stopped it early)")
        for c in run["cases"]:
            if c["name"] in by_name:
                print(f"note: case {c['name']} appears again in {p}; using that copy")
            by_name[c["name"]] = c
        cost += run.get("costUsd") or 0.0
    return list(by_name.values()), cost


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def fmt(x: float | None) -> str:
    return "  -  " if x is None else f"{x:5.2f}"


def usable(run: dict) -> bool:
    """A run whose graders all ran: no error, no paid grader skipped at the cap."""
    return not run.get("error") and not run.get("skippedPaidGraders") and bool(run.get("graders"))


def signal_only(case: dict) -> bool:
    names = {g["name"] for g in case.get("graders", [])}
    return bool(names) and names <= with_only(case)


def with_only(case: dict) -> set[str]:
    """Graders marked `arm: with-only` in the case (or flagged in a result)."""
    marked = {g["name"] for g in case.get("graders", []) if (g.get("config") or {}).get("arm") == "with-only"}
    for runs in case["arms"].values():
        marked |= {g["name"] for r in runs for g in r.get("graders", []) if g.get("withOnly")}
    return marked


def run_score(run: dict, skip: set[str]) -> float | None:
    """Weighted pass rate over the graders that count; None if none count."""
    gs = [g for g in run.get("graders", []) if g["name"] not in skip]
    total = sum(g.get("weight", 1) for g in gs)
    return sum(g.get("weight", 1) for g in gs if g.get("passed")) / total if total else None


def arm_score(case: dict, arm: str) -> float | None:
    skip = with_only(case)
    return mean([s for r in case["arms"].get(arm, []) if usable(r) and (s := run_score(r, skip)) is not None])


def grader_passes(runs: list[dict], only: set[str] = frozenset()) -> dict[str, list]:
    """name -> [passed, total, with_only]"""
    out = defaultdict(lambda: [0, 0, False])
    for r in runs:
        if not usable(r):
            continue
        for g in r.get("graders", []):
            row = out[g["name"]]
            row[0] += bool(g.get("passed"))
            row[1] += 1
            row[2] = row[2] or g["name"] in only
    return out


def ablation(paths: list[str]) -> int:
    cases, cost = load(paths)
    if not any(c["arms"].get("without") for c in cases):
        sys.exit("error: no 'without' arm: run with --ablation with-without (tools/run-bench.sh does)")
    print(f"{'case':28} {'with':>5} {'w/out':>5} {'delta':>6}")
    pairs, dropped = [], []
    for c in sorted(cases, key=lambda c: c["name"]):
        for arm in ("with", "without"):
            bad = [r for r in c["arms"].get(arm, []) if not usable(r)]
            if bad:
                why = sorted({"error" if r.get("error") else "cost cap" if r.get("skippedPaidGraders")
                              else "no graders" for r in bad})
                dropped.append(f"{c['name']} ({arm}): {len(bad)} run(s) left out: {', '.join(why)}")
        if signal_only(c):
            print(f"{c['name']:28} signal only (every grader is with-only)")
            continue
        w, wo = arm_score(c, "with"), arm_score(c, "without")
        if w is not None and wo is not None:
            pairs.append((w, wo))
        delta = "" if w is None or wo is None else f"{w - wo:+6.2f}"
        print(f"{c['name']:28} {fmt(w)} {fmt(wo)} {delta}")
    if pairs:
        tw, two = mean([p[0] for p in pairs]), mean([p[1] for p in pairs])
        print(f"{'mean, ' + str(len(pairs)) + ' cases with both':28} {fmt(tw)} {fmt(two)} {tw - two:+6.2f}")
    for line in dropped:
        print(f"note: {line}")

    print(f"\n{'case':28} {'grader':24} {'with':>6} {'w/out':>6}")
    for c in sorted(cases, key=lambda c: c["name"]):
        only = with_only(c)
        gw = grader_passes(c["arms"].get("with", []), only)
        gwo = grader_passes(c["arms"].get("without", []), only)
        for name in sorted(set(gw) | set(gwo)):
            a, b = gw.get(name), gwo.get(name)
            only = (a and a[2]) or (b and b[2])
            cell = lambda r: f"{r[0]}/{r[1]}" if r else "-"
            print(f"{c['name']:28} {name + (' *' if only else ''):24} {cell(a):>6} {cell(b):>6}")
    print("\n* with-only: a sign the plugin fired, not scored")
    print(f"cost: ${cost:.2f}")
    return 0


def compare(old: str, new: str) -> int:
    (oc, ocost), (nc, ncost) = load([old]), load([new])
    o = {c["name"]: grader_passes(c["arms"].get("with", []), with_only(c)) for c in oc}
    n = {c["name"]: grader_passes(c["arms"].get("with", []), with_only(c)) for c in nc}
    print(f"{'case':28} {'grader':24} {'old':>6} {'new':>6}")
    for case in sorted(set(o) | set(n)):
        for name in sorted(set(o.get(case, {})) | set(n.get(case, {}))):
            a, b = o.get(case, {}).get(name), n.get(case, {}).get(name)
            cell = lambda r: f"{r[0]}/{r[1]}" if r else "-"
            mark = "  <" if a and b and a[0] * b[1] != b[0] * a[1] else ""
            print(f"{case:28} {name:24} {cell(a):>6} {cell(b):>6}{mark}")
    print(f"\ncost: old ${ocost:.2f}, new ${ncost:.2f}   (< marks a changed pass rate)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("runs", nargs="+", help="eval JSON files")
    parser.add_argument("--compare", action="store_true", help="compare the with arms of OLD NEW")
    args = parser.parse_args()
    if args.compare:
        if len(args.runs) != 2:
            sys.exit("error: --compare takes exactly two files: OLD NEW")
        return compare(*args.runs)
    return ablation(args.runs)


if __name__ == "__main__":
    sys.exit(main())
