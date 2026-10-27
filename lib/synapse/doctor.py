#!/usr/bin/env python3
"""
doctor.py — read-only health and conflict report for a Synapse install.

  synapse doctor [--json] [--project-dir DIR]

Checks the runtime (Python, venv, DB, Ollama, the obsidian CLI), where data
resolves, and the conflicts INSTALL.md lists: same-named skills, competing
always-on rules, other Stop hooks, an output style, hooks disabled by
settings, an old V1/v1.5 install, and an unignored .claude-work/. It changes
nothing. Exit code 1 when any check is an error.
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

OLLAMA_BASE = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"
SKILL_NAMES = ("plan-session", "end-session", "recall", "extract-session", "share",
               "emission-contract", "workflow-recovery", "language-sweep",
               "setup", "doctor")
RULE_KEYWORDS = ("PLAN.md", "EXECUTION.md", ".claude-work", "/recall",
                 "extract-session", "emission", "Stop hook", "vector")
MANAGED_SETTINGS = {
    "darwin": Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    "linux": Path("/etc/claude-code/managed-settings.json"),
    "win32": Path(r"C:\Program Files\ClaudeCode\managed-settings.json"),
}


class Report:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, level: str, check: str, detail: str, fix: str = "") -> None:
        self.items.append({"level": level, "check": check, "detail": detail, "fix": fix})

    def count(self, level: str) -> int:
        return sum(1 for i in self.items if i["level"] == level)


def tilde(p) -> str:
    s, h = str(p), str(Path.home())
    return "~" + s[len(h):] if s.startswith(h) else s


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()


def read_json(path: Path, rep: Report) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        rep.add("warn", "settings", f"cannot parse {tilde(path)}: {e}")
        return {}


# ---------- Runtime ----------

def check_ollama() -> tuple[bool, bool]:
    """(reachable, model present)"""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=3) as resp:
            models = [m.get("name", "") for m in json.load(resp).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return False, False
    return True, any(m.split(":")[0] == EMBEDDING_MODEL for m in models)


def obsidian_vaults() -> dict[str, str]:
    """Vault folder name -> path, from Obsidian's own vault list."""
    if sys.platform == "darwin":
        cfg = Path("~/Library/Application Support/obsidian/obsidian.json").expanduser()
    elif sys.platform == "win32":
        cfg = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"
    else:
        cfg = Path("~/.config/obsidian/obsidian.json").expanduser()
    try:
        vaults = json.loads(cfg.read_text(encoding="utf-8")).get("vaults", {})
    except (OSError, ValueError):
        return {}
    return {Path(v["path"]).name: v["path"] for v in vaults.values() if v.get("path")}


