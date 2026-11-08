"""review.py — the ledger of notes written by automatic extraction ([extract] accept = auto).

A JSON file in the store (paths.review_ledger): {"entries": [...], "reviewed_at": ISO|null}.
`synapse vault create-note --review-batch ID` appends; `synapse extract review` lists
entries newer than reviewed_at; `synapse pending --hook` counts them. A file scan only:
no DB, no Ollama.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load(r: paths.Resolved) -> dict:
    """The ledger; an absent or unreadable file is an empty one."""
    try:
        data = json.loads(paths.review_ledger(r).read_text(encoding="utf-8"))
        entries = data.get("entries")
        reviewed = data.get("reviewed_at")
        return {"entries": [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else [],
                "reviewed_at": reviewed if isinstance(reviewed, str) else None}
    except (OSError, ValueError, AttributeError):
        return {"entries": [], "reviewed_at": None}


def save(r: paths.Resolved, ledger: dict) -> None:
    target = paths.review_ledger(r)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def append(r: paths.Resolved, entry: dict) -> None:
    ledger = load(r)
    ledger["entries"].append({**entry, "time": now()})
    save(r, ledger)


def _when(text) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(text))
        return t if t.tzinfo else t.astimezone()
    except ValueError:
        return None


def unreviewed(ledger: dict) -> list[dict]:
    """Entries written after reviewed_at (all of them when it is null)."""
    cut = _when(ledger.get("reviewed_at")) if ledger.get("reviewed_at") else None
    out = []
    for e in ledger["entries"]:
        t = _when(e.get("time"))
        if cut is None or t is None or t > cut:
            out.append(e)
    return out


def mark_reviewed(r: paths.Resolved) -> str:
    ledger = load(r)
    ledger["reviewed_at"] = now()
    save(r, ledger)
    return ledger["reviewed_at"]
