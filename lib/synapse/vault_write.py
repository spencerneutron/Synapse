#!/usr/bin/env python3
"""
vault_write.py — write structured notes into an Obsidian vault via the CLI.

Subcommands:
  verify                    Check Obsidian CLI is reachable and folders exist.
  create-note               Create a vault note from a JSON spec
                            (--from-file <path>, preferred; else stdin).
  note-exists <folder> <name>
                            Check if a note exists in a folder (exit 0 yes, 1 no).
  search <query>            Wrap `obsidian search`, return matching notes as JSON.

JSON spec for create-note:
{
  "type": "decision" | "pattern" | "session",
  "title": "Use sqlite-vec for local vector store",
  "project": "workspace",
  "session_id": "2026-04-23-1645",        // optional, links back to source session
  "tags": ["decision"],                    // optional, auto-prefixed with type
  "related": ["[[Session 2026-04-23-1645]]"],
  "supersedes": "[[Decision: Use Chroma]]", // optional, decision notes only
  "applies_to": ["python", "retrieval"],    // optional, pattern notes only
  "body": "## Context\\n...\\n## Decision\\n..."
}
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Force UTF-8 for stdout/stderr on Windows PowerShell.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# ---------- Configuration ----------

# The active store's vault (paths.resolve); SYNAPSE_VAULT overrides it.
# Set in main() so importing this module never reads config.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

VAULT_NAME = paths.DEFAULT_VAULT

FOLDERS = {
    "session": "Sessions",
    "decision": "Decisions",
    "pattern": "Patterns",
    "project": "Projects",
}

# Characters that are unsafe in Windows filenames.
# Obsidian additionally disallows # ^ [ ] | : in note names.
INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*#^\[\]]')


# ---------- CLI invocation ----------

_obsidian_checked = False


def ensure_obsidian_running() -> None:
    """Launch Obsidian detached if it isn't running (macOS only).

    If the app is not running, the `obsidian` CLI starts it as a CHILD of the
    calling process: the first call then usually times out while the app boots,
    and the app quits again when the caller's shell exits — so the next call
    finds nothing either. Launching through LaunchServices (`open -a`) hands the
    app to the session instead, so it outlives this script. Checked once per
    process.
    """
    global _obsidian_checked
    if _obsidian_checked or sys.platform != "darwin":
        return
    _obsidian_checked = True
    running = subprocess.run(["pgrep", "-x", "Obsidian"], capture_output=True).returncode == 0
    if running:
        return
    print("Obsidian is not running; launching it detached via `open -a Obsidian`", file=sys.stderr)
    if subprocess.run(["open", "-a", "Obsidian"], capture_output=True).returncode != 0:
        sys.exit("error: could not launch Obsidian (`open -a Obsidian` failed). Start it by hand and retry.")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if subprocess.run(["pgrep", "-x", "Obsidian"], capture_output=True).returncode == 0:
            time.sleep(5)  # let the CLI server inside the app come up before the first command
            return
        time.sleep(1)
    sys.exit("error: Obsidian did not start within 30s. Start it by hand and retry.")


def run_obsidian(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    """Invoke the obsidian CLI. Always pins the vault name."""
    if not shutil.which("obsidian"):
        sys.exit(
            "error: 'obsidian' command not found on PATH.\n"
            "ensure Obsidian is installed and the CLI was registered "
            "(Settings → General → Command line interface → Register CLI)."
        )
    ensure_obsidian_running()

    cmd = ["obsidian", *args, f'vault={VAULT_NAME}']
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        sys.exit(
            "error: obsidian CLI timed out after 30s.\n"
            f"is Obsidian running with the {VAULT_NAME!r} vault open?\n"
            "(If it was just launched by the CLI itself, it runs as a child of this shell "
            "and quits when the shell exits — start it with `open -a Obsidian` instead.)"
        )
    return result


_vault_path_cache: Path | None = None


def vault_path() -> Path:
    """Return the on-disk path to the Synapse vault. Cached per-process."""
    global _vault_path_cache
    if _vault_path_cache is not None:
        return _vault_path_cache
    result = run_obsidian("vault", "info=path")
    if result.returncode != 0:
        sys.exit(
            f"error: could not determine vault path. "
            f"is Obsidian running with the {VAULT_NAME!r} vault open?"
        )
    path = Path(result.stdout.strip())
    if not path.exists():
        sys.exit(f"error: Obsidian reported vault path {path} but it does not exist.")
    _vault_path_cache = path
    return path


# ---------- Frontmatter generation ----------

def emit_yaml_value(value) -> str:
    """Emit a single YAML value. Conservative quoting: only when needed."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]  # YYYY-MM-DD only
    if isinstance(value, list):
        if not value:
            return "[]"
        items = ", ".join(emit_yaml_value(v) for v in value)
        return f"[{items}]"

    s = str(value)
    # Quote if contains YAML-significant chars or starts ambiguously.
    needs_quote = any(c in s for c in [":", "#", "&", "*", "!", "|", ">", "%", "@", "`", '"'])
    needs_quote = needs_quote or s.strip() != s
    needs_quote = needs_quote or s.lower() in ("true", "false", "null", "yes", "no", "")
    needs_quote = needs_quote or (s and s[0] in "[]{},'\"")

    if needs_quote:
        # Use double quotes; escape internal double quotes and backslashes.
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def emit_frontmatter(fields: dict) -> str:
    """Emit a YAML frontmatter block. Field order matters for diff readability."""
    lines = ["---"]
    for k, v in fields.items():
        if v is None or v == [] or v == "":
            continue
        lines.append(f"{k}: {emit_yaml_value(v)}")
    lines.append("---")
    return "\n".join(lines)


