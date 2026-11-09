#!/usr/bin/env python3
"""
setup_cmd.py — provision the Synapse home. Idempotent; never overwrites.

  synapse setup
  synapse setup --notes {obsidian,folder}
                                    (where a new config keeps notes; asked once on a terminal,
                                     else Obsidian when it is installed, else a plain folder)
  synapse setup --autocompact N     (N or Nk; writes autoCompactWindow to the user's
                                     Claude Code settings.json after a backup; refuses if set)

Creates <home>/config.toml (only when missing), and <home>/venv with
sqlite-vec (downloaded once from PyPI); gives every configured store its
archive folder and vectors.db (the resolved store, in folder mode, also gets its notes folder);
then checks Ollama, the embedding model, and (in Obsidian mode) the obsidian CLI
and says what is missing. It never downloads a model and never edits files Synapse does not own.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import autocompact  # noqa: E402
import doctor  # noqa: E402
import paths  # noqa: E402

REQUIREMENT = "sqlite-vec~=0.1.9"
CLI = Path(__file__).resolve().with_name("cli.py")


def step(status: str, what: str) -> None:
    print(f"  {status:<8} {what}")


def parse_window(text: str) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*([kK]?)\s*", text)
    n = int(m.group(1)) * (1000 if m.group(2) else 1) if m else 0
    if n <= 0:
        raise ValueError(f"invalid auto-compact window {text!r}: use a positive integer, or one with a k suffix (300k)")
    return n


def set_autocompact(text: str) -> int:
    """Add autoCompactWindow to the user's settings.json. Refuses if already set; backs up first."""
    try:
        n = parse_window(text)
    except ValueError as e:
        print(f"synapse setup: {e}", file=sys.stderr)
        return 2
    target = doctor.claude_dir() / "settings.json"
    data: dict = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"synapse setup: cannot read {doctor.tilde(target)}: {e}; file left untouched", file=sys.stderr)
            return 1
        if not isinstance(data, dict):
            print(f"synapse setup: {doctor.tilde(target)} is not a JSON object; file left untouched", file=sys.stderr)
            return 1
    found = doctor.autocompact_values(data)
    if found:
        print(f"synapse setup: autoCompactWindow is already set in {doctor.tilde(target)}; file left untouched",
              file=sys.stderr)
        for scope, value in found:
            print(f"  {scope}: {value}", file=sys.stderr)
        print("  change it yourself (or with /autocompact); Synapse never overwrites it", file=sys.stderr)
        return 1
    backup = target.with_name(f"{target.name}.synapse-backup-{datetime.now():%Y%m%d-%H%M%S}")
    print(f"will change: {doctor.tilde(target)}")
    print(f"  add: autoCompactWindow: {n} (top level)")
    print(f"  backup: {doctor.tilde(backup) if target.exists() else '(none; file does not exist yet)'}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup.write_bytes(target.read_bytes())
    data["autoCompactWindow"] = n
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    print(f"done: autoCompactWindow set to {n} in {doctor.tilde(target)}")
    print(f"  Claude Code {autocompact.marks(n, doctor.gate_min_context(Path.cwd()))} "
          "(on a 1M-window model)")
    return 0


def autocompact_advice() -> None:
    """Print the doctor's warning for an unset window, plus the command, when none is set."""
    rep = doctor.Report()
    doctor.check_settings(rep, Path.cwd())
    for i in rep.items:
        if i["check"] == "autocompact-window" and i["detail"].startswith(doctor.AUTOCOMPACT_UNSET[:30]):
            print(f"auto-compact: {i['detail']}")
            print("  to set it (backs up your settings.json first): synapse setup --autocompact 300k")


def detect_notes_mode() -> str:
    """Obsidian when it looks installed (its CLI on PATH, or its vault list), else a plain folder."""
    if shutil.which("obsidian") or doctor.obsidian_config_file().exists():
        return "obsidian"
    return "folder"


def choose_notes_mode(given: str | None) -> str:
    if given:
        return given
    detected = detect_notes_mode()
    if sys.stdin.isatty():
        answer = input("Keep notes in Obsidian or in a plain folder? "
                       f"[obsidian/folder] (default: {detected}): ").strip().lower()
        if answer in paths.NOTES_MODES:
            return answer
    return detected


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="synapse setup", description=__doc__.split("\n\n")[0])
    ap.add_argument("--autocompact", metavar="N", help="set Claude Code's autoCompactWindow (300000 or 300k) and stop")
    ap.add_argument("--notes", choices=paths.NOTES_MODES,
                    help="where a new config.toml keeps notes: an Obsidian vault or a plain folder")
    args = ap.parse_args(argv)
    if args.autocompact is not None:
        return set_autocompact(args.autocompact)
    print(f"Synapse setup -> {doctor.tilde(paths.home())}")

    paths.home().mkdir(parents=True, exist_ok=True)
    cfg = paths.config_path()
    if cfg.exists():
        step("kept", f"{doctor.tilde(cfg)} (existing, not changed)")
    else:
        mode = choose_notes_mode(args.notes)
        cfg.write_text(paths.CONFIG_TEMPLATE.replace('notes = "obsidian" ', f'notes = "{mode}" ', 1),
                       encoding="utf-8")
        step("created", doctor.tilde(cfg))

    r = paths.resolve()
    todo = []
    if args.notes and args.notes != r.notes:
        todo.append(f'set notes = "{args.notes}" under [stores.{r.store}] in {doctor.tilde(cfg)}')

    vp = paths.venv_python()
    if not vp.exists():
        made = subprocess.run([sys.executable, "-m", "venv", str(paths.venv_dir())],
                              capture_output=True, text=True)
        if made.returncode:
            step("FAILED", f"venv: {made.stderr.strip().splitlines()[-1] if made.stderr else 'unknown error'}")
            print("  hint: on Debian/Ubuntu install python3-venv; elsewhere reinstall Python with ensurepip")
            return 1
        step("created", f"venv {doctor.tilde(paths.venv_dir())}")
    if subprocess.run([str(vp), "-c", "import sqlite_vec"], capture_output=True).returncode:
        pip = subprocess.run([str(vp), "-m", "pip", "install", "--disable-pip-version-check",
                              "-q", REQUIREMENT], capture_output=True, text=True)
        if pip.returncode:
            step("FAILED", f"pip install {REQUIREMENT}: {pip.stderr.strip()[-300:]}")
            return 1
        step("installed", REQUIREMENT)
    else:
        step("kept", "sqlite-vec already in the venv")

    for name, store_path in paths.configured_stores().items():
        (store_path / "archive").mkdir(parents=True, exist_ok=True)
        db = store_path / "vectors.db"
        init = subprocess.run([str(vp), str(CLI), "extract", "--db", str(db), "upgrade"],
                              capture_output=True, text=True)
        if init.returncode:
            step("FAILED", f"store {name!r}: {init.stderr.strip() or init.stdout.strip()}")
            return 1
        note = " (upgraded to schema v2; backup kept)" if "upgraded" in init.stdout else ""
        step("ready", f"store {name!r} at {doctor.tilde(store_path)}{note}")

    if r.notes == "folder" and r.vault_path:
        default = r.store_path / "vault"
        if not r.vault_path.is_absolute():
            todo.append(f"make vault_path absolute under [stores.{r.store}] in {doctor.tilde(cfg)}")
        elif r.vault_path.is_dir() or paths.same_path(r.vault_path, default):
            for name in paths.VAULT_FOLDERS:
                (r.vault_path / name).mkdir(parents=True, exist_ok=True)
            step("ready", f"notes folder {doctor.tilde(r.vault_path)}")
        else:
            todo.append(f"create the notes folder {doctor.tilde(r.vault_path)} (vault_path in {doctor.tilde(cfg)})")
    reachable, has_model = doctor.check_ollama()
    if not reachable:
        todo.append("install and start Ollama (https://ollama.com), then: ollama pull nomic-embed-text")
    elif not has_model:
        todo.append("ollama pull nomic-embed-text   (about 270 MB; ask the user first)")
    if r.notes == "obsidian":
        if not shutil.which("obsidian"):
            todo.append("enable Obsidian's command-line interface so `obsidian` is on PATH")
        if r.vault not in doctor.obsidian_vaults():
            todo.append(f"create or open an Obsidian vault named {r.vault!r}")

    if todo:
        print("still needed for memory features:")
        for t in todo:
            print(f"  - {t}")
    else:
        print("memory features ready")
    autocompact_advice()
    print("next: synapse doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
