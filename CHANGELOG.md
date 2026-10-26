# Changelog

## 1.6.1 — 2026-10-26

### Fixed

- **Filtered recall came back empty.** `--type` and `--project` filters ran
  after a fixed 20-neighbour search, so in a large store a `--type decision`
  query could return nothing while hundreds of decisions existed. The search
  now widens (×8 per round, up to sqlite-vec's 4,096 limit or the whole DB)
  until enough rows pass the filters. Unfiltered queries are unchanged.
- **Doctor kept suggesting a migration that was already done.** It now checks
  an old archive's sessions against the store and reports a fully migrated
  copy as `ok` (a backup), or how many sessions are still missing.
- **Windows CI.** The SessionStart tests called `bash`, which on GitHub's
  Windows runners resolves to the WSL launcher; they now use Git Bash, as
  Claude Code does.
- INSTALL.md's upgrade notes again cover session hooks for project commands
  that V1's `plan-session` ran, and how to retire V1 files restorably.

## 1.6.0 — 2026-10-26

Packages Synapse as a Claude Code plugin with a global knowledge base. No new
memory or retrieval capabilities; locations and installation change.

### Changed

- **Synapse is a plugin.** The repo is its own marketplace; install with
  `claude plugin install synapse --marketplace spencerneutron/Synapse` at user
  scope, and it applies in every project. Skills are namespaced
  (`/synapse:recall`), so they never collide with a user's own skills.
- **Rules load from a `SessionStart` hook** (`instructions/core.md`, 7,074
  characters, under the 10,000 cap) instead of a workspace `AGENTS.md`, so a
  project's own `CLAUDE.md` no longer hides them. The platform profile is
  picked by OS automatically. Where a project's rules conflict, Synapse defers
  to the project's.
- **One global store in `~/.claude/synapse/`** (archive, `vectors.db`, vault,
  plus the venv), resolved from any folder. V1 depended on the working
  directory and on files sitting next to the kb scripts.
- **Optional per-project stores:** a `.synapse.toml` with `store = "<name>"`
  splits a project's archive, vector DB, and vault together. `SYNAPSE_STORE`
  overrides it for a session.
- **Portable paths in the DB:** chunks record `archive/<project>/…` and
  `vault/<Folder>/…` instead of machine paths.
- **Python 3.11+** (config uses `tomllib`), found by `lib/py.sh`, which
  handles the Windows Store stub and Git Bash paths. The Stop hook no longer
  hard-codes `python3`.

### Added

- `synapse` CLI on the Bash PATH: `where`, `setup`, `doctor`, `archive`,
  `recall`, `extract`, `vault`, `backfill`, `migrate`, `version`.
- `/synapse:setup` (idempotent provisioning) and `/synapse:doctor` (read-only
  health and conflict report covering same-named skills, competing rules,
  other Stop hooks, output styles, disabled hooks, old installs, unignored
  working files).
- `synapse migrate --from <dir>`: copies a V1/v1.5 workspace's archive and
  vectors into the store without re-embedding; idempotent; never writes to
  the source.
- INSTALL.md as an agent-followable runbook (read-only preflight, consent
  points, expected outputs); AGENTS.md is now the guide for working on this
  repo.
- Unit tests, `tools/build_context.py`, and a CI workflow (tests on macOS,
  Linux, and Windows; cap check; personal-path scan; plugin validation).

### Removed

- The workspace-copy install (`docs/setup.md`, `templates/settings.json`,
  `platform/`, `kb/`).

## 1.5 — 2026-10-26

Consolidates V1 into one portable repo. No new memory or retrieval features.

### Changed

- **`AGENTS.md` is the only instruction file.** Claude Code reads it natively
  (2.1.277+), so `CLAUDE.md` is gone. V1's `CLAUDE.md` imported `AGENTS.md`
  and then repeated most of it; the two are now one deduplicated file.
- **OS-neutral core.** Shell conventions moved out of the instructions into
  `platform/macos.md` and `platform/windows.md`, installed as
  `.claude/rules/platform.md`. V1 mandated PowerShell while its memory skills
  said macOS and that the PowerShell rules did not apply.
- **One home for planning files:** `.claude-work/current/`. V1 gave three
  different answers.
- **`/plan-session` is project-neutral.** The hard-wired roadmap sync became
  a generic `## Session hooks` section that any project's `PLAN.md` can list.
- **`recall` and `extract-session` skills** defer to the platform profile
  instead of assuming macOS.
- **Vault name is configurable** with `SYNAPSE_VAULT` (default `Synapse`).
- The Agent tool replaces the old "Task tool" name; example project names in
  `backfill.py` are generic.

### Added

- **Waves and model right-sizing** in `AGENTS.md`: implementation,
  verification, research, and adversarial-review waves, one writer per file
  set, and model tiers per wave. Rebuilt from the V1 design notes. This
  reverses V1's rule that sub-agents never write to the workspace:
  implementation waves now write, one agent per set of files.
- **`emission-contract` skill** (late-bound directive plus exemplars) and the
  **`emission_check.py` Stop hook** with a pattern file. Rebuilt from the V1
  design notes; the originals were not available.
- `AGENTS.md` lifecycle table and a pointer to `/workflow-recovery` for
  interrupted multi-agent runs.
- `templates/` (PLAN, EXECUTION, NOTES, Stop-hook settings), `docs/setup.md`,
  `docs/architecture.md`, `kb/requirements.txt`, and `examples/`.

### Fixed

- `backfill.py` started `extract.py` with a hard-coded `python`, which does
  not exist on stock macOS; it now uses the running interpreter.
- `/recall` no longer offers `--type session` (Session notes are never
  embedded); `vault_write.py`'s docstring shows `note-exists <folder> <name>`.

### Removed

- Project-specific skills (`deploy`, `roadmap-sync`, `device-log-triage`).
  They belong to a single app, not the harness.

## 1.0 — 2026 (unreleased)

The harness as it ran day to day:

- `CLAUDE.md` + `AGENTS.md` instructions.
- Session skills: `/plan-session`, `/end-session`.
- Memory skills: `/recall`, `/extract-session`, backed by `extract.py`,
  `recall.py`, `vault_write.py`, and `backfill.py`.
- `workflow-recovery` and `language-sweep`.
- An emission contract with a Stop hook, and the multi-agent wave rules.
