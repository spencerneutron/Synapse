#!/usr/bin/env python3
"""
context-cost.py — token and cost numbers from Claude Code transcripts.

  python3 tools/context-cost.py TRANSCRIPT... [--json]

Each TRANSCRIPT is a main transcript (projects/<project>/<session>.jsonl).
Subagent transcripts in the sibling folder <session>/subagents/*.jsonl are
read too. The line schema is undocumented, so any line that does not parse or
lacks the fields is skipped.

Each request counts once, keyed on message.id: one response is written as
several `assistant` entries that repeat the same usage.

Prints numbers only: counts, token totals, model names and timestamps. It
never prints message text, prompts, tool inputs or paths found inside a
transcript, and it writes nothing.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

W_READ, W_WRITE_5M, W_WRITE_1H, W_OUT = 0.1, 1.25, 2.0, 5.0
TTL_5M, TTL_1H, COLD_MIN_WRITE = 300, 3600, 1000
MODEL_OK = re.compile(r"^[A-Za-z0-9._\[\]-]{1,64}$")
CHECKPOINT = "synapse:checkpoint"


def _int(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0
    return max(0, int(v))


def _time(v):
    if not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def _lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def count_lines(path):
    """Numbers for a diagnostic when a transcript yields no requests."""
    n = {"lines": 0, "objects": 0, "assistant": 0, "usage": 0}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                n["lines"] += 1
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                n["objects"] += 1
                n["assistant"] += obj.get("type") == "assistant"
                msg = obj.get("message")
                n["usage"] += isinstance(msg, dict) and isinstance(msg.get("usage"), dict)
    except OSError:
        pass
    return n


def _request(entry):
    """Return (id, request dict) for an assistant entry, or None."""
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None
    mid, usage = msg.get("id"), msg.get("usage")
    if not isinstance(mid, str) or not mid or not isinstance(usage, dict):
        return None
    inp = _int(usage.get("input_tokens"))
    read = _int(usage.get("cache_read_input_tokens"))
    total = _int(usage.get("cache_creation_input_tokens"))
    cc = usage.get("cache_creation")
    h1 = m5 = None
    if isinstance(cc, dict):
        h1 = _int(cc.get("ephemeral_1h_input_tokens"))
        if "ephemeral_5m_input_tokens" in cc:
            m5 = _int(cc.get("ephemeral_5m_input_tokens"))
    ttl = None
    if h1:
        ttl = TTL_1H
    elif m5:
        ttl = TTL_5M
    h1 = h1 or 0
    if m5 is None:
        m5 = max(0, total - h1)
    model = msg.get("model")
    if not (isinstance(model, str) and MODEL_OK.match(model)):
        model = "unknown"
    return mid, {
        "time": _time(entry.get("timestamp")),
        "model": model,
        "context": inp + read + total,
        "input": inp,
        "cache_read": read,
        "cache_write": h1 + m5 if (h1 or m5) else total,
        "cache_write_1h": h1,
        "cache_write_5m": m5,
        "output": _int(usage.get("output_tokens")),
        "ttl": ttl,
    }


def _is_checkpoint_call(entry):
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return 0
    n = 0
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
            inp = b.get("input")
            skill = inp.get("skill") if isinstance(inp, dict) else None
            if isinstance(skill, str) and CHECKPOINT in skill:
                n += 1
    return n


def _is_checkpoint_prompt(entry):
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return int(CHECKPOINT in content)
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text" \
                    and isinstance(b.get("text"), str) and CHECKPOINT in b["text"]:
                return 1
    return 0


def _first_seen(e, seen):
    """False when this entry's uuid was already counted (a transcript can
    repeat earlier lines, e.g. after a resume); entries without uuid pass."""
    u = e.get("uuid")
    if not isinstance(u, str) or not u:
        return True
    if u in seen:
        return False
    seen.add(u)
    return True


def read_file(path, role, requests, events):
    seen = events["seen"]
    for e in _lines(path):
        t = e.get("type")
        fresh = _first_seen(e, seen) if t in ("assistant", "user", "system") else True
        if t == "assistant":
            r = _request(e)
            if r:
                mid, req = r
                req["role"] = role
                req["file"] = str(path)
                old = requests.get((str(path), mid))
                if old is None or req["output"] >= old["output"]:
                    requests[(str(path), mid)] = req
            if fresh:
                events["checkpoints"] += _is_checkpoint_call(e)
        elif t == "user":
            if fresh:
                events["checkpoints"] += _is_checkpoint_prompt(e)
        elif t == "system" and e.get("subtype") == "compact_boundary" and fresh:
            md = e.get("compactMetadata")
            md = md if isinstance(md, dict) else {}
            trig = md.get("trigger")
            c = {
                "time": _time(e.get("timestamp")),
                "trigger": trig if trig in ("auto", "manual") else "unknown",
                "pre_tokens": _int(md.get("preTokens")),
                "post_tokens": _int(md.get("postTokens")),
            }
            key = (c["time"], c["trigger"], c["pre_tokens"])
            if not (isinstance(e.get("uuid"), str) and e.get("uuid")):
                if key in events["compact_keys"]:
                    continue
                events["compact_keys"].add(key)
            events["compactions"].append(c)


def percentile(values, p):
    """Nearest-rank percentile; 0 for no values."""
    if not values:
        return 0
    s = sorted(values)
    k = max(1, -(-len(s) * p // 100))
    return s[int(k) - 1]


def cost(reqs, one_hour_mult):
    total = 0.0
    for r in reqs:
        total += (r["input"] + W_READ * r["cache_read"]
                  + W_WRITE_5M * r["cache_write_5m"]
                  + one_hour_mult * r["cache_write_1h"]
                  + W_OUT * r["output"])
    return total


def stats(reqs):
    ctx = [r["context"] for r in reqs]
    return {
        "requests": len(reqs),
        "mean_context": round(sum(ctx) / len(ctx)) if ctx else 0,
        "p90_context": percentile(ctx, 90),
        "cache_reads": sum(r["cache_read"] for r in reqs),
        "cache_write_5m": sum(r["cache_write_5m"] for r in reqs),
        "cache_write_1h": sum(r["cache_write_1h"] for r in reqs),
        "output": sum(r["output"] for r in reqs),
        "cost_base_equiv": round(cost(reqs, W_WRITE_5M), 1),
        "cost_base_equiv_1h2x": round(cost(reqs, W_WRITE_1H), 1),
    }


def cold_resumes(reqs):
    """Requests after an idle gap longer than the cache TTL whose writes
    dwarf their reads. Gaps are per transcript file; the TTL comes from the
    latest earlier request that reported a cache_creation split (else 5m)."""
    by_file = {}
    for r in reqs:
        if r["time"]:
            by_file.setdefault(r["file"], []).append(r)
    found = []
    for rows in by_file.values():
        rows.sort(key=lambda r: r["time"])
        ttl, prev = TTL_5M, None
        for r in rows:
            if prev is not None:
                gap = (datetime.fromisoformat(r["time"])
                       - datetime.fromisoformat(prev["time"])).total_seconds()
                if gap > ttl and r["cache_write"] > r["cache_read"] \
                        and r["cache_write"] >= COLD_MIN_WRITE:
                    found.append((r, gap))
            if r["ttl"]:
                ttl = r["ttl"]
            prev = r
    found.sort(key=lambda x: x[0]["time"])
    rs = [r for r, _ in found]
    return {
        "count": len(found),
        "cache_write_tokens": sum(r["cache_write"] for r in rs),
        "cost_base_equiv": round(cost(rs, W_WRITE_5M), 1),
        "cost_base_equiv_1h2x": round(cost(rs, W_WRITE_1H), 1),
        "events": [{"time": r["time"], "gap_min": round(g / 60, 1), "context": r["context"]}
                   for r, g in found],
    }


def share(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def analyze(main_path):
    main_path = Path(main_path)
    requests = {}
    events = {"checkpoints": 0, "compactions": [], "seen": set(), "compact_keys": set()}
    read_file(main_path, "main", requests, events)
    sub_dir = main_path.with_suffix("") / "subagents"
    sub_files = sorted(sub_dir.glob("*.jsonl")) if sub_dir.is_dir() else []
    for f in sub_files:
        read_file(f, "subagent", requests, events)
    reqs = sorted(requests.values(), key=lambda r: r["time"] or "")
    main = [r for r in reqs if r["role"] == "main"]
    sub = [r for r in reqs if r["role"] == "subagent"]
    sm, ss, sa = stats(main), stats(sub), stats(reqs)
    times = [r["time"] for r in reqs if r["time"]]
    models = {}
    for r in reqs:
        models[r["model"]] = models.get(r["model"], 0) + 1
    return {
        "session": main_path.stem if re.match(r"^[A-Za-z0-9._-]{1,80}$", main_path.stem) else "session",
        "first": times[0] if times else None,
        "last": times[-1] if times else None,
        "subagent_files": len(sub_files),
        "models": models,
        "main": sm, "subagent": ss, "all": sa,
        "main_share_pct": {
            "requests": share(sm["requests"], sa["requests"]),
            "cache_reads": share(sm["cache_reads"], sa["cache_reads"]),
            "output": share(sm["output"], sa["output"]),
            "cost": share(sm["cost_base_equiv"], sa["cost_base_equiv"]),
        },
        "cold_resumes": {"main": cold_resumes(main), "subagent": cold_resumes(sub),
                         "all": cold_resumes(reqs)},
        "checkpoints": events["checkpoints"],
        "compactions": events["compactions"],
        "request_list": [
            {k: r[k] for k in ("role", "time", "model", "context", "cache_read",
                               "cache_write", "cache_write_1h", "cache_write_5m", "output")}
            for r in reqs
        ],
    }


def render(results):
    out = []
    for i, r in enumerate(results, 1):
        out.append(f"session {i}: {r['session']}  {r['first'] or '-'} .. {r['last'] or '-'}"
                   f"  subagent files {r['subagent_files']}")
        out.append("  models: " + ", ".join(f"{m} x{n}" for m, n in sorted(r["models"].items())) if r["models"] else "  models: none")
        head = f"  {'':9}{'requests':>9}{'mean ctx':>11}{'p90 ctx':>11}{'cache reads':>14}{'output':>9}{'cost':>13}{'cost(1h 2x)':>13}"
        out.append(head)
        for name in ("main", "subagent", "all"):
            s = r[name]
            out.append(f"  {name:9}{s['requests']:>9}{s['mean_context']:>11}{s['p90_context']:>11}"
                       f"{s['cache_reads']:>14}{s['output']:>9}{s['cost_base_equiv']:>13.1f}{s['cost_base_equiv_1h2x']:>13.1f}")
        sh = r["main_share_pct"]
        out.append(f"  main share %: requests {sh['requests']}  cache reads {sh['cache_reads']}"
                   f"  output {sh['output']}  cost {sh['cost']}")
        out.append(f"  cache writes: 5m {r['all']['cache_write_5m']}  1h {r['all']['cache_write_1h']}")
        out.append(f"  checkpoints: {r['checkpoints']}  compactions: {len(r['compactions'])}")
        for c in r["compactions"]:
            out.append(f"    compact {c['time'] or '-'} {c['trigger']} pre {c['pre_tokens']} post {c['post_tokens']}")
        for role in ("main", "subagent"):
            cr = r["cold_resumes"][role]
            out.append(f"  cold resumes ({role}): {cr['count']}  cache writes {cr['cache_write_tokens']}"
                       f"  cost {cr['cost_base_equiv']:.1f}  cost(1h 2x) {cr['cost_base_equiv_1h2x']:.1f}")
            for c in cr["events"]:
                out.append(f"    cold {c['time']} gap {c['gap_min']} min ctx {c['context']}")
        out.append("")
    if len(results) > 1:
        main = sum(r["main"]["cache_reads"] for r in results)
        allr = sum(r["all"]["cache_reads"] for r in results)
        out.append(f"total over {len(results)} sessions: cache reads {allr}, main share {share(main, allr)}%")
    return "\n".join(out).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Numbers-only token and cost report from transcripts.")
    ap.add_argument("transcripts", nargs="+", help="main transcript .jsonl files")
    ap.add_argument("--json", action="store_true", help="print JSON (includes per-request rows)")
    args = ap.parse_args(argv)
    bad = False
    for p in args.transcripts:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                fh.read(1)
        except OSError as exc:
            print(f"error: cannot read transcript: {p} ({exc.strerror or type(exc).__name__})",
                  file=sys.stderr)
            bad = True
    if bad:
        return 1  # nothing on stdout: no partial report for the good paths
    results = [analyze(p) for p in args.transcripts]
    for p, r in zip(args.transcripts, results):
        if r["main"]["requests"] == 0:
            n = count_lines(p)
            print(f"note: no requests found in {p}: lines {n['lines']}, json objects {n['objects']}, "
                  f"assistant entries {n['assistant']}, entries with message.usage {n['usage']}",
                  file=sys.stderr)
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        sys.stdout.write(render(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
