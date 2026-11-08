#!/usr/bin/env python3
"""
vault_write.py — write structured notes into an Obsidian vault via the CLI.

Subcommands:
  verify                    Check Obsidian CLI is reachable and folders exist.
  create-note               Create a vault note from a Markdown file with front
                            matter (--from-md <path>, preferred), a JSON spec
                            (--from-file <path>), or JSON on stdin.
  note-exists <folder> <name>
                            Check if a note exists in a folder (exit 0 yes, 1 no).
  search <query>            Wrap `obsidian search`, return matching notes as JSON.

JSON spec for create-note:
{
  "type": "decision" | "pattern" | "fact" | "session",
  "title": "Use sqlite-vec for local vector store",
  "project": "workspace",
  "session_id": "2026-04-23-1645",        // optional, links back to source session
  "tags": ["decision"],                    // optional, auto-prefixed with type
  "related": ["[[Session 2026-04-23-1645]]"],
  "supersedes": "[[Decision: Use Chroma]]", // optional, decision notes only
  "applies_to": ["python", "retrieval"],    // optional, pattern notes only
  "body": "## Context\\n...\\n## Decision\\n..."
}

The same spec as Markdown (--from-md): the fields go in front matter and the
body follows it as plain text, so backslashes and newlines need no escaping.
Lists are `[a, b]` or `- item` lines; the H1 is added, so leave it out.

---
type: pattern
title: Quote Windows paths in Git Bash
project: workspace
session_id: 2026-04-23-1645
related: ["[[2026-04-23-1645]]"]
applies_to: [windows, shell]
---
## Problem
...
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
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
# The store's configured vault_path, if any; it wins over the Obsidian CLI.
VAULT_DIR: Path | None = None

FOLDERS = {
    "session": "Sessions",
    "decision": "Decisions",
    "pattern": "Patterns",
    "fact": "Facts",
    "project": "Projects",
}

# Characters that are unsafe in Windows filenames.
# Obsidian additionally disallows # ^ [ ] | : in note names.
INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*#^\[\]]')


# ---------- CLI invocation ----------

_obsidian_checked = False


def obsidian_running() -> bool | None:
    """Whether Obsidian is running; None when the check itself cannot run."""
    if sys.platform == "win32":
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe", "/NH"],
                                 capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out.returncode != 0:
            return None
        # Bytes: tasklist writes in the console code page, not UTF-8.
        return b"obsidian.exe" in out.stdout.lower()
    try:
        code = subprocess.run(["pgrep", "-x", "Obsidian"], capture_output=True).returncode
    except OSError:
        return None
    return {0: True, 1: False}.get(code)


def launch_command() -> list[str]:
    if sys.platform == "win32":
        # explorer.exe hands the URI to the running Windows shell, so Obsidian
        # starts outside this process tree (and any job the caller kills), with
        # the store's vault open.
        return ["explorer.exe", "obsidian://open?vault=" + urllib.parse.quote(VAULT_NAME)]
    return ["open", "-a", "Obsidian"]


def ensure_obsidian_running() -> None:
    """Launch Obsidian detached if it isn't running (macOS and Windows).

    If the app is not running, the `obsidian` CLI starts it as a CHILD of the
    calling process: the first call then usually times out while the app boots,
    and the app quits again when the caller's shell exits — so the next call
    finds nothing either. Launching through LaunchServices (`open -a`) or the
    Windows shell (`explorer.exe obsidian://…`) hands the app to the user's
    session instead, so it outlives this script. Checked once per process.
    """
    global _obsidian_checked
    if _obsidian_checked or sys.platform not in ("darwin", "win32"):
        return
    _obsidian_checked = True
    if obsidian_running() is not False:   # running, or the check can't tell: let the CLI try
        return
    cmd = launch_command()
    print(f"Obsidian is not running; launching it detached via `{' '.join(cmd)}`", file=sys.stderr)
    try:
        launched = subprocess.run(cmd, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        launched = None
    # explorer.exe exits 1 even when the launch works; the poll below decides.
    if launched is None or (sys.platform == "darwin" and launched.returncode != 0):
        sys.exit(f"error: could not launch Obsidian (`{' '.join(cmd)}` failed). "
                 "Start it by hand and retry.")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if obsidian_running():
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
        how = "by hand"
        if sys.platform in ("darwin", "win32"):
            how = f"with `{' '.join(launch_command())}` or by hand"
        sys.exit(
            "error: obsidian CLI timed out after 30s.\n"
            f"is Obsidian running with the {VAULT_NAME!r} vault open?\n"
            "(If it was just launched by the CLI itself, it runs as a child of this shell "
            f"and quits when the shell exits — start it {how} instead.)"
        )
    return result


_vault_path_cache: Path | None = None


def vault_path() -> Path:
    """The vault's folder on disk, cached per process: the store's configured
    vault_path, else what the Obsidian CLI reports. Always an existing
    absolute folder: the CLI can exit 0 with empty output, and Path("") is
    the working directory, so a note would land in the user's repo."""
    global _vault_path_cache
    if _vault_path_cache is not None:
        return _vault_path_cache
    if VAULT_DIR is not None:
        if not VAULT_DIR.is_absolute() or not VAULT_DIR.is_dir():
            sys.exit(f"error: the configured vault_path {VAULT_DIR} is not an existing absolute "
                     f"folder. fix vault_path in {paths.config_path()}")
        path = VAULT_DIR
    else:
        result = run_obsidian("vault", "info=path")
        out = (result.stdout or "").strip() if result.returncode == 0 else ""
        if not out:
            sys.exit(
                f"error: could not determine vault path (the obsidian CLI gave none). "
                f"is Obsidian running with the {VAULT_NAME!r} vault open? setting vault_path "
                f"for the store in {paths.config_path()} avoids asking Obsidian."
            )
        path = Path(out)
        if not path.is_absolute() or not path.is_dir():
            sys.exit(f"error: Obsidian reported vault path {out!r}, which is not an existing "
                     "absolute folder.")
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
    needs_quote = needs_quote or any(ord(c) < 32 for c in s)

    if needs_quote:
        # Double quotes; escape backslashes, quotes, and control characters,
        # so a value never starts a new front-matter line.
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        escaped = "".join(c if ord(c) >= 32 else f"\\x{ord(c):02x}" for c in escaped)
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