def check_runtime(rep: Report, r: paths.Resolved) -> None:
    v = sys.version_info
    rep.add("ok", "python", f"{v.major}.{v.minor}.{v.micro} ({sys.executable})")

    if os.environ.get("EVAL_SYNAPSE_HOME") and not os.environ.get("SYNAPSE_HOME"):
        rep.add("warn", "home", f"{tilde(paths.home())} comes from EVAL_SYNAPSE_HOME, meant for eval runs only",
                "unset EVAL_SYNAPSE_HOME outside eval runs")
    if paths.config_path().exists():
        rep.add("ok", "config", tilde(paths.config_path()))
    else:
        rep.add("warn", "config", f"{tilde(paths.config_path())} missing", "run: synapse setup")

    rep.add("ok", "store", f"{r.store!r} at {tilde(r.store_path)} (from {tilde(r.store_source)})")
    rep.add("ok", "project", f"{r.project!r} (from {tilde(r.project_source)})")

    try:
        st = paths.settings()
        rep.add("ok", "triggers",
                f"recall hints {'on' if st['recall_auto'] else 'off'} (min_score {st['min_score']}, "
                f"max_hits {st['max_hits']}); extraction reminder {'on' if st['extract_remind'] else 'off'}")
    except SystemExit as e:
        rep.add("error", "triggers", str(e))
    from archive import discover_sessions
    pending = [s["id"] for s in discover_sessions(r.archive_dir) if not s["processed"]]
    if pending:
        rep.add("info", "pending", f"{len(pending)} archived session(s) in {r.project!r} never extracted "
                f"(latest {pending[-1]})", "run /synapse:extract-session")

    vp = paths.venv_python()
    if not vp.exists():
        rep.add("warn", "venv", f"{tilde(paths.venv_dir())} missing", "run: synapse setup")
    elif subprocess.run([str(vp), "-c", "import sqlite_vec"], capture_output=True).returncode:
        rep.add("warn", "venv", "sqlite-vec is not installed in the venv", "run: synapse setup")
    else:
        rep.add("ok", "venv", tilde(paths.venv_dir()))

    if r.db.exists():
        try:
            con = sqlite3.connect(f"file:{r.db}?mode=ro", uri=True)
            n = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
            tables = {t[0] for t in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            row = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone() \
                if "meta" in tables else None
            version = int(row[0]) if row else 1
            if version < 2:
                rep.add("warn", "vectors", f"{n} chunks in {tilde(r.db)}, schema v{version}",
                        "run: synapse setup (upgrades in place, backs up first, keeps every vector)")
            else:
                rep.add("ok", "vectors", f"{n} chunks in {tilde(r.db)} (schema v{version})")
        except sqlite3.Error as e:
            rep.add("error", "vectors", f"{tilde(r.db)} unreadable: {e}")
    else:
        rep.add("warn", "vectors", f"{tilde(r.db)} missing", "run: synapse setup")

    reachable, has_model = check_ollama()
    if not reachable:
        rep.add("warn", "ollama", f"not reachable at {OLLAMA_BASE}; recall and extraction need it",
                "install Ollama and start it (ollama serve)")
    elif not has_model:
        rep.add("warn", "ollama", f"{EMBEDDING_MODEL} not pulled", f"run: ollama pull {EMBEDDING_MODEL}")
    else:
        rep.add("ok", "ollama", f"{EMBEDDING_MODEL} available")

    if shutil.which("obsidian"):
        rep.add("ok", "obsidian", "obsidian CLI on PATH")
    else:
        rep.add("warn", "obsidian", "obsidian CLI not on PATH; /synapse:extract-session cannot write notes",
                "enable Obsidian's command-line interface")
    vaults = obsidian_vaults()
    if r.vault in vaults:
        detail = f"vault {r.vault!r} found at {tilde(vaults[r.vault])}"
        if r.vault_path is None:
            rep.add("info", "vault", detail,
                    f"set vault_path = \"{vaults[r.vault]}\" under [stores.{r.store}] so recall prints note paths")
        else:
            rep.add("ok", "vault", detail)
    elif vaults:
        rep.add("warn", "vault", f"no Obsidian vault named {r.vault!r} (have: {', '.join(sorted(vaults))})",
                f"create it, or set vault under [stores.{r.store}] in {tilde(paths.config_path())}")


# ---------- Conflicts ----------

def check_skills(rep: Report, project_dir: Path) -> None:
    dirs = [claude_dir() / "skills"] + [d / ".claude" / "skills" for d in (project_dir, *project_dir.parents)]
    for d in dict.fromkeys(dirs):
        clash = [n for n in SKILL_NAMES if (d / n / "SKILL.md").exists()]
        for n in clash:
            rep.add("warn", "skills", f"{tilde(d / n)} shares a name with /synapse:{n}; both load",
                    "remove or rename yours if it is an older copy of the same skill")


def check_rules(rep: Report, project_dir: Path) -> None:
    files = [claude_dir() / "CLAUDE.md", *sorted((claude_dir() / "rules").glob("*.md"))]
    for d in (project_dir, *project_dir.parents):
        files += [d / "CLAUDE.md", d / "AGENTS.md", d / "CLAUDE.local.md", d / ".claude" / "CLAUDE.md"]
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        v1 = (".claude-work" in text or "Local Knowledge Recall" in text) and \
             ("plan-session" in text or "/recall" in text)
        if v1:
            rep.add("warn", "rules", f"{tilde(f)} looks like Synapse V1/v1.5 instructions; the plugin now loads these rules",
                    "after migrating, retire or trim it so the rules are not loaded twice (the user's call)")
            continue
        hits = [k for k in RULE_KEYWORDS if k in text]
        if hits:
            rep.add("info", "rules", f"{tilde(f)} mentions {', '.join(hits)}",
                    "check it does not contradict Synapse's rules; project rules win where they do")


def plugin_stop_hooks(settings: dict) -> list[str]:
    """Stop hook commands of other enabled plugins."""
    found = []
    installed = read_json(claude_dir() / "plugins" / "installed_plugins.json", Report())
    for pid, enabled in settings.get("enabledPlugins", {}).items():
        if not enabled or pid.startswith("synapse@"):
            continue
        for inst in installed.get("plugins", {}).get(pid, []):
            hooks = read_json(Path(inst.get("installPath", "")) / "hooks" / "hooks.json", Report())
            if hooks.get("hooks", {}).get("Stop"):
                found.append(pid)
    return found


def check_settings(rep: Report, project_dir: Path) -> None:
    layers = [claude_dir() / "settings.json",
              project_dir / ".claude" / "settings.json",
              project_dir / ".claude" / "settings.local.json"]
    managed = MANAGED_SETTINGS.get(sys.platform)
    for path in [*layers, managed] if managed else layers:
        s = read_json(path, rep)
        if not s:
            continue
        for group in s.get("hooks", {}).get("Stop", []):
            for h in group.get("hooks", []):
                rep.add("warn", "stop-hooks", f"{tilde(path)} runs a Stop hook: {h.get('command', h)}",
                        "if it can block, it and Synapse's emission check may both ask for rewrites")
        if s.get("outputStyle"):
            rep.add("info", "output-style", f"{tilde(path)} sets outputStyle {s['outputStyle']!r}",
                    "make sure it does not contradict /synapse:emission-contract")
        if s.get("disableAllHooks"):
            rep.add("error", "hooks", f"{tilde(path)} sets disableAllHooks; Synapse's rules and Stop hook never load",
                    "remove the setting, or Synapse cannot work")
        if path == managed and s.get("allowManagedHooksOnly"):
            rep.add("error", "hooks", "managed settings allow only managed hooks; Synapse's hooks never run",
                    "ask your administrator")
        if path == layers[0]:
            for pid in plugin_stop_hooks(s):
                rep.add("warn", "stop-hooks", f"plugin {pid} also has a Stop hook",
                        "check it does not also ask for rewrites")


def migrated_count(old_archive: Path, r: paths.Resolved) -> tuple[int, int]:
    """(sessions in an old flat archive, how many are fully in the store)."""
    from archive import discover_sessions
    sessions = discover_sessions(old_archive)
    in_store = sum(
        all(any((proj / f.name).exists() for proj in r.archive_root.glob("*/")) for f in s["files"].values())
        for s in sessions)
    return len(sessions), in_store


def check_subagent_models(rep: Report, project_dir: Path) -> None:
    """Settings that override the role agents' own models."""
    sources = [("environment", dict(os.environ))]
    managed = MANAGED_SETTINGS.get(sys.platform)
    for path in (claude_dir() / "settings.json", project_dir / ".claude" / "settings.json",
                 project_dir / ".claude" / "settings.local.json", *([managed] if managed else [])):
        env = read_json(path, Report()).get("env") or {}
        if isinstance(env, dict):
            sources.append((tilde(path), env))
    for where, env in sources:
        model = env.get("CLAUDE_CODE_SUBAGENT_MODEL")
        forced = str(env.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "")).strip().lower() in {"1", "true", "yes", "on"}
        if forced:
            runs_on = f"CLAUDE_CODE_SUBAGENT_MODEL={model}" if model else "the main conversation's model"
            rep.add("warn", "agent-models", f"{where} forces sub-agent models "
                    f"(CLAUDE_CODE_SUBAGENT_MODEL_FORCE); every sub-agent runs on {runs_on}, "
                    "so Synapse's role models are ignored",
                    "unset it to let synapse:implementer/verifier/researcher/scout use their own models")
        elif model:
            rep.add("info", "agent-models", f"{where} sets CLAUDE_CODE_SUBAGENT_MODEL={model}",
                    "it applies only to agents without their own model; Synapse's roles set theirs")


