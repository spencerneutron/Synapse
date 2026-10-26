# Setup

Install Synapse into a **workspace root**: the folder that holds your repos and
where you start Claude Code sessions. Commands below are macOS/Linux; Windows
notes follow each step.

**Requirements:** Claude Code 2.1.277 or later (native `AGENTS.md`), Python
3.10+, [Ollama](https://ollama.com) for embeddings, and Obsidian with its
`obsidian` command-line interface on `PATH` for the vault.

---

## 1. Copy the harness

```bash
SYNAPSE=~/Synapse WS=~/Workspace; mkdir -p "$WS/.claude/rules" "$WS/kb" && cp "$SYNAPSE/AGENTS.md" "$WS/" && cp -R "$SYNAPSE/.claude/skills" "$SYNAPSE/.claude/hooks" "$WS/.claude/" && cp "$SYNAPSE/platform/macos.md" "$WS/.claude/rules/platform.md" && cp -R "$SYNAPSE/kb/scripts" "$SYNAPSE/kb/requirements.txt" "$WS/kb/" && cp -R "$SYNAPSE/templates" "$WS/"
```

Set `SYNAPSE` to this repo and `WS` to your workspace root. On Windows, copy
the same paths and use `platform/windows.md` as the rule file.

**If the workspace root, or any folder above it, has a `CLAUDE.md`,
`.claude/CLAUDE.md`, or `CLAUDE.local.md`**, Claude Code reads that *instead
of* `AGENTS.md`. Move anything you need from it into `AGENTS.md`, then delete
it. (A V1 workspace is in this state; see "Upgrading from V1" below.)

**Expected:** `ls "$WS/.claude/skills"` lists the seven Synapse skills (plus
any project skills you already had), and `"$WS/.claude/rules/platform.md"`
exists.

## 2. Register the Stop hook

If `"$WS/.claude/settings.json"` does not exist, copy the template:

```bash
cp ~/Synapse/templates/settings.json ~/Workspace/.claude/settings.json
```

If it exists, merge the template's `hooks.Stop` entry into it by hand. On
Windows, change `python3` in the command to `python`.

## 3. Build the memory layer

```bash
cd ~/Workspace && python3 -m venv kb/.venv && kb/.venv/bin/pip install -r kb/requirements.txt && ollama pull nomic-embed-text && python3 kb/scripts/extract.py init
```

On Windows the venv's pip is `kb\.venv\Scripts\pip.exe`.

**Expected:** `initialized .claude-work/kb/vectors.db`.
**Failure signal:** `sqlite-vec not installed` means the venv step failed.

## 4. Connect the vault

1. Create an Obsidian vault named `Synapse`. For any other name, export
   `SYNAPSE_VAULT=<name>` in the shell that runs Claude Code.
2. Open it in Obsidian, then run:

```bash
python3 ~/Workspace/kb/scripts/vault_write.py verify
```

**Expected:** `vault: Synapse`. The `Sessions`, `Decisions`, `Patterns`, and
`Projects` folders appear on the first write.
**Failure signal:** "is Obsidian running with the 'Synapse' vault open?"

## 5. Backfill existing archives (optional)

If `.claude-work/archive/` already holds sessions, embed them so `/recall` can
find them. The kb scripts resolve `.claude-work/` from the working directory,
so run them from the workspace root. Preview first:

```bash
cd ~/Workspace && python3 kb/scripts/backfill.py --dry-run
```

## 6. Check the install

Start `claude` in the workspace root.

- Ask "Which skill do you run after /end-session?" The answer names
  `/extract-session`, which only `AGENTS.md` tells it. A generic answer means
  `AGENTS.md` did not load: look for a `CLAUDE.md` in the working directory or
  above it.
- `/plan-session` responds with an objective and a next step.
- Ask for a reply that opens with "Great question!". The Stop hook blocks it
  once and Claude rewrites the message.

If the workspace root is itself a git repo, add `.claude-work/` and `kb/.venv/`
to its `.gitignore`.

---

## Sessions started inside a sub-repo

Claude Code reads `AGENTS.md` only when no `CLAUDE.md` exists in the working
directory or any folder above it. Start a session inside a repo that has its
own `CLAUDE.md` and the workspace `AGENTS.md` is skipped. Two fixes:

- **Per repo:** add `@../AGENTS.md` (the relative path to the workspace file)
  to that repo's `CLAUDE.md`.
- **Everywhere:** have Claude Code read both kinds of file. In
  `~/.claude/settings.json`:

```json
{
  "pluginConfigs": {
    "cc-plugin-agents-md@builtin": {
      "options": { "instructionFiles": "claude-md-and-agents-md" }
    }
  }
}
```

Use the per-repo import as well for sessions where native `AGENTS.md` support
is unavailable (for example, the first session after upgrading Claude Code).

Either fix restores the instructions only. Planning files
(`.claude-work/current/`) and the kb scripts (`kb/scripts/`) resolve from the
working directory, so the session lifecycle and memory skills still expect the
workspace root. Start structured work there.

---

## Upgrading from V1

1. Archive the old instruction files: move the workspace's `CLAUDE.md` and
   `AGENTS.md` into `.claude-work/archive/`.
2. Run steps 1 and 2 above. Your skills folder keeps any project-specific
   skills; the Synapse ones are overwritten with v1.5.
3. Keep `kb/.venv`, `.claude-work/kb/vectors.db`, the archive, and the vault.
   v1.5 reads them unchanged.
4. If you set a vault name other than `Synapse` in V1's `vault_write.py`, set
   `SYNAPSE_VAULT` instead.
5. If V1's `/plan-session` ran a project command at session start (for
   example a roadmap sync), list that command under `## Session hooks` in the
   project's `PLAN.md`. v1.5's `/plan-session` no longer runs it on its own.
