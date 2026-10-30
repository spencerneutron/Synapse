#!/usr/bin/env python3
"""
build_eval_home.py — build a fixture Synapse home for the slice-D, slice-E, and hard evals.

  python3 tools/build_eval_home.py <home dir> --triggers on|off [--team] [--hard]

Provisions <home> with `synapse setup` (venv, config, DB), points the store's
vault at a copy of evals/fixtures/memory/vault, embeds those notes (needs
Ollama), and copies the fixture archive, never extracted, for the project
"harbor" (its own project, so the pending reminder only fires in the case
that tests it). With --triggers off, [recall] auto and [extract] remind are
false. With --team (slice E), it also adds a local decision from
fixtures/memory/vault-e and a folder team "acme" whose shared note, by a
teammate, contradicts it; this member shares as "alex". With --hard (the
`hard` cases), it also adds fixtures/hard: its vault notes, embedded, with the
older webhook decision marked superseded by the newer one, and its archive
sessions, embedded as if extracted (so no pending reminder fires for them).
Run the cases with EVAL_SYNAPSE_HOME=<home>.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "evals" / "fixtures" / "memory"
HARD = ROOT / "evals" / "fixtures" / "hard"
SUPERSEDED = [("Retry webhooks with exponential backoff", "Webhooks get three fixed-delay attempts")]


def synapse(home: Path, *args: str) -> None:
    env = {**os.environ, "SYNAPSE_HOME": str(home)}
    subprocess.run([str(ROOT / "bin" / "synapse"), *args], env=env, check=True,
                   stdout=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("home", type=Path)
    parser.add_argument("--triggers", choices=["on", "off"], required=True)
    parser.add_argument("--team", action="store_true", help="add the slice-E team and its conflict")
    parser.add_argument("--hard", action="store_true", help="add the hard cases' notes and archive")
    args = parser.parse_args()
    home = args.home.resolve()
    if home.exists():
        sys.exit(f"error: {home} exists; pass a new folder")

    synapse(home, "setup")
    on = "true" if args.triggers == "on" else "false"
    (home / "config.toml").write_text(
        'default_store = "main"\n\n[stores.main]\nvault = "Fixture"\n'
        f'vault_path = "{(home / "vault").as_posix()}"\n\n'
        f"[recall]\nauto = {on}\n\n[extract]\nremind = {on}\n", encoding="utf-8")
    shutil.copytree(FIXTURE / "vault", home / "vault")
    if args.team:
        shutil.copytree(FIXTURE / "vault-e", home / "vault", dirs_exist_ok=True)
    if args.hard:
        shutil.copytree(HARD / "vault", home / "vault", dirs_exist_ok=True)
    for note in sorted((home / "vault").rglob("*.md")):
        synapse(home, "extract", "embed-note", str(note))
    shutil.copytree(FIXTURE / "archive", home / "stores" / "main" / "archive", dirs_exist_ok=True)
    if args.hard:
        for old, new in SUPERSEDED:
            synapse(home, "extract", "supersede", old, "--by", new)
        archive = home / "stores" / "main" / "archive"
        shutil.copytree(HARD / "archive", archive, dirs_exist_ok=True)
        for project in sorted(d.name for d in (HARD / "archive").iterdir() if d.is_dir()):
            sessions = {f.stem.split("_", 1)[1] for f in (archive / project).glob("*_*.md")}
            for session in sorted(sessions):
                synapse(home, "extract", "embed-archive", session, "--project", project)
    if args.team:
        synapse(home, "shared", "init", "acme", "--author", "alex", "--path", str(home / "team-notes"))
        shutil.copytree(FIXTURE / "team", home / "team-notes", dirs_exist_ok=True)
        synapse(home, "shared", "sync", "acme")
    print(f"built {home} (triggers {args.triggers}{', hard' if args.hard else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
