# Installing Synapse

Synapse installs as a Claude Code plugin at user scope, so it works in every
project. It writes only to its own folders, and it never changes an existing
setup: where it overlaps one, it reports the overlap and the user decides.

**For a Claude Code agent installing this for a user:** follow the steps in
order. Steps 1 and 5 are read-only. Ask the user before step 2 and wherever
this page says *ask*. Never fix a conflict on the user's behalf during
install.

---

## Requirements

| Need | Check | Notes |
|------|-------|-------|
| Claude Code 2.1.292+ (one-step CLI install) | `claude --version` | 2.1.275+ supports the one-step in-session `/plugin install`; older versions use the two-step install in step 2 |
| bash | `bash --version` | macOS and Linux have it; on Windows, Claude Code uses Git Bash |
| Python 3.11+ | `python3 --version` (Windows: `python --version`) | Synapse picks the first 3.11+ it finds |
| Ollama + `nomic-embed-text` | `ollama list` | Needed for recall and extraction |
| Obsidian with its CLI on `PATH` | `obsidian --help` | Needed for vault notes |
| Read access to `spencerneutron/Synapse` | `gh repo view spencerneutron/Synapse` | Public repos need nothing. If the repo is private and the check fails, the **user** runs `gh auth login` and `gh auth setup-git` (the second changes their global git credential helper); an agent cannot complete them |

Ollama and Obsidian can come later; the session rules, skills, and output
contract work without them.

---

## 0. Get this runbook

A web fetch of the raw file works while the repo is public. If it is
private, read it with the user's GitHub credentials instead:

```bash
gh api repos/spencerneutron/Synapse/contents/INSTALL.md -H "Accept: application/vnd.github.raw"
```

---

## 1. Preflight (read-only)

Installing is additive, but Synapse's rules and Stop hook take effect in every
new session. Look for overlaps first and report them to the user. Run these
from the folder where the user usually starts Claude Code.

| Look for | Command | If found |
|----------|---------|----------|
| Skills named `plan-session`, `end-session`, `recall`, `extract-session`, `emission-contract`, `workflow-recovery`, `language-sweep`, `setup`, `doctor` | `ls ~/.claude/skills .claude/skills 2>/dev/null` | Both copies load beside `/synapse:<name>`. An older Synapse copy should be retired later (the user's call) |
| Always-on rules about planning files, recall, memory, or output style | `ls ~/.claude/CLAUDE.md ~/.claude/rules CLAUDE.md AGENTS.md CLAUDE.local.md .claude/CLAUDE.md 2>/dev/null`, then read them | Where a project's rules conflict, Synapse defers to them; tell the user which rules overlap |
| Other `Stop` hooks, an `outputStyle`, or `disableAllHooks` | `grep -n -e '"Stop"' -e outputStyle -e disableAllHooks ~/.claude/settings.json .claude/settings.json .claude/settings.local.json 2>/dev/null` | Another blocking Stop hook can stack rewrite requests. `disableAllHooks` stops Synapse from working at all |
| Managed settings that allow only managed hooks | macOS `/Library/Application Support/ClaudeCode/managed-settings.json`, Linux `/etc/claude-code/managed-settings.json`, Windows `C:\Program Files\ClaudeCode\managed-settings.json` | `allowManagedHooksOnly` means Synapse cannot load; stop and tell the user |
| A V1 or v1.5 install, here, in a parent folder, or in a child folder | `ls -d kb/scripts .claude-work/archive .claude-work/kb ../.claude-work/archive */.claude-work/archive 2>/dev/null` | Offer migration in step 6 |
| Working files a repo would commit | `git check-ignore -q .claude-work/current/PLAN.md; echo $?` inside a repo (`1` means not ignored) | Suggest adding `.claude-work/` to that repo's `.gitignore` (ask first) |
| An earlier v1.6+ install | `ls ~/.claude/synapse 2>/dev/null` | Setup reuses it and never overwrites it |

Summarize what you found, then *ask* whether to continue.

---

## 2. Install (ask first)

This adds `enabledPlugins` and `extraKnownMarketplaces` entries to
`~/.claude/settings.json`. Tell the user that before running it. Nothing else
outside Claude Code's plugin cache changes.

```bash
claude plugin install synapse --marketplace spencerneutron/Synapse
```

This one-step form needs Claude Code 2.1.292 or later. On older versions,
add the marketplace, then install:

```bash
claude plugin marketplace add spencerneutron/Synapse
```

```bash
claude plugin install synapse@synapse
```

Inside a session (Claude Code 2.1.275 or later) the user can type
`/plugin install synapse --marketplace spencerneutron/Synapse`.

**Expected:** `claude plugin list` shows `synapse@synapse`, enabled, scope
`user`. **Failure signal:** an authentication error means the user's git
credentials cannot read the private repo (see Requirements).

## 3. Start a new session (hand off to the user)

Plugins load at session start, and an agent cannot start a session. **Stop
here** and ask the user to start a new Claude Code session and say *"continue
INSTALL.md from step 4"*. The installed copy of this file is at
`~/.claude/plugins/cache/synapse/synapse/<version>/INSTALL.md`
(`claude plugin list --json` shows the exact path).

In the new session, `/synapse:doctor` appears in the slash menu, and asking
"Which skill runs after /synapse:end-session?" gets `/synapse:extract-session`
as the answer. A generic answer means the rules did not load: check step 1's
hook settings.

## 4. Provision (`/synapse:setup`)

Run `/synapse:setup`, or `synapse setup` from the Bash tool. It creates, under
`~/.claude/synapse/` only:

- `config.toml` (when missing): one global store, `main`, using the vault `Synapse`
- `stores/main/archive/` and `stores/main/vectors.db`
- `venv/` with `sqlite-vec`, downloaded once from PyPI (tell the user)
- the archive folder and `vectors.db` of every store in `config.toml`

Then it lists what is still missing. *Ask* before pulling the embedding
model (`ollama pull nomic-embed-text`, about 270 MB). Never install Ollama or
Obsidian for the user; point them to it.

**Expected:** the last lines read `memory features ready` (or a short list of
what is missing) and `next: synapse doctor`.

## 5. Verify (`/synapse:doctor`, read-only)

Run `/synapse:doctor`, or `synapse doctor`. It ends with a summary such as
`summary: 8 ok, 1 info, 0 warn, 0 error`.

- **error:** Synapse cannot work until the user changes this.
- **warn:** Synapse works, but something will surprise the user (a same-named
  skill, another Stop hook, a missing dependency).
- **info:** worth knowing; acts only if the user wants.

Rerun it any time Synapse misbehaves.

## 6. Bring in old memory (optional, ask first)

When doctor reports `old-install`:

```bash
synapse migrate --from "<old workspace>" --dry-run
```

Show the user the plan, then run it again without `--dry-run`. Migration
copies archives and vectors into the active store and never changes the old
workspace; re-running it adds nothing twice. Then embed any sessions the old
install never embedded:

```bash
synapse backfill --dry-run
```

After migrating, doctor reports the old memory as `ok` (already in the store)
and flags the old instruction files and skill copies, which duplicate what the
plugin now loads. Retiring them is the user's call; moving them into a folder
such as `.claude-work/v1-retired/` keeps them restorable.

If V1's `plan-session` ran a project command at session start (for example a
roadmap sync), list that command under `## Session hooks` in the project's
`PLAN.md`; `/synapse:plan-session` runs only what is listed there. Project
skills that are not Synapse's own (a deploy or log-triage skill, say) keep
working where they are.