def check_old_installs(rep: Report, project_dir: Path, r: paths.Resolved) -> None:
    try:
        children = [c for c in project_dir.iterdir() if c.is_dir() and not c.name.startswith(".")]
    except OSError:
        children = []
    for d in (project_dir, *project_dir.parents, *children):
        old = [p for p in ("kb/scripts/extract.py", ".claude-work/kb/vectors.db", ".claude-work/archive")
               if (d / p).exists()]
        if not old:
            continue
        total, done = migrated_count(d / ".claude-work" / "archive", r)
        if total and done == total and not (d / "kb" / "scripts").exists():
            rep.add("ok", "old-install", f"V1/v1.5 memory at {tilde(d)}: all {total} sessions are in "
                    f"store {r.store!r}; the old copy is only a backup")
            continue
        detail = f"V1/v1.5 memory at {tilde(d)} ({', '.join(old)})"
        if total:
            detail += f"; {done} of {total} sessions already in store {r.store!r}"
        fix = f"copy it into the store: synapse migrate --from \"{d}\" --dry-run, then without --dry-run"
        if total and done == total:
            fix = "the sessions are migrated; retire the V1 scripts (kb/) when ready"
        rep.add("info", "old-install", detail, fix)


def check_teams(rep: Report, r: paths.Resolved) -> None:
    """Each team: folder present, last sync, unpushed commits, conflict copies."""
    import shared
    try:
        teams = paths.teams()
    except SystemExit as e:
        rep.add("error", "teams", str(e))
        return
    for t in teams.values():
        name = f"team {t.name}"
        if not t.notes.is_dir():
            rep.add("error", name, f"notes folder {tilde(t.notes)} missing",
                    "check the path (folder team) or rejoin: synapse shared join")
            continue
        s = shared.team_status(t)
        in_store = t.stores is None or r.store in t.stores
        detail = (f"{t.transport}, {s['notes']} notes, author {t.author}, last sync {s['last_success'] or 'never'}"
                  + ("" if in_store else f"; not searched from store {r.store!r}"))
        if s["last_error"]:
            rep.add("warn", name, f"{detail}; last error: {s['last_error']}", f"run: synapse shared sync {t.name}")
        else:
            rep.add("ok", name, detail)
        if s["unpushed"]:
            rep.add("info", name, f"{s['unpushed']} commit(s) not pushed", f"after the user's OK: synapse shared push {t.name}")
        if s["conflicts"]:
            rep.add("warn", name, f"{len(s['conflicts'])} sync-conflict copies not indexed: "
                    + ", ".join(Path(c).name for c in s["conflicts"][:3]), "merge them into the original and delete the copy")