# ---------- Note construction ----------

def safe_name(title: str) -> str:
    """Normalize a title to a valid Obsidian note name."""
    cleaned = INVALID_NAME_CHARS.sub("", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        sys.exit(f"error: title produced an empty name after sanitization: {title!r}")
    if len(cleaned) > 200:
        cleaned = cleaned[:200].rstrip()
    return cleaned


def build_note_name(spec: dict) -> str:
    """Build the filename based on note type. The folder (Sessions/Decisions/
    Patterns/Projects) already indicates the note's type, so filenames don't
    need a redundant prefix. The H1 inside the file shows the type for human
    readers."""
    note_type = spec["type"]
    title = spec["title"]

    if note_type == "session":
        # Session notes are named by their session_id directly.
        return safe_name(spec.get("session_id") or title)
    if note_type in ("decision", "pattern", "project"):
        return safe_name(title)
    sys.exit(f"error: unknown note type {note_type!r}")


def build_frontmatter_fields(spec: dict) -> dict:
    """Construct the frontmatter field dict in display order."""
    note_type = spec["type"]
    today = date.today().isoformat()

    fields: dict = {
        "type": note_type,
        "date": spec.get("date", today),
        "project": spec.get("project"),
        "status": spec.get("status", "active"),
    }

    if note_type == "session":
        fields["session_id"] = spec.get("session_id")
        fields["duration"] = spec.get("duration")
    elif note_type == "decision":
        fields["supersedes"] = spec.get("supersedes")
    elif note_type == "pattern":
        fields["applies_to"] = spec.get("applies_to") or []

    # Tags: always include the type as a tag, plus any extras.
    tag_set = {note_type}
    for t in spec.get("tags", []):
        tag_set.add(t)
    fields["tags"] = sorted(tag_set)

    # Provenance fields, kept last for readability.
    fields["sources"] = spec.get("sources") or []
    fields["related"] = spec.get("related") or []

    return fields


def build_note_content(spec: dict) -> str:
    """Compose the full markdown for a vault note: frontmatter + H1 + body."""
    fields = build_frontmatter_fields(spec)
    fm_block = emit_frontmatter(fields)

    note_type = spec["type"]
    title = spec["title"]
    if note_type == "decision":
        h1 = f"# Decision: {title}"
    elif note_type == "pattern":
        h1 = f"# Pattern: {title}"
    else:
        h1 = f"# {title}"

    body = spec.get("body", "").strip()
    parts = [fm_block, "", h1, ""]
    if body:
        parts.append(body)
        parts.append("")  # trailing newline
    return "\n".join(parts)


# ---------- Conflict resolution ----------

def note_exists(folder: str, name: str) -> bool:
    """Check whether a note exists by direct disk lookup. Faster and
    more reliable than asking the Obsidian CLI."""
    target = vault_path() / folder / f"{name}.md"
    return target.exists()


def resolve_name_with_conflict(folder: str, name: str, on_conflict: str) -> str:
    """If a note with this name exists, return a non-conflicting name per policy."""
    if not note_exists(folder, name):
        return name
    if on_conflict == "error":
        sys.exit(f"error: note '{folder}/{name}.md' already exists. "
                 "use --on-conflict suffix to write a versioned name instead.")
    if on_conflict == "suffix":
        for n in range(2, 100):
            candidate = f"{name} v{n}"
            if not note_exists(folder, candidate):
                return candidate
        sys.exit(f"error: could not find a free suffix for {name!r} after 99 tries.")
    sys.exit(f"error: unknown --on-conflict policy {on_conflict!r}")


# ---------- Subcommands ----------

def cmd_verify(args: argparse.Namespace) -> int:
    """Confirm Obsidian CLI is reachable and we're connected to the right vault.

    Folders are not created here. Obsidian creates folders implicitly when a
    note is written into a path that doesn't yet exist, so the four typed
    folders (Sessions, Decisions, Patterns, Projects) will materialize as
    notes get created in them. There's no folder:create command in the CLI."""
    result = run_obsidian("vault", "info=name")
    if result.returncode != 0:
        sys.exit(
            f"error: obsidian CLI returned exit code {result.returncode}.\n"
            f"stderr: {result.stderr.strip()}\n"
            f"is Obsidian running with the {VAULT_NAME!r} vault open?"
        )

    actual_vault = result.stdout.strip()
    if actual_vault != VAULT_NAME:
        sys.exit(
            f"error: connected to vault {actual_vault!r}, expected {VAULT_NAME!r}.\n"
            f"open the {VAULT_NAME!r} vault in Obsidian and retry."
        )

    print(f"vault: {VAULT_NAME}")
    print(f"folders will be created on first note write: "
          f"{', '.join(FOLDERS.values())}")
    print("verify OK")
    return 0


def cmd_create_note(args: argparse.Namespace) -> int:
    """Create a vault note from a JSON spec.

    Prefers --from-file because piping multi-line JSON through PowerShell
    triggers shell-injection heuristics in agentic safety classifiers.
    Reading from a file keeps the invocation simple: a single absolute
    path argument with no embedded quotes or braces."""
    if args.from_file:
        spec_path = Path(args.from_file)
        if not spec_path.exists():
            sys.exit(f"error: spec file not found: {spec_path}")
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            sys.exit(f"error: invalid JSON in {spec_path}: {e}")
    else:
        # Fallback: read from stdin. Useful for direct shell piping when
        # safety prompts aren't a concern.
        try:
            spec = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            sys.exit(f"error: invalid JSON on stdin: {e}")

    if not isinstance(spec, dict):
        sys.exit("error: spec JSON must be an object, not an array or scalar.")

    required = ["type", "title"]
    missing = [f for f in required if not spec.get(f)]
    if missing:
        sys.exit(f"error: missing required fields: {', '.join(missing)}")

    note_type = spec["type"]
    if note_type not in FOLDERS:
        sys.exit(f"error: unknown note type {note_type!r}. "
                 f"valid types: {', '.join(FOLDERS)}")

    folder = FOLDERS[note_type]
    name = build_note_name(spec)
    name = resolve_name_with_conflict(folder, name, args.on_conflict)

    content = build_note_content(spec)

    # Write the note file directly to disk under the vault path. This
    # bypasses Obsidian's `create` CLI command for two reasons:
    #
    # 1. Subprocess argv encoding on Windows mangles unicode characters
    #    (em-dashes, smart quotes, etc.) when the child process is not a
    #    Python script. Python's Path.write_text(encoding="utf-8") avoids
    #    this entirely.
    #
    # 2. The CLI returns exit 0 on silent failures, requiring fragile
    #    string matching ("Created:") to verify success. Direct disk
    #    writes either succeed or raise — unambiguous.
    #
    # Obsidian watches its vault directory and picks up new files
    # automatically, so the user-facing experience is identical.

    target_dir = vault_path() / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{name}.md"

    try:
        target_path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as e:
        sys.exit(f"error: failed to write {target_path}: {e}")

    print(json.dumps({
        "created": True,
        "folder": folder,
        "name": name,
        "path": str(target_path),
        "vault_relative_path": f"{folder}/{name}.md",
    }, indent=2))
    return 0


def cmd_note_exists(args: argparse.Namespace) -> int:
    """Exit 0 if the named note exists in the given folder, 1 otherwise."""
    folder = args.folder
    name = safe_name(args.name)
    exists = note_exists(folder, name)
    print(json.dumps({"folder": folder, "name": name, "exists": exists}))
    return 0 if exists else 1


def cmd_search(args: argparse.Namespace) -> int:
    """Wrap obsidian search, emit results as JSON."""
    result = run_obsidian("search", f"query={args.query}", "format=json")
    if result.returncode != 0:
        sys.exit(f"error: obsidian search failed: {result.stderr.strip()}")
    # Pass through whatever shape obsidian search emits.
    print(result.stdout)
    return 0


# ---------- Entry point ----------

def main(argv: list[str] | None = None) -> int:
    global VAULT_NAME
    VAULT_NAME = paths.resolve().vault
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser("verify",
                              help="check Obsidian CLI works and folders exist")
    p_verify.set_defaults(func=cmd_verify)

    p_create = sub.add_parser("create-note",
                              help="create a vault note from a JSON spec file or stdin")
    p_create.add_argument("--from-file", default=None,
                          help="path to a JSON file containing the note spec "
                               "(preferred over stdin to avoid shell-quoting issues)")
    p_create.add_argument("--on-conflict", choices=["error", "suffix"],
                          default="error",
                          help="behavior when a note with this name already exists")
    p_create.set_defaults(func=cmd_create_note)

    p_exists = sub.add_parser("note-exists",
                              help="check whether a note exists")
    p_exists.add_argument("folder", help="vault folder (e.g. Decisions)")
    p_exists.add_argument("name", help="note name without .md extension")
    p_exists.set_defaults(func=cmd_note_exists)

    p_search = sub.add_parser("search",
                              help="wrap obsidian search; emit results as JSON")
    p_search.add_argument("query")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())