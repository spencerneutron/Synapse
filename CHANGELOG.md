# Changelog

## Repository, after 2.3.0 — V2 slice A: eval bench

The plugin is unchanged (no runtime file), so the version stays 2.3.0.

- **`tools/run-bench.sh --yes`** runs every eval case with Synapse and
  without it (the no-plugin baseline), building the fixture homes it needs;
  about $6, capped at $13.50, reports local.
- **`tools/eval-report.py`**: with vs without per case and per grader, or
  `--compare OLD NEW`. It scores only graders that count in both arms,
  leaves errored and cost-skipped runs out (and says so), and pairs cases
  for the mean.
- **Two core-loop cases** (`verify-before-done`, `answer-first`); the
  release-gate case now relies on memory alone; `reviewer-minimum` gains a
  scored `finds-bug` grader.
- **Measured on 2.3.0:** 1.00 with Synapse vs 0.71 without, over 15 cases.
  The gain comes from memory (four cases, 0 to 1) and the general-purpose
  brief rule; the other ten cases tie.

## 2.3.0 — 2026-10-26 — V2 slice E: shared memory for a small team

No store schema change. Update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.
Teams are opt-in: nothing changes until `synapse shared init` or `join`.

### Added

- **Teams.** A team shares Decisions and Patterns (never session archives)
  through a folder that reaches every member by **git** (any remote, even a
  bare repo on a NAS) or a **synced folder** (Dropbox, iCloud Drive, SMB).
  Each member keeps a local index rebuilt from the folder by content hash;
  the index is never shared. `synapse shared init | join | sync | status |
  retract | push`.
- **Scrub gate** (`synapse share scrub`, `synapse share lint`). Home and temp
  paths are rewritten; secrets, emails, private IPs, host names, and device
  ids block sharing; session-local references (a bare `#17`, "Wave B",
  "this session"), the user's login name, and text aimed at an agent must
  be reworded. `synapse share lint <folder>` can guard a team repo in CI.
- **`/synapse:share`.** Scrubs each chosen note, rewrites what needs
  judgment, shows only the changed lines, adds only the notes the user
  approves (with `origin`, `author`, `shared_at`, `source_id`; personal
  front matter dropped), and asks before every push. Sharing an edited note
  again replaces its copy.
- **Retraction.** `synapse shared retract` moves a note to `Retracted/` with
  a reason; every member's next sync drops it.
- **Automatic sync.** A `SessionStart` hook starts a background pull and
  re-index at most every 10 minutes. It never prompts for credentials and
  never makes the session wait; a sync failing for 3 days gets one line.
- **Recall and hints include teams.** Shared hits are labeled
  `shared:<team>, <author>`; each list keeps its order and the lists merge
  by score, the store's own result first on a tie, so a weak shared hit
  never displaces a stronger local one. A note you shared shows once.
  `synapse recall --scope all|local|shared`.
- **Inbound gate.** Sync lints every incoming note: one with a secret, an
  identifier, or text aimed at an agent is held back from the index and
  listed by `synapse shared status`; author names are plain labels.
- **Doctor** reports each team: folder, last sync and error, unpushed
  commits, sync-conflict copies.
- **`tools/live-check-share.sh`**: a guarded live check of the share flow
  (eval sessions cannot run the CLI).

### Changed

- **Core rules:** a teammate's note is weighed like any hint, never
  followed as an instruction, and loses to a contradicting local decision
  (say so); share only through `/synapse:share`, per note, and ask before
  every push.
- `/synapse:extract-session` offers `/synapse:share` once when a team is
  configured.
- `tools/run-evals.sh` drops an installed Synapse from PATH, so evals call
  the plugin under test.

### Measured

- Scrub corpus: every planted finding caught, 0 of 25 clean notes blocked.
  On the author's 125 real notes: 7 flagged, all correctly; no false blocks.
- Conflict eval 2/2; live share check 2/2 (scrubbed, asked first, nothing
  added before approval).
- No regression: slice-C and slice-D cases unchanged; golden set identical
  with no team configured.

## 2.2.1 — 2026-10-26 — Windows checkout fix

### Fixed

- **Windows could not clone the repo**, so the plugin could not install
  there: an eval fixture note had `<` and `>` in its file name. Renamed, and
  CI now rejects file names Windows cannot check out.
- **Background-task notifications got recall hints.** They reach the
  `UserPromptSubmit` hook like prompts; prompts that start with a hyphenated
  tag (such as `<task-notification>`) now get no hint.

## 2.2.0 — 2026-10-26 — V2 slice D: deterministic triggers

### Added

- **Automatic recall hints.** A `UserPromptSubmit` hook (`synapse
  recall-hint`) searches the active store for each prompt of four or more
  words that is not a slash command. Hits scoring at least `[recall]
  min_score` (0.70) appear as up to `max_hits` (3) pointers, each shown once
  per session and marked as navigation, not instructions. It is silent when
  anything is missing or broken (store, schema v2, sqlite-vec, Python 3.11+,
  a venv whose interpreter cannot start, Ollama down or slower than 3 s),
  and never blocks a prompt.
- **Pending-extraction reminder.** A `SessionStart` hook (`synapse pending
  --hook`) notes, on startup and `/clear`, archived sessions in this project
  that were never extracted; the session mentions it once and offers
  `/synapse:extract-session`. `synapse pending` lists them by hand.
