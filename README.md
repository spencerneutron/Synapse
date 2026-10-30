# Synapse

A Claude Code plugin that gives every session the same operating loop: plan,
execute in small verified steps, archive the working state, and promote
durable decisions into a local knowledge base the next session can recall.
It installs once for the whole machine and works in every project.

**Version:** 2.3.1 (2026-10-30). See [CHANGELOG.md](CHANGELOG.md).

## Install

```bash
claude plugin install synapse --marketplace spencerneutron/Synapse
```

Then, in a new Claude Code session, run `/synapse:setup` and `/synapse:doctor`.

To update an installed copy:

```bash
claude plugin marketplace update synapse
```

```bash
claude plugin update synapse@synapse
```

Then start a new session and run `synapse setup` once (see
[INSTALL.md](INSTALL.md#update)).

### Install with Claude Code

Tell Claude: *"Install Synapse from github.com/spencerneutron/Synapse."*
It follows [INSTALL.md](INSTALL.md): a read-only check of the existing setup
first, then the install, provisioning, and verification, asking before each
change. Synapse never edits what it does not own; overlaps with an existing
setup are reported for the user to decide.

## How a session runs

1. **Plan:** `/synapse:plan-session` reads or starts `PLAN.md` and
   `EXECUTION.md`, runs the project's session hooks, and calls
   `/synapse:recall` when the work resembles past work.
2. **Execute:** small steps, each with a run path, an expected outcome, and a
   failure signal. Independent work runs as waves of Synapse's role agents
   (`synapse:implementer`, `verifier`, `researcher`, `reviewer`, `scout`),
   each carrying its own rules and model.
3. **Emit:** the `synapse:emission-contract` skill shapes each final message,
   and a Stop hook enforces its mechanical rules.
4. **Archive:** `/synapse:end-session` copies the planning files into the
   store and writes session notes.
5. **Extract:** `/synapse:extract-session` promotes Decisions and Patterns to
   an Obsidian vault and embeds the session in the vector DB. A new session
   says so when an archived session was never extracted.
6. **Recall:** later sessions, in any project, get ranked pointers into that
   history: automatically, when a prompt closely matches something in the
   store, and on demand with `/synapse:recall`.
7. **Share (optional):** `/synapse:share` gives a team chosen Decisions and
   Patterns, scrubbed of paths, secrets, and session-local references,
   through a git repo or a synced folder. Teammates' notes join recall,
   labeled; your own note wins a tie, and your own decision wins a conflict.

## Where things live

- **Rules** load at every session start from the plugin's `SessionStart`
  hook: the core rules, plus a macOS or Windows profile picked automatically.
- **Data** lives in `~/.claude/synapse/`: one global store by default (archive,
  `vectors.db`, and an Obsidian vault). A project can opt into its own store
  with a one-line `.synapse.toml`; see [INSTALL.md](INSTALL.md).
- **Teams** (optional): a shared notes folder per team, plus a local index
  rebuilt from it; see [INSTALL.md](INSTALL.md#share-with-a-team-optional).
- **Everything stays local:** sqlite-vec, Ollama embeddings, and Obsidian.
  Only notes you approve for a team leave the machine.

## Layout

```
.claude-plugin/   plugin.json, marketplace.json (this repo is its own marketplace)
instructions/     core.md, platform-macos.md, platform-windows.md (each < 10,000 chars)
agents/           implementer, verifier, researcher, reviewer, scout (synapse:<role> sub-agents)
hooks/            hooks.json (SessionStart, UserPromptSubmit, Stop), session_start.sh,
                  context/*.json, emission_check.py
bin/synapse       CLI on the Bash PATH: where, setup, doctor, archive, recall,
                  recall-check, recall-hint, pending, share, shared, extract, vault,
                  backfill, migrate
lib/              py.sh (finds Python 3.11+), synapse/ (resolver + memory pipeline)
skills/           plan-session, end-session, recall, extract-session, share, emission-contract,
                  workflow-recovery, language-sweep, setup, doctor
templates/        PLAN.md, EXECUTION.md, NOTES.md
tools/            build_context.py (rebuilds hooks/context from instructions/),
                  run-evals.sh (guarded eval runner), run-bench.sh (with vs without
                  Synapse), eval-report.py, build_eval_home.py, live-check-share.sh
tests/            unit tests (python -m unittest discover -s tests)
evals/            claude plugin eval suite with a no-plugin baseline (core loop, role agents,
                  triggers, teams; run locally, results gitignored)
docs/             architecture.md, design/packaging.md, design/v2.md
examples/         real PLAN/EXECUTION files from a mature project
```

## Learn more

- [INSTALL.md](INSTALL.md): install, provision, migrate, split stores, share
  with a team, update, uninstall
- [docs/architecture.md](docs/architecture.md): lifecycle, components,
  principles, and the V2 roadmap
- [docs/design/packaging.md](docs/design/packaging.md): why a plugin, and how
  install stays non-destructive
- [docs/design/v2.md](docs/design/v2.md): the V2 plan, slice by slice, with
  measurements
- [AGENTS.md](AGENTS.md): working on this repo

## License

MIT. See [LICENSE](LICENSE).
