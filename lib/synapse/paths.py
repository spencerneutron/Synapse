#!/usr/bin/env python3
"""
paths.py — resolve where Synapse keeps its data. No other module hard-codes a
location; everything asks resolve().

  Home     $SYNAPSE_HOME, else ${CLAUDE_CONFIG_DIR:-~/.claude}/synapse
  Config   <home>/config.toml
  Store    $SYNAPSE_STORE, else the nearest .synapse.toml's `store`, else the
           config's `default_store`, else "main". A store is an archive folder,
           a vectors.db, and an Obsidian vault, kept together so a project can
           split all three at once.
  Project  an explicit --project, else the nearest .synapse.toml's `project`,
           else the git root's folder name, else the working directory's name.

Paths stored inside a store's DB are relative ("archive/<project>/<file>",
"vault/<Folder>/<file>") so a store can move, or later be shared, intact.
"""

import os
import re
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_STORE = "main"
DEFAULT_VAULT = "Synapse"
MARKER = ".synapse.toml"
VAULT_FOLDERS = ("Sessions", "Decisions", "Patterns", "Projects")

CONFIG_TEMPLATE = """\
# Synapse configuration. Written once by `synapse setup`; edit freely.
# A store keeps one archive, one vectors.db, and one Obsidian vault together.
# Projects use `default_store` unless a .synapse.toml at their root names
# another store (store = "<name>"), or SYNAPSE_STORE is set.

default_store = "main"

[stores.main]
# path = "~/.claude/synapse/stores/main"   # default
vault = "Synapse"
# vault_path = "/path/to/the/vault/folder" # optional; lets recall print note paths

# [stores.client-x]
# path = "~/clients/x/synapse-store"
# vault = "Client X"
"""


def home() -> Path:
    if os.environ.get("SYNAPSE_HOME"):
        return Path(os.environ["SYNAPSE_HOME"]).expanduser()
    base = os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"
    return Path(base).expanduser() / "synapse"


def config_path() -> Path:
    return home() / "config.toml"


def venv_dir() -> Path:
    return home() / "venv"


def venv_python() -> Path:
    if sys.platform == "win32":
        return venv_dir() / "Scripts" / "python.exe"
    return venv_dir() / "bin" / "python"


def load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"error: cannot parse {path}: {e}")


def find_upwards(start: Path, name: str) -> Path | None:
    for d in (start, *start.parents):
        candidate = d / name
        if candidate.exists():
            return candidate
    return None


def safe_project(name: str) -> str:
    """A project name usable as a folder name on every platform."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name).strip(" .")
    return cleaned or "unsorted"


@dataclass
class Resolved:
    home: Path
    config: Path
    store: str
    store_source: str
    store_path: Path
    vault: str
    vault_path: Path | None
    project: str
    project_source: str
    archive_root: Path
    archive_dir: Path
    processed_dir: Path
    db: Path

    def as_dict(self) -> dict:
        return {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(self).items()}


def resolve(project: str | None = None, cwd: Path | None = None) -> Resolved:
    cwd = (cwd or Path.cwd()).resolve()
    cfg = load_toml(config_path())
    marker = find_upwards(cwd, MARKER)
    mk = load_toml(marker) if marker else {}

    if os.environ.get("SYNAPSE_STORE"):
        store, store_source = os.environ["SYNAPSE_STORE"], "SYNAPSE_STORE"
    elif mk.get("store"):
        store, store_source = mk["store"], str(marker)
    elif cfg.get("default_store"):
        store, store_source = cfg["default_store"], str(config_path())
    else:
        store, store_source = DEFAULT_STORE, "built-in default"

    stores = cfg.get("stores", {})
    if store in stores:
        sc = stores[store]
    elif store == DEFAULT_STORE:
        sc = {}
    else:
        sys.exit(f"error: store {store!r} (from {store_source}) is not defined in {config_path()}")

    store_path = Path(sc["path"]).expanduser() if sc.get("path") else home() / "stores" / store
    vault = os.environ.get("SYNAPSE_VAULT") or sc.get("vault") or DEFAULT_VAULT
    vault_path = Path(sc["vault_path"]).expanduser() if sc.get("vault_path") else None

    if project:
        project_source = "argument"
    elif mk.get("project"):
        project, project_source = mk["project"], str(marker)
    else:
        git = find_upwards(cwd, ".git")
        if git:
            project, project_source = git.parent.name, "git root"
        else:
            project, project_source = cwd.name, "working directory"
    project = safe_project(project)

    archive_root = store_path / "archive"
    archive_dir = archive_root / project
    return Resolved(
        home=home(),
        config=config_path(),
        store=store,
        store_source=store_source,
        store_path=store_path,
        vault=vault,
        vault_path=vault_path,
        project=project,
        project_source=project_source,
        archive_root=archive_root,
        archive_dir=archive_dir,
        processed_dir=archive_dir / ".processed",
        db=store_path / "vectors.db",
    )


def configured_stores() -> dict[str, Path]:
    """Every store in config.toml, plus the default store, mapped to its folder."""
    cfg = load_toml(config_path())
    names = [*cfg.get("stores", {}), cfg.get("default_store", DEFAULT_STORE)]
    stores = {}
    for name in dict.fromkeys(names):
        sc = cfg.get("stores", {}).get(name, {})
        stores[name] = Path(sc["path"]).expanduser() if sc.get("path") else home() / "stores" / name
    return stores


def to_stored_path(path: Path, r: Resolved) -> str:
    """The portable form of a source path, as written to the DB."""
    path = Path(path)
    try:
        return path.resolve().relative_to(r.store_path.resolve()).as_posix()
    except ValueError:
        pass
    if len(path.parts) >= 2 and path.parts[-2] in VAULT_FOLDERS:
        return f"vault/{path.parts[-2]}/{path.parts[-1]}"
    return str(path)


def to_display_path(stored: str, r: Resolved) -> str:
    """The readable location of a stored path on this machine."""
    if stored.startswith("archive/"):
        return str(r.store_path / stored)
    if stored.startswith("vault/") and r.vault_path:
        return str(r.vault_path / stored.removeprefix("vault/"))
    return stored