def set_frontmatter(path: Path, updates: dict) -> None:
    """Set front-matter keys in an existing note, keeping every other line.
    Adds a front-matter block when the note has none."""
    text = path.read_text(encoding="utf-8").removeprefix("\ufeff")
    lines = [f"{k}: {emit_yaml_value(v)}" for k, v in updates.items()]
    close = re.compile(r"\n---[ \t]*(?=\n|$)").search(text, 3) if text.startswith("---\n") else None
    if close:
        end = close.start()
        head = text[4:end].split("\n") if end > 3 else []
        for k, line in zip(updates, lines):
            idx = next((i for i, h in enumerate(head) if h.split(":", 1)[0].strip() == k), None)
            if idx is None:
                head.append(line)
            else:
                head[idx] = line
        new = "---\n" + "\n".join(head) + text[end:]
    else:
        new = "---\n" + "\n".join(lines) + "\n---\n" + text
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(new, encoding="utf-8", newline="\n")
    tmp.replace(path)


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
    Patterns/Facts/Projects) already indicates the note's type, so filenames don't
    need a redundant prefix. The H1 inside the file shows the type for human
    readers."""
    note_type = spec["type"]
    title = spec["title"]

    if note_type == "session":
        # Session notes are named by their session_id directly.
        return safe_name(spec.get("session_id") or title)
    if note_type in ("decision", "pattern", "fact", "project"):
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
    elif note_type in ("decision", "fact"):
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


def note_heading(spec: dict) -> str:
    """The H1 a note gets: the type is shown for decisions, patterns, and facts."""
    prefix = {"decision": "Decision: ", "pattern": "Pattern: ", "fact": "Fact: "}.get(spec["type"], "")
    return f"# {prefix}{spec['title']}"


def build_note_content(spec: dict) -> str:
    """Compose the full markdown for a vault note: frontmatter + H1 + body."""
    fields = build_frontmatter_fields(spec)
    fm_block = emit_frontmatter(fields)
    h1 = note_heading(spec)

    body = spec.get("body", "").strip()
    parts = [fm_block, "", h1, ""]
    if body:
        parts.append(body)
        parts.append("")  # trailing newline
    return "\n".join(parts)


# ---------- Markdown specs (--from-md) ----------

LIST_FIELDS = ("tags", "related", "sources", "applies_to")
WIKILINK = re.compile(r"\[\[[^\[\]]*\]\]")
WIKILINKS = re.compile(r"\[\[[^\[\]]*\]\](\s*,\s*\[\[[^\[\]]*\]\])*")


def _md_scalar(s: str) -> str | None:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        inner = s[1:-1]
        if s[0] == "'":
            return inner.replace("''", "'")
        # Only \" and \\ are unescaped; any other backslash stays as written.
        return re.sub(r'\\(["\\])', r"\1", inner)
    return None if s in ("", "~", "null") else s


def _md_flow_list(s: str) -> list[str]:
    """Split `a, "b", [[c]]` on commas outside quotes and brackets."""
    items, buf, depth, quote = [], "", 0, None
    for c in s:
        if quote:
            quote = None if c == quote else quote
        elif c in "\"'" and not buf.strip():   # a quote opens only at an item's start
            quote = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif c == "," and depth == 0:
            items.append(buf)
            buf = ""
            continue
        buf += c
    items.append(buf)
    return [v for v in map(_md_scalar, items) if v is not None]


def _md_value(key: str, raw: str):
    raw = raw.strip()
    if key not in LIST_FIELDS:
        return _md_scalar(raw)
    if WIKILINKS.fullmatch(raw):   # [[a]] or [[a]], [[b]]: links, not a YAML list
        return WIKILINK.findall(raw)
    if raw.startswith("[") and raw.endswith("]"):
        return _md_flow_list(raw[1:-1])
    value = _md_scalar(raw)
    return [] if value is None else [value]


def parse_md_spec(text: str) -> dict:
    """A note spec from Markdown: front matter fields, then the body.

    Reads the flat subset of YAML that a spec needs: `key: value`, flow lists
    `[a, b]`, and block lists of `- item` lines. Values are taken literally
    (no escape sequences), so Windows paths survive as written."""
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    text = re.sub(r"\A(?:[ \t]*\n)+", "", text)
    opener = re.match(r"---[ \t]*\n", text)
    close = re.compile(r"\n---[ \t]*(?=\n|$)").search(text, opener.end() - 1) if opener else None
    if not close:
        raise ValueError("no front matter: the file must start with a `---` line "
                         "and close the fields with another `---` line")
    spec: dict = {}
    key = None
    for line in text[opener.end():close.start()].split("\n"):
        item = re.match(r"\s*-\s+(.*)$", line)
        if item and key in LIST_FIELDS and isinstance(spec.get(key), list):
            value = _md_scalar(item.group(1))
            if value is not None:
                spec[key].append(value)
            continue
        m = re.match(r"([A-Za-z_][\w-]*)\s*:(.*)$", line)
        if not m:
            if line.strip() and not line.lstrip().startswith("#"):
                raise ValueError(f"cannot read front-matter line: {line!r}")
            continue
        key = m.group(1)
        spec[key] = _md_value(key, m.group(2))
    body = text[close.end():].lstrip("\n")
    if spec.get("type") and spec.get("title"):
        first, _, rest = body.partition("\n")
        if first.strip() in (note_heading(spec), f"# {spec['title']}"):   # create-note adds the H1
            body = rest
    spec["body"] = body
    return spec


def load_spec(args: argparse.Namespace) -> dict:
    """The note spec from --from-md, --from-file, or stdin."""
    if args.from_md:
        md_path = Path(args.from_md)
        if not md_path.exists():
            sys.exit(f"error: note file not found: {md_path}")
        try:
            return parse_md_spec(md_path.read_text(encoding="utf-8"))
        except ValueError as e:
            sys.exit(f"error: {md_path}: {e}")
    if args.from_file:
        spec_path = Path(args.from_file)
        if not spec_path.exists():
            sys.exit(f"error: spec file not found: {spec_path}")
        source, label = spec_path.read_text(encoding="utf-8"), f"in {spec_path}"
    else:
        # Fallback: read from stdin. Useful for direct shell piping when
        # safety prompts aren't a concern.
        source, label = sys.stdin.read(), "on stdin"
    try:
        return json.loads(source)
    except json.JSONDecodeError as e:
        hint = ""
        if "escape" in e.msg:   # Invalid \escape, Invalid \uXXXX escape (C:\users)
            hint = ("\nhint: a backslash in a JSON string must be written \\\\ "
                    "(Windows paths can use / instead). Or write the note as Markdown "
                    "with front matter and pass --from-md, which needs no escaping.")
        sys.exit(f"error: invalid JSON {label}: {e}{hint}")


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
    root = vault_path()
    print(f"vault path: {root}")
    if VAULT_DIR is not None:
        # vault_path decides where notes go; it must be the vault Obsidian has open.
        shown = run_obsidian("vault", "info=path")
        out = (shown.stdout or "").strip() if shown.returncode == 0 else ""
        if out and Path(out).is_absolute() and not paths.same_path(out, root):
            sys.exit(f"error: vault_path {root} is not the open vault's folder ({out}).\n"
                     f"notes would be written where Obsidian does not show them; fix vault_path "
                     f"in {paths.config_path()}.")
    print(f"folders will be created on first note write: "
          f"{', '.join(FOLDERS.values())}")
    print("verify OK")
    return 0


def cmd_create_note(args: argparse.Namespace) -> int:
    """Create a vault note from a Markdown or JSON spec.

    Prefers a file because piping multi-line JSON through PowerShell
    triggers shell-injection heuristics in agentic safety classifiers.
    Reading from a file keeps the invocation simple: a single absolute
    path argument with no embedded quotes or braces. Markdown (--from-md)
    also spares the body JSON escaping, which backslashes in prose break."""
    spec = load_spec(args)

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

    if note_type == "fact" and not spec.get("project"):
        sys.exit("error: a Fact note needs a project: facts are listed per project at session start")

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

    root = vault_path()
    target_dir = root / folder
    target_path = target_dir / f"{name}.md"
    # No resolve(): a vault folder may be a symlink. root is an absolute folder
    # and name is sanitized, so this only fails if that ever stops being true.
    if not target_path.is_absolute() or target_path.parent != root / folder:
        sys.exit(f"error: refusing to write {target_path}: it is outside the vault {root}")
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        target_path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as e:
        sys.exit(f"error: failed to write {target_path}: {e}")

    # Forward slashes: a Windows path with backslashes breaks when an agent
    # pastes it into a bash loop (`\$f` escapes the `$`).
    if getattr(args, "review_batch", None):
        import review
        r = paths.resolve()
        review.append(r, {"path": f"vault/{folder}/{name}.md", "title": spec["title"], "folder": folder,
                          "session": args.review_batch, "project": spec.get("project") or r.project})

    print(json.dumps({
        "created": True,
        "folder": folder,
        "name": name,
        "path": target_path.as_posix(),
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
    global VAULT_NAME, VAULT_DIR
    r = paths.resolve()
    VAULT_NAME, VAULT_DIR = r.vault, r.vault_path
    parser = argparse.ArgumentParser(prog="synapse vault", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser("verify",
                              help="check Obsidian CLI works and folders exist")
    p_verify.set_defaults(func=cmd_verify)

    p_create = sub.add_parser("create-note",
                              help="create a vault note from a Markdown or JSON spec file, or stdin")
    source = p_create.add_mutually_exclusive_group()
    source.add_argument("--from-md", default=None,
                        help="path to a Markdown file: spec fields in front matter, "
                             "then the body as plain text (preferred: no escaping)")
    source.add_argument("--from-file", default=None,
                        help="path to a JSON file containing the note spec "
                             "(preferred over stdin to avoid shell-quoting issues)")
    p_create.add_argument("--on-conflict", choices=["error", "suffix"],
                          default="error",
                          help="behavior when a note with this name already exists")
    p_create.add_argument("--review-batch", default=None, metavar="SESSION_ID",
                          help="record the note in the review ledger (synapse extract review)")
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