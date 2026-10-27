#!/usr/bin/env python3
"""
synapse — command-line entry point for the Synapse plugin.

  synapse where [--project P] [--json]   where data resolves for this folder
  synapse setup                          provision ~/.claude/synapse (idempotent)
  synapse doctor [--json]                read-only health and conflict report
  synapse archive [--project P]          archive .claude-work/current into the store
  synapse recall "<query>" [...]         semantic search over the active store
  synapse recall-check <golden.toml>     score recall against a golden set
  synapse recall-hint [--prompt "..."]   the automatic hint (UserPromptSubmit hook)
  synapse pending [--hook]               archived sessions never extracted
  synapse extract <subcommand> [...]     init | embed-archive | embed-note | status |
                                         upgrade | supersede
  synapse vault <subcommand> [...]       verify | create-note | note-exists | search
  synapse backfill [...]                 embed archived sessions with no marker
  synapse migrate --from DIR [...]       copy a V1/v1.5 workspace's memory in
  synapse version

bin/synapse runs this file with a Python 3.11+ found by lib/py.sh.
"""

import importlib
import json
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit(f"error: Synapse needs Python 3.11+; this is {sys.version.split()[0]} ({sys.executable})")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

COMMANDS = {
    "setup": "setup_cmd",
    "doctor": "doctor",
    "archive": "archive",
    "recall": "recall",
    "recall-check": "recall_check",
    "recall-hint": "hint",
    "pending": "pending",
    "extract": "extract",
    "vault": "vault_write",
    "backfill": "backfill",
    "migrate": "migrate",
}


def version() -> str:
    manifest = HERE.parent.parent / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, ValueError):
        return "unknown"


def where(argv: list[str]) -> int:
    import argparse
    import paths
    p = argparse.ArgumentParser(prog="synapse where")
    p.add_argument("--project", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    r = paths.resolve(project=args.project)
    if args.json:
        print(json.dumps(r.as_dict(), indent=2))
    else:
        for k, v in r.as_dict().items():
            print(f"{k:<15} {v}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "version":
        print(f"synapse {version()}")
        return 0
    if cmd == "where":
        return where(rest)
    if cmd not in COMMANDS:
        sys.exit(f"error: unknown command {cmd!r}; run `synapse help`")
    module = importlib.import_module(COMMANDS[cmd])
    return module.main(rest) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
