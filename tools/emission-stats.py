#!/usr/bin/env python3
"""
emission-stats.py — Stop-hook verdicts (blocks per turn) and emission-contract skill loads per transcript.

  python3 tools/emission-stats.py TRANSCRIPT... [--json]

Each TRANSCRIPT is a main Claude Code session file (projects/<project>/<session>.jsonl).
Only the main session is read: entries with isSidechain true are skipped, and
sub-agent files are not opened. Any line that does not parse is skipped.

  turn    a system entry with subtype stop_hook_summary
  block   a turn whose summary has hasOutput true (the Stop hook spoke)
  load    a Skill tool_use of synapse:emission-contract, counted once per id
          Since 2.6.1 the block count is the metric (issue #18); loads should be 0.
  origin  the user entry that started the turn: the last user entry before the
          turn's first assistant entry that is not a tool_result.
          slash = command tags; notification = <task-notification> and other
          automated event tags (<side-sessions-event>, <ci-monitor-event>);
          user = everything else, including ! shell input.

Prints numbers, file base names, model names and plugin versions only. It never
prints message text, prompts, tool inputs or full paths, and it writes nothing.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ORIGINS = ("user", "slash", "notification")
LOAD_SKILLS = {"synapse:emission-contract", "emission-contract"}
SLASH_RE = re.compile(r"<command-(?:name|message)>")
NOTIFY_RE = re.compile(r"<(?:task-notification|side-sessions-event|ci-monitor-event|[a-z]+-monitor-event)\b")
SKIP_USER_RE = re.compile(r"\s*<(?:system-reminder|local-command-caveat|local-command-stdout)\b")
VERSION_RE = re.compile(r"plugins[\\/]+cache[\\/]+synapse[\\/]+synapse[\\/]+(\d+\.\d+\.\d+[0-9A-Za-z.+-]*)")
MODEL_OK = re.compile(r"^[A-Za-z0-9._\[\]-]{1,64}$")


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text"
                         and isinstance(b.get("text"), str))
    return ""


def _is_tool_result(content):
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def classify(text):
    if SLASH_RE.search(text):
        return "slash"
    if NOTIFY_RE.search(text):
        return "notification"
    return "user"


def _blank():
    return {"turns": 0, "loads": 0, "load_turns": []}


def analyze(path):
    path = Path(path)
    res = {"file": path.name, "versions": [], "models": [], "turns": 0, "blocks": 0,
           "loads": 0, "compactions": 0, "origins": {o: _blank() for o in ORIGINS}}
    models = Counter()
    seen_ids, seen_msgs = set(), set()
    origin = "user"      # origin of the latest real user entry
    turn_origin = None   # latched at the first assistant entry of the open turn
    pending = []         # loads in the open turn
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return res

    def close_turn(index_origin, index):
        for _ in pending:
            res["origins"][index_origin]["loads"] += 1
            res["origins"][index_origin]["load_turns"].append(index)
        pending.clear()

    with fh:
        for raw in fh:
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(obj, dict) or obj.get("isSidechain") is True:
                continue
            for v in VERSION_RE.findall(raw):
                if v not in res["versions"]:
                    res["versions"].append(v)
            etype, msg = obj.get("type"), obj.get("message")
            if obj.get("subtype") == "compact_boundary" or obj.get("isCompactSummary"):
                if obj.get("subtype") == "compact_boundary":
                    res["compactions"] += 1
                continue
            if etype == "user" and isinstance(msg, dict):
                content = msg.get("content")
                if _is_tool_result(content) or obj.get("isCompactSummary"):
                    continue
                text = _text(content)
                if SKIP_USER_RE.match(text) and not SLASH_RE.search(text):
                    continue
                origin = classify(text)
                turn_origin = None
            elif etype == "assistant" and isinstance(msg, dict):
                if turn_origin is None:
                    turn_origin = origin
                mid = msg.get("id")
                model = msg.get("model")
                if (isinstance(model, str) and model != "<synthetic>" and MODEL_OK.match(model)
                        and (mid is None or mid not in seen_msgs)):
                    models[model] += 1
                if mid is not None:
                    seen_msgs.add(mid)
                blocks = msg.get("content")
                for b in blocks if isinstance(blocks, list) else []:
                    if (isinstance(b, dict) and b.get("type") == "tool_use"
                            and b.get("name") == "Skill"
                            and isinstance(b.get("input"), dict)
                            and b["input"].get("skill") in LOAD_SKILLS):
                        bid = b.get("id")
                        if bid in seen_ids:
                            continue
                        seen_ids.add(bid)
                        res["loads"] += 1
                        pending.append(1)
            elif etype == "system" and obj.get("subtype") == "stop_hook_summary":
                o = turn_origin or origin
                res["turns"] += 1
                res["origins"][o]["turns"] += 1
                if obj.get("hasOutput") is True:
                    res["blocks"] += 1
                close_turn(o, res["turns"])
                turn_origin = None
        if pending:  # loads in a turn that never reached a Stop summary
            close_turn(turn_origin or origin, res["turns"] + 1)
    res["models"] = [m for m, _ in models.most_common()]
    return res


def _join(items, sep=","):
    return sep.join(items) if items else "unknown"


def render(results):
    head = ["file", "version", "model", "turns u/s/n", "loads u/s/n", "loaded in turns",
            "blocks", "compact"]
    rows = []
    for r in results:
        o = r["origins"]
        where = " ".join(f"{k[0]}:{','.join(map(str, o[k]['load_turns']))}"
                         for k in ORIGINS if o[k]["load_turns"]) or "-"
        rows.append([r["file"], _join(r["versions"]), _join(r["models"]),
                     "/".join(str(o[k]["turns"]) for k in ORIGINS),
                     "/".join(str(o[k]["loads"]) for k in ORIGINS),
                     where, str(r["blocks"]), str(r["compactions"])])
    if len(results) > 1:
        tot = [sum(r["origins"][k][f] for r in results) for k in ORIGINS for f in ("turns",)]
        lod = [sum(r["origins"][k]["loads"] for r in results) for k in ORIGINS]
        rows.append(["TOTAL", "", "", "/".join(map(str, tot)), "/".join(map(str, lod)), "",
                     str(sum(r["blocks"] for r in results)),
                     str(sum(r["compactions"] for r in results))])
    widths = [max(len(x[i]) for x in [head, *rows]) for i in range(len(head))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in [head, *rows]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    # Windows Python writes pipes in the ANSI code page; force UTF-8 output.
    for stream, errors in ((sys.stdout, "replace"), (sys.stderr, "backslashreplace")):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors=errors)
    ap = argparse.ArgumentParser(
        description="Stop-hook verdicts and emission-contract loads per transcript "
                    "(origins: u = user, s = slash, n = notification – numbers only).")
    ap.add_argument("transcripts", nargs="+", help="main transcript .jsonl files")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    results = []
    for p in args.transcripts:
        if not Path(p).is_file():
            print(f"note: not a file: {Path(p).name}", file=sys.stderr)
            continue
        results.append(analyze(p))
    if not results:
        return 1
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        sys.stdout.write(render(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