---

## Keep a project in its own store (optional)

One global store is the default. To keep a project's archive, vector DB, and
vault apart, add a store to `~/.claude/synapse/config.toml`:

```toml
[stores.client-x]
path = "~/clients/x/synapse-store"
vault = "Client X"
```

and a `.synapse.toml` at that project's root:

```toml
store = "client-x"
```

Then run `synapse setup` once to create the new store's archive and
`vectors.db`. `synapse where`, run inside the project, confirms which store,
archive, DB, and vault apply and why. `SYNAPSE_STORE=<name>` overrides both for one
session.

## What Synapse writes

| Location | What | Written by |
|----------|------|------------|
| `~/.claude/plugins/` | The plugin itself | Claude Code's installer |
| `~/.claude/settings.json` | `enabledPlugins`, `extraKnownMarketplaces` entries | Claude Code's installer |
| `~/.claude/synapse/` | Config, stores (archives + `vectors.db`), venv | `synapse setup`, `archive`, `extract`, `migrate` |
| `<project>/.claude-work/current/` | `PLAN.md`, `EXECUTION.md` | The agent, during structured work |
| The store's Obsidian vault | `Sessions/`, `Decisions/`, `Patterns/`, `Projects/` notes | `/synapse:extract-session` |

`~/.claude/synapse/` moves with `CLAUDE_CONFIG_DIR`, or anywhere with
`SYNAPSE_HOME`.

## Update

Third-party marketplaces do not auto-update unless the user enables it in
`/plugin`. To update by hand:

```bash
claude plugin update synapse@synapse
```

## Uninstall

```bash
claude plugin uninstall synapse@synapse
```

The rules, skills, and hooks stop loading. `~/.claude/synapse/` stays, because
it holds the user's archives and knowledge base; deleting it is the user's
decision.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Rules do not load in a new session | Plugin disabled, `disableAllHooks`, or managed hooks only | `claude plugin list`; `/synapse:doctor` |
| `synapse: no Python 3.11+ found` | No suitable interpreter on `PATH` | macOS: `brew install python`; Windows: python.org installer, not the Microsoft Store |
| `error: DB not found` from recall | Setup has not run for this store | `/synapse:setup` |
| `cannot reach Ollama` | Ollama is not running | `ollama serve` |
| `is Obsidian running with the 'Synapse' vault open?` | Obsidian closed or another vault open | Open the store's vault in Obsidian |
