# Packaging Synapse (v1.6 design)

Ship Synapse as a Claude Code **plugin** from its own repo-hosted marketplace,
installed at user scope. Always-on rules arrive through `SessionStart` hooks,
user data lives in `~/.claude/synapse/`, and Synapse never edits a file it does
not own. Status: **implemented in v1.6.0** (2026-10-26); the build's
differences from this proposal are listed at the end. Facts below were checked against
code.claude.com/docs and the plugins installed on the author's Mac
(Claude Code 2.1.310).

> **This page records the v1.6 packaging design.** The packaging still holds,
> but later releases added to it: the repo is public; V2 added role agents
> (`agents/`), a `UserPromptSubmit` hook and two more `SessionStart`
> handlers, teams under `~/.claude/synapse/shared/`, and more skills and CLI
> commands. For current behavior read [INSTALL.md](../../INSTALL.md) and
> [architecture.md](../architecture.md); for V2, [v2.md](v2.md).

---

## Why a plugin

| Option | Gives | Lacks | Verdict |
|--------|-------|-------|---------|
| Copy files into a workspace root (v1.5) | Works inside that one folder | Depends on placement and cwd-relative paths; same-named skills overwrite; no update or uninstall path | Replace |
| Copy files into `~/.claude/` (skills, rules, hooks) | Global | Edits the user's `settings.json` hooks; un-namespaced skills collide; no versioning | No |
| **Plugin + own marketplace** | Namespaced skills (`/synapse:recall`), hooks that merge with the user's, `bin/` on the Bash `PATH`, versioned updates, `claude plugin install/uninstall` an agent can run, private-repo access through the user's git credentials, claude.ai org distribution later | No always-on instruction file; `SessionStart` context is capped at 10,000 characters per string | **Adopt** |
| MCP server for memory | Recall and extract as tools usable outside Claude Code; the natural transport for a shared store | Larger surface; not needed for single-user | V2, bundled in the same plugin |

Same pattern in the wild: Cloudflare's skills repo is both the plugin and its
marketplace (`"source": "./"`). Anthropic's `learning-output-style` plugin
injects always-on guidance with a `SessionStart` hook, and `security-guidance`
bootstraps a Python dependency from one.

---

## What goes where

| Artifact | Location | Owner | On uninstall |
|----------|----------|-------|--------------|
| Skills, hooks, `bin/synapse`, Python package, instruction text | `~/.claude/plugins/cache/synapse/synapse/<version>/` | Claude Code | Removed |
| Always-on rules | Injected each session (startup, resume, clear, compact) by `SessionStart`: one handler for the core rules, one for the OS-detected platform profile | Plugin | Stop loading |
| Config, stores (archive + `vectors.db`), venv | `~/.claude/synapse/` (respects `CLAUDE_CONFIG_DIR`) | Synapse | **Kept** — user data |
| Vault | The Obsidian vault named in config (default `Synapse`) | User | Kept |
| Working files | `<project>/.claude-work/current/` | Project | Untouched |

The store does **not** use `${CLAUDE_PLUGIN_DATA}`: Claude Code deletes that
folder on uninstall unless `--keep-data` is passed, and it is not set in the
Bash tool's environment. `~/.claude/synapse/` follows Claude Code's user-scope
location and the `security-guidance` precedent (`~/.claude/security/`).

---

## Stores: global by default, split when needed

One global store unless the user says otherwise. A store is the trio of
archive, vector DB, and vault, so a project can split all three together.

```toml
# ~/.claude/synapse/config.toml
default_store = "main"

[stores.main]
path = "~/.claude/synapse/stores/main"   # archive/<project>/..., vectors.db
vault = "Synapse"

[stores.client-x]                          # optional: only when work must stay apart
path = "~/clients/x/synapse-store"
vault = "Client X"
```

A project opts into another store with a `.synapse.toml` at its root (the
nearest one above the working directory wins):

```toml
store = "client-x"
project = "billing-api"   # optional; defaults to the git root's folder name
```

Precedence: `SYNAPSE_STORE` environment variable, then the nearest
`.synapse.toml`, then `default_store`. Recall searches the active store only.
This is the whole override surface. It maps directly onto V2's shared store: a
store whose path (or, later, MCP endpoint) is shared.

Config needs `tomllib`, so the floor moves to Python 3.11. Python 3.10 reached
end of life this month (2026-10).

---

## "Give me this": the install flow

A user points their session at the repo. The README's "Install with Claude
Code" section sends the agent to `INSTALL.md`, a runbook it follows in order:

1. **Preflight (read-only).** Run the conflict checklist below and report what
   it finds. Ask the user to confirm before continuing.
2. **Install.** These commands add `enabledPlugins` and
   `extraKnownMarketplaces` keys to `~/.claude/settings.json`; disclose that.

   ```bash
   claude plugin install synapse --marketplace spencerneutron/Synapse
   ```

3. **Reload.** Start a new session so the skills and hooks load.
4. **Provision (`/synapse:setup`).** Create `~/.claude/synapse/` with config,
   the `main` store, and a venv with `sqlite-vec`. Ask before
   `ollama pull nomic-embed-text`. Check the vault. Initialize the DB. Offer
   `synapse migrate --from <old workspace>` when a V1 or v1.5 install exists.
5. **Verify (`/synapse:doctor`).** A read-only health and conflict report.
   Rerun any time.

Uninstall: `claude plugin uninstall synapse@synapse`. The store stays; deleting
`~/.claude/synapse/` is the user's call.

While the repo was private (through v1.6.1), step 2 worked only for GitHub
accounts with read access, through `gh auth setup-git` or an SSH key.

---

## Never modify what Synapse doesn't own