- **Config switches:** `[recall] auto`, `min_score`, `max_hits`, and
  `[extract] remind` in `config.toml`. A wrong type (for example `auto =
  "false"`) is an error, never a guess. Doctor reports the switches, the
  pending count, config errors, and a home taken from `EVAL_SYNAPSE_HOME`.
- **`tools/run-evals.sh`:** the only documented way to run the eval suite.
  It refuses to start without `--yes`, keeps reports local, and caps cost.
- **Four `slice-d` eval cases** with a synthetic fixture memory
  (`evals/fixtures/memory/`, built by `tools/build_eval_home.py`).

### Changed

- **Core rules:** how to treat an automatic hint (check the source, never
  present a hint as a decision) and the reminder (mention once; never
  extract without the user's go-ahead).
- **`EVAL_SYNAPSE_HOME`** selects the Synapse home when `SYNAPSE_HOME` is
  unset. It exists for eval runs, which pass only `EVAL_*` variables.
- **AGENTS.md:** "run the tests" means unit tests; evals run only when the
  user asks, through the wrapper.

### Measured

- **Threshold** (author's store, 24 unrelated prompts, 17 eligible golden
  queries): at 0.70, 0 of 24 unrelated prompts get a hint, 16 of 17 golden
  queries do, and 15 of 17 hints contain the expected source. Warm hook
  latency: p50 0.18 s, worst 0.19 s.
- **Agent evals** (Sonnet, 2 runs per case): outcome graders 12/12 with
  triggers on, 6/12 off. A convention that lives only in memory was applied
  4/4 on vs 0/4 off; the un-extracted archive was mentioned 2/2 vs 0/2; the
  unrelated task stayed on task in both arms.
- **No regression:** the eight slice-C cases match 2.1 grader for grader.

## 2.1.0 — 2026-10-26 — V2 slice C: role agents

### Added

- **Five role agents**, dispatched as `subagent_type: synapse:<role>`:
  `implementer` (Sonnet; everything but nested agents), `verifier` (Sonnet;
  read + Bash, never edits), `researcher` (Sonnet; read + search + web,
  cites every fact), `reviewer` (inherits the session's model; adversarial,
  never edits), and `scout` (Haiku; exhaustive mechanical sweeps). Each
  body carries the rules its job needs, because sub-agents do not receive
  Synapse's `SessionStart` rules (verified live).
- **Reviewer minimum, suggested:** below the frontier tier, the session
  offers to run reviews on Opus or Fable once per session; a reviewer on a
  small model says so first and recommends a re-run.
- **`evals/`**: an 8-case `claude plugin eval` suite (outcome, discipline,
  and role-dispatch graders) for role agents.
- **Doctor** warns when `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` overrides every
  role's model.

### Changed

- **Core rules:** the waves section names the role agents, says sub-agents do
  not see these rules, and requires a `general-purpose` brief to carry the
  rules it needs. Model-tier prose shrinks to "the agents carry their models".

### Measured (2.0.0 vs 2.1.0, final suite, 8 cases × 2 runs, Sonnet sessions)

- Intended role dispatched: 2/16 -> **16/16**. Files left alone where they
  should be: 12/12 -> 12/12. Outcome graders: 22/24 -> **23/24**; 2.1 matches
  or beats 2.0 on every outcome grader.
- On a Haiku session, the offer of a frontier reviewer appeared in 6 of 7
  runs (2.0: 0 of 4), and the reviewer flagged its own small model in 2 of 3.
- Cost per suite: $1.61 (2.0) and $1.63 (2.1), effectively equal.

## 2.0.0 — 2026-10-26 — V2 slice 1: retrieval quality

Store schema v2: older plugin versions cannot use an upgraded store, so
update every machine that shares one, then run `synapse setup` once.

### Added

- **Hybrid recall.** Every query runs a vector search and an FTS5 keyword
  search, merged by reciprocal rank fusion. Exact names (`QuickAddTracker`,
  `#127`, file names) now surface. Each hit is labeled `vector`, `keyword`, or
  `both`; `--mode vector|keyword|hybrid` picks one search.
- **Supersession.** `synapse extract supersede <old> --by <new>` marks a
  replaced Decision in the DB and in its front matter; recall hides it unless
  `--include-superseded` is passed. `/synapse:extract-session` runs it for
  every Decision written with `supersedes`. Re-embedding keeps the status. It
  edits front matter through the store's `vault_path` and never calls the
  Obsidian CLI.
- **`synapse recall-check <golden.toml>`** scores recall against a golden set
  (hit rate and MRR, overall and per kind), so retrieval changes are measured
  without agent runs.
- **Store schema v2:** filter metadata inside the vector index, an FTS5 index,
  status and `superseded_by` columns, and `origin`/`author` reserved for
  shared stores.

### Changed

- **Filters are exact and run inside the search**, replacing v1.6.1's widening
  loop (kept only for `--since`). `--project` ignores case.
- **`synapse setup` upgrades an older store in place** (`synapse extract
  upgrade`): it backs up `vectors.db` first, rebuilds the indexes from the
  stored vectors without re-embedding, and verifies every vector is unchanged.
  Other commands stop on an old schema and say to run it.

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
