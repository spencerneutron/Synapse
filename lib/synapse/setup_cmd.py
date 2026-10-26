#!/usr/bin/env python3
"""
setup_cmd.py — provision the Synapse home. Idempotent; never overwrites.

  synapse setup

Creates <home>/config.toml (only when missing), and <home>/venv with
sqlite-vec (downloaded once from PyPI); gives every configured store its
archive folder and vectors.db;
then checks Ollama, the embedding model, and the obsidian CLI and says what is
missing. It never downloads a model and never edits files Synapse does not own.
"""

import argparse
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor  # noqa: E402
import paths  # noqa: E402

REQUIREMENT = "sqlite-vec~=0.1.9"
CLI = Path(__file__).resolve().with_name("cli.py")


def step(status: str, what: str) -> None:
    print(f"  {status:<8} {what}")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args(argv)
    print(f"Synapse setup -> {doctor.tilde(paths.home())}")

    paths.home().mkdir(parents=True, exist_ok=True)
    cfg = paths.config_path()
    if cfg.exists():
        step("kept", f"{doctor.tilde(cfg)} (existing, not changed)")
    else:
        cfg.write_text(paths.CONFIG_TEMPLATE, encoding="utf-8")
        step("created", doctor.tilde(cfg))

    r = paths.resolve()

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
        init = subprocess.run([str(vp), str(CLI), "extract", "--db", str(db), "init"],
                              capture_output=True, text=True)
        if init.returncode:
            step("FAILED", f"store {name!r}: {init.stderr.strip() or init.stdout.strip()}")
            return 1
        step("ready", f"store {name!r} at {doctor.tilde(store_path)}")

    todo = []
    reachable, has_model = doctor.check_ollama()
    if not reachable:
        todo.append("install and start Ollama (https://ollama.com), then: ollama pull nomic-embed-text")
    elif not has_model:
        todo.append("ollama pull nomic-embed-text   (about 270 MB; ask the user first)")
    if not doctor.shutil.which("obsidian"):
        todo.append("enable Obsidian's command-line interface so `obsidian` is on PATH")
    if r.vault not in doctor.obsidian_vaults():
        todo.append(f"create or open an Obsidian vault named {r.vault!r}")

    if todo:
        print("still needed for memory features:")
        for t in todo:
            print(f"  - {t}")
    else:
        print("memory features ready")
    print("next: synapse doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