Synapse writes only to `~/.claude/synapse/**`, `<project>/.claude-work/**`,
the vault's four folders, and (through Claude Code's installer) the plugin
keys in `settings.json`. Everything else gets a finding and a recommendation,
never an edit. `migrate` copies; it never moves or deletes.

### Conflict checklist (`INSTALL.md` preflight and `/synapse:doctor`)

| # | Look for | Where | Why it matters | Resolution (user's call) |
|---|----------|-------|----------------|--------------------------|
| 1 | Skills named `plan-session`, `end-session`, `recall`, `extract-session`, `emission-contract`, `workflow-recovery`, `language-sweep` | `~/.claude/skills/`, `<project>/.claude/skills/` | Both copies load; the model may pick the un-namespaced one | Remove or rename yours, or keep both knowingly |
| 2 | Competing always-on rules: planning-file conventions, output-style rules, other memory systems | `~/.claude/CLAUDE.md`, `~/.claude/rules/`, project `CLAUDE.md` / `AGENTS.md` | Contradictory instructions every session | Reconcile by hand |
| 3 | Other `Stop` hooks that block (`"decision": "block"` or exit 2) | Every `settings.json` layer, other plugins | Stacked rewrite requests | Review the overlap |
| 4 | `outputStyle` set | Settings | May fight the emission contract | Pick one |
| 5 | `disableAllHooks` or `allowManagedHooksOnly` | Any settings layer, managed settings | Synapse's rules and Stop hook never load | Not supported; ask the admin |
| 6 | An existing V1 or v1.5 install (`kb/scripts`, `.claude-work/archive`, `vectors.db`) | Any workspace root | Two memory systems | `synapse migrate --from <dir>` (copies) |
| 7 | An existing `~/.claude/synapse/` | User config dir | Earlier install | `setup` reuses it and never overwrites |
| 8 | An Obsidian vault already named `Synapse` holding other notes | Obsidian | Mixed notes | Choose another vault name |
| 9 | Python 3.11+, Ollama with `nomic-embed-text`, the `obsidian` CLI | `PATH` | Memory features degrade | Install them |
| 10 | `.claude-work/` not ignored in a repo | Project `.gitignore` | Working files get committed | Add it (ask first) |

---

## Repository layout after v1.6

```
.claude-plugin/          plugin.json (version, userConfig-free), marketplace.json ("source": "./")
instructions/            core.md, platform-macos.md, platform-windows.md (each < 10,000 chars, CI-checked)
hooks/                   hooks.json, session_start.sh, context/*.json, emission_check.py, emission_patterns.json
bin/synapse              CLI on the Bash PATH: where, setup, doctor, archive, recall, extract, vault, backfill, migrate
lib/py.sh                Python launcher (see below)
lib/synapse/             config resolver + the four v1.5 scripts as modules (no cwd-relative paths)
skills/                  the seven v1.5 skills + setup + doctor
templates/  docs/  examples/
README.md                humans, plus an "Install with Claude Code" section
INSTALL.md               the agent runbook above
AGENTS.md                guide for agents working on this repo (no longer the harness rules)
```

`py.sh` adapts the `security-guidance` launcher: it finds a working Python 3.11+
across macOS, Linux, and Windows Git Bash (skipping the Microsoft Store stub)
and sets `PYTHONUTF8=1`. That also fixes v1.5's hard-coded `python3` in the
Stop hook command.

## Release practice

- `version` in `plugin.json`, bumped per release (users get updates only when it
  changes); `claude plugin tag` for `synapse--v1.6.0` tags.
- CI: `claude plugin validate --strict`, the 10,000-character check on
  `instructions/`, the hook tests, and a scan for personal paths.
- Third-party marketplaces do not auto-update by default; the README documents
  `claude plugin update synapse@synapse`.

## Decisions

1. **Rules delivery:** `SessionStart` hooks (recommended: lifecycle follows the
   plugin, updates with it) or a `~/.claude/rules/synapse.md` file written by
   setup (no size cap, but orphaned on uninstall and frozen at install time).
2. **Data home:** `~/.claude/synapse/` (recommended) or `~/.synapse/`.
3. **Label:** v1.6, because it changes packaging and locations, not
   capabilities; V2 keeps the capability seams.

## Deferred to V2

MCP memory server and shared stores (behind the scrubbing gate in
`architecture.md`), Harness Bench on `claude plugin eval`, and manifests for
other agent tools (Cursor, Codex).

Outcome ([v2.md](v2.md)): shared stores became teams in slice E (2.3.0),
through a git repo or a synced folder rather than an MCP server; the bench
became slice A. The MCP server and other agents' manifests are slice F,
not yet built.

## As built (v1.6.0)

- **One-step install.** Claude Code installs from a marketplace source in one
  command (`claude plugin install … --marketplace`, 2.1.292+; the in-session
  `/plugin install` form from 2.1.275), so INSTALL.md leads with it and keeps
  the two-step form for older versions.
- **No `userConfig`.** Options reach skills and the Bash tool more reliably
  from `~/.claude/synapse/config.toml` than from plugin options, so the
  manifest declares none.
- **Session archiving moved into the CLI.** `synapse archive` copies the
  working files and picks the session ID; the skill keeps the judgment work
  (notes, open questions).
- **The venv lives in the Synapse home** (`~/.claude/synapse/venv`), next to
  the stores, for the same reason as the data: the plugin data folder is
  deleted on uninstall and is not visible to the Bash tool.
- **Migration merges vectors without re-embedding.** `synapse migrate` copies
  V1 chunks with their vectors, rewrites their source paths to the portable
  form, and recomputes the dedup hash, so two old workspaces that embedded the
  same files merge cleanly.
- **Linux gets no platform profile yet**; the core rules still load.