def check_gitignore(rep: Report, project_dir: Path) -> None:
    work = project_dir / ".claude-work"
    if not work.exists() or not paths.find_upwards(project_dir, ".git"):
        return
    probe = subprocess.run(["git", "-C", str(project_dir), "check-ignore", "-q", ".claude-work/current/PLAN.md"],
                           capture_output=True)
    if probe.returncode == 1:
        rep.add("warn", "gitignore", f"{tilde(work)} is not ignored by git",
                "add .claude-work/ to the repo's .gitignore (ask the user first)")


# ---------- Entry point ----------

def run(project_dir: Path) -> Report:
    rep = Report()
    try:
        r = paths.resolve(cwd=project_dir)
    except SystemExit as e:
        rep.add("error", "config", str(e))
        return rep
    check_runtime(rep, r)
    check_teams(rep, r)
    check_skills(rep, project_dir)
    check_rules(rep, project_dir)
    check_settings(rep, project_dir)
    check_subagent_models(rep, project_dir)
    check_old_installs(rep, project_dir, r)
    check_gitignore(rep, project_dir)
    return rep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    rep = run(args.project_dir.resolve())
    if args.json:
        print(json.dumps(rep.items, indent=2))
    else:
        print("Synapse doctor (read-only)")
        for i in rep.items:
            print(f"  {i['level']:<6} {i['check']:<13} {i['detail']}")
            if i["fix"]:
                print(f"  {'':<6} {'':<13} fix: {i['fix']}")
        print(f"summary: {rep.count('ok')} ok, {rep.count('info')} info, "
              f"{rep.count('warn')} warn, {rep.count('error')} error")
    return 1 if rep.count("error") else 0


if __name__ == "__main__":
    sys.exit(main())
