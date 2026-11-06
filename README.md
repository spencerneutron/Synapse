# Synapse

A Claude Code plugin that gives every session the same operating loop: plan,
execute in small verified steps, archive the working state, and promote
durable decisions into a local knowledge base the next session can recall.
It installs once for the whole machine and works in every project.

**Version:** 2.6.0 (2026-11-06). See [CHANGELOG.md](CHANGELOG.md).

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
   each carrying its own rules and model. A sixth role, `synapse:extractor`,
   is dispatched by `/synapse:extract-session`.
3. **Emit:** the `synapse:emission-contract` skill shapes each final message,
   and a Stop hook enforces its mechanical rules.
4. **Checkpoint (any time):** `/synapse:checkpoint` writes a `## Resume`
   section in `EXECUTION.md` and the working `NOTES.md`, and work goes on.
   `/synapse:end-session` later archives them.
5. **Archive:** `/synapse:end-session` copies the planning files into the
   store and writes session notes.
6. **Extract:** `/synapse:extract-session` promotes Decisions, Patterns,
   and Facts (what the user stated about the project) to an Obsidian vault
   and embeds the session in the vector DB. A new session lists the
   project's Facts, and says so when an archived session was never
   extracted.
7. **Recall:** later sessions, in any project, get ranked pointers into that
   history: automatically, when a prompt closely matches something in the
   store, and on demand with `/synapse:recall`.
8. **Share (optional):** `/synapse:share` gives a team chosen Decisions,
   Patterns, and Facts, scrubbed of paths, secrets, and session-local references,
   through a git repo or a synced folder. Teammates' notes join recall,
   labeled; your own note wins a tie, and your own decision wins a conflict.

## Long sessions

On a model with a 1M-token window (the Fable models, Sonnet 5 and later,
Haiku 5.5, Opus 4.7 and later), Claude Code's default auto-compact threshold
is about 967k tokens, and in practice compactions on the maintainer's
machines ran anywhere from 307k to 968k. Synapse's PreCompact hook, which
shapes the compaction summary, runs only at compaction, so a session that
stays below the threshold does not use it. A long session also re-reads its
whole context on every request: across seven measured sessions on two
machines, the main session was 79 to 100 percent of cost (100 where no
sub-agents ran). Consider lowering the auto-compact window to about 300k, which makes compaction predictable with
`/autocompact 300k`, the `autoCompactWindow` setting, or the
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` environment variable (the variable wins over
the other two). The trade-off: each compaction is lossy and costs one large
request. Synapse never changes this setting; `/synapse:doctor` reports it.

Before a long session gets heavy, run `/synapse:checkpoint`. It saves what
the work needs to continue (a `## Resume` section and the session's notes)
and does not end the turn. After a checkpoint, `/clear` is free: the next
session starts from the files. `/compact` is lossy, because it keeps only a
summary.

- **Resume pointer.** After `/clear` or a compaction, the session start adds
  one line that names the `## Resume` section and when it was written. It
  only points; you or Claude read the file.
- **Context nudge.** The nudge hook measures the real context size and adds
  one line at 60% and at 90% of `[nudge] context_window` (default 300000
  tokens). If you were away longer than the prompt cache lasts, it also says
  what the next request will rewrite. Set `context_window` to your
  auto-compact window: on a 200k-window model the default's 180k mark sits
  at the compaction point, so lower it (for example 150000) or the lines
  never show. It is checked after Bash, PowerShell, Edit, Write and Agent
  calls, not after reads. Set `context_window = 0` to turn both off.
  Neither line blocks anything.

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
agents/           implementer, verifier, researcher, reviewer, scout, extractor (synapse:<role> sub-agents)
hooks/            hooks.json (SessionStart, UserPromptSubmit, PreCompact, PostToolUse, Stop), session_start.sh,
                  context/*.json, emission_check.py
bin/synapse       CLI on the Bash PATH: where, setup, doctor, archive, recall,
                  recall-check, recall-hint, pending, compact-guide, nudge, checkpoint, share, shared, extract
                  (incl. check-candidates), vault,
                  backfill, migrate
lib/              py.sh (finds Python 3.11+), synapse/ (resolver + memory pipeline)
skills/           plan-session, checkpoint, end-session, recall, extract-session, share, emission-contract,
                  workflow-recovery, language-sweep, setup, doctor
templates/        PLAN.md, EXECUTION.md, NOTES.md
tools/            build_context.py (rebuilds hooks/context from instructions/),
                  run-evals.sh (guarded eval runner), run-bench.sh (with vs without
                  Synapse), eval-report.py, build_eval_home.py, live-check-share.sh,
                  live-check-extract.sh, live-check-compact.sh, context-cost.py
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
