# Synapse

Synapse is a Claude Code plugin that gives every session a working method and a memory. The method is a planning and delegation loop: the main session plans, briefs role sub-agents for anything beyond a handful of calls, and ends each turn with a message that meets a fixed contract. The memory is a local store that archives every session, distils it into Obsidian notes and a vector index, and brings the relevant parts back at the start of the next session, in this project or another. Hooks enforce the method and the `synapse` CLI does the bookkeeping, so the model's attention stays on the work.

Install, then provision and check from a new session:

```bash
claude plugin install synapse --marketplace spencerneutron/Synapse
```

```
/synapse:setup
/synapse:doctor
```

[INSTALL.md](INSTALL.md) lists the requirements (Python 3.11+, Ollama with `nomic-embed-text`, Obsidian), the preflight for an existing Claude Code setup, and the install forms for older Claude Code builds.

## A session

1. **Plan.** `/synapse:plan-session` reads or starts `PLAN.md` (strategy, constraints, decision log) and `EXECUTION.md` (the active task and its next steps) under `.claude-work/current/`. When the work resembles past work, `/synapse:recall` returns ranked snippets from the store with source paths; a hook adds the same kind of hint to a prompt on its own.
2. **Execute.** The main session keeps the work that takes a handful of calls: dialogue, decisions, the planning files, briefs, and reading reports. Anything over about five tool calls or three files is a brief to a role, which runs as a sub-agent carrying its own rules:

   | `subagent_type` | Use for | Model | Writes? |
   |---|---|---|---|
   | `synapse:implementer` | One planned change, validated | Sonnet | Yes, one writer per set of files |
   | `synapse:verifier` | Check claims against evidence; run tests | Sonnet | No |
   | `synapse:researcher` | Answer a question from code, docs, or the web, with sources | Sonnet | No |
   | `synapse:reviewer` | Adversarial review of a change or plan | Inherits the session's | No |
   | `synapse:scout` | Mechanical sweeps: inventories, searches | Haiku | No |

   Independent briefs run as a wave. Every report is a claim: the main session runs its validation once before reporting the work as done.
3. **Emit.** Every final message meets the emission contract: no praise or filler openers, no pleasantry, recap or offer closers, no tic words, placeholders or emoji, and a cap on headings in a short message. The Stop hook checks it and asks for one rewrite when it fails; `synapse:emission-contract` holds the reference text.
4. **Checkpoint.** `/synapse:checkpoint` writes the live state to `EXECUTION.md` and `NOTES.md` without ending the turn: between stages, before stepping away, or when the Stop gate asks. After it, `/clear` loses nothing.
5. **End.** `/synapse:end-session` writes the session notes (open questions, deferred items, why the pivots happened) from live context, archives the working files under a session ID, and runs extraction last in the same turn. Extraction writes notes without asking by default; `synapse extract review` lists what it wrote.
6. **Next session.** The start hook lists the project's Fact notes, and recall ranks the archived sessions, decisions and patterns against the new prompt.

If a session ends without `/synapse:end-session` (a crash, a forgotten close, `/clear`), the SessionEnd hook archives the working files as they stand, and the next session start says archives are waiting and offers `/synapse:extract-session`.

## What runs without you

| Hook | What it does |
|---|---|
| SessionStart | Loads the rules and the platform notes, lists the project's Facts, reports archives never extracted and notes written by automatic extraction, starts a due team sync |
| UserPromptSubmit | Adds a recall hint (up to three ranked snippets above a score threshold) and a one-line digest of the delegation rule |
| PreToolUse | Above half the context window, denies the next hands-on call once at the fifth, tenth and twentieth call of a step and names the role to brief; the retry goes through, and a dispatch or a new prompt resets the count |
| PostToolUse, PostToolUseFailure | Below that threshold, a reminder at the same counts; a context-size line at 60% and 90% of the window |
| Stop | The emission contract, with one rewrite; a checkpoint ask once at 60% and once at 90% of the window; a hold while a dispatched sub-agent is still running |
| PreCompact | Guidance for the compaction summary: what to keep, which planning files exist, where the resume state is |
| SessionEnd | The failsafe archive of the working files at exit, `/clear` and `/resume`, with no model call |

Rules in a prompt decay as the context fills; hooks hold at any context size, which is why the contract, the gate and the archive are enforced rather than requested. [docs/architecture.md](docs/architecture.md#operating-principles) states the principles.

## Memory

A store is one folder: `archive/<project>/` holds the archived sessions, `vectors.db` the embeddings, and an Obsidian vault the notes. Extraction reads an archived session and writes Session, Decision, Pattern and Fact notes to the vault, embedded with `nomic-embed-text` through Ollama. Recall ranks those notes and archives against a query and returns snippets with source paths; they are navigation hints, so the model reads a source before relying on it. Fact notes (what the user stated about the project: deploy targets, customers, constraints) are listed at every session start. Every Artifact a session publishes is recorded by the Stop hook and lands in its Session note as a link, under `## Artifacts` and in the `artifacts` property, which the vault's `Artifacts.base` lists across sessions.

One global store, `main`, serves every project by default; a project opts into its own store with a `.synapse.toml` at its root. The Synapse home is `~/.claude/synapse` (`SYNAPSE_HOME` overrides it), and `synapse where` prints where this folder's data resolves. `/synapse:share` scrubs Decision, Pattern and Fact notes and adds the ones the user approves to a team folder or git repository; teammates' notes appear in recall labelled with team and author.

## Configuration

`config.toml` in the Synapse home holds the defaults below; a project's `.synapse.toml` overrides `[nudge]` and `[gate]`.

| Setting | Default | Effect |
|---|---|---|
| `[nudge] calls` | 5 | Hands-on calls per step before the reminder and the gate; 0 turns the reminder off |
| `[nudge] context_window` | unset | Window the context marks are measured against; unset reads Claude Code's auto-compact setting, else the model's default |
| `[gate] enabled`, `min_context` | true, 0.5 | The deny, and the context fraction above which it applies |
| `[gate] checkpoint`, `wait_for_agents` | true, true | The Stop checkpoint ask and the hold for a running sub-agent |
| `[extract] accept` | auto | `auto` writes notes and lists them for review; `review` asks before writing |
| `[extract] on_exit` | false | Detached extraction after the failsafe archive |
| `[extract] artifacts` | true | Record published Artifact links for the Session note |
| `[archive] on_exit` | true | The failsafe archive |
| `[recall] auto`, `min_score`, `max_hits` | true, 0.70, 3 | The prompt hint |

The context marks sit on the auto-compaction point. `synapse setup --autocompact 300k` sets Claude Code's window after backing up `settings.json`; a 300k window compacts near 267k, with the gate from 134k and the checkpoint asks at 160k and 240k. [INSTALL.md](INSTALL.md) covers the rest.

## Cost

Model turns cost money; hooks and the CLI run locally and cost nothing. Each main-session call re-reads the whole context, so a long hands-on loop in the main session is the expensive pattern, and the gate exists for that: a role runs the loop in a fresh, small context and sends back a report. `tools/context-cost.py` reads Claude Code transcripts and prints token and cost numbers per session; `tools/emission-stats.py` counts Stop-hook verdicts per turn.

## Security and data

Synapse runs on your machine and keeps what it stores there: SQLite, an Obsidian vault, and Ollama for embeddings. `synapse where` prints every directory below for the current folder. It works only in Claude Code (hooks and a Bash CLI), not in claude.ai or Cowork.

- **What it keeps from your sessions.** Synapse is a memory: it stores notes derived from the conversation and brings them back in later sessions. The model writes them under the skills' rules: `/synapse:plan-session` creates `PLAN.md` and `EXECUTION.md` in the project's `.claude-work/current/`; `/synapse:checkpoint` updates them and appends to `NOTES.md` there; `/synapse:end-session` writes `NOTES_<id>.md` (open questions, decisions, facts the user stated) straight into the store's archive. The Stop hook records the title and link of each Artifact the session published in `ARTIFACTS.md`. The archive copies the working files into the store; extraction turns the archive into vault notes (Session, Decision, Pattern, Fact) and into `vectors.db`, which holds each chunk's text, its embedding and a full-text index. Recall hints, the Facts list and the resume pointer put that text back into later sessions' context, so it reaches the model like anything else in the session. Synapse does not copy transcripts.
- **What the hooks read.** Each hook runs `bash` on a file in the plugin folder (table above). Hooks read the event on stdin, the tail of the session transcript (token counts and model, timestamps, the turn's Artifact tool calls and results), and the planning files; the Stop hooks read the final message for the emission check and for Artifact links. The recall hint embeds the first 1,000 characters of each prompt through local Ollama and stores only which notes it showed. Timeouts are 2 to 15 seconds. Without Python the rules still load and the other hooks exit silently, except the emission check, which reports the missing Python.
- **Other files it reads.** Claude Code's settings layers (user, project, local, managed) for the auto-compact window. `synapse doctor` also reads the `CLAUDE.md`/`AGENTS.md` rule files and skills folders, `installed_plugins.json` and other plugins' `hooks.json`, and Obsidian's vault list, to report overlaps. `/synapse:workflow-recovery` reads a dead workflow's journal and agent transcripts under `~/.claude/projects/`.
- **Python.** `synapse setup` creates a venv in the Synapse home and installs one package, `sqlite-vec`, from PyPI. `/synapse:setup` runs `ollama pull nomic-embed-text` (about 270 MB) after you agree. Everything else is the standard library.
- **Network.** Ollama on `localhost:11434`. PyPI and the Ollama model registry during setup. For a git team you created or joined: `git clone` on join, `git pull --ff-only` in the background at session start when a sync is due (`auto_sync = false` turns it off), and `git pull --rebase` then `git push` on `synapse shared push`, which the rules run only after you say yes. No telemetry and no other host.
- **Detached extraction (off by default).** With `[extract] on_exit = true`, the SessionEnd hook starts a headless `claude -p "/synapse:extract-session …"` on Sonnet in the project folder, with hooks off and only these tools pre-approved: `Bash(synapse extract|vault|where|shared status …)`, `Read`, `Write`, `Agent`. It uses your Claude login, costs model tokens, and logs to `state/extract-<id>.log` in the Synapse home.
- **Local apps.** The optional Obsidian CLI (`obsidian vault info`, `obsidian search`) finds and searches the vault; on macOS and Windows Synapse starts Obsidian when it is not running. Notes are written as files, not through the CLI.
- **Writes.** The Synapse home (`synapse` under `$CLAUDE_CONFIG_DIR` or `~/.claude`; `SYNAPSE_HOME` overrides it): config, venv, `state/` (hint, nudge and sync state, logs), the default store (archives, `vectors.db` and its backups, review and processed markers), git team clones. A store or team configured with its own `path`. The project's `.claude-work/`. The store's vault, wherever `vault_path` points. A folder team's shared notes folder.
- **Claude Code settings.** Only `synapse setup --autocompact N` writes to Claude Code's `settings.json`: it adds `autoCompactWindow`, refuses when one is already set, and copies the file to `settings.json.synapse-backup-<time>` first. Nothing runs it automatically.
- **Removal.** [INSTALL.md](INSTALL.md#uninstall) covers uninstall. Deleting the Synapse home removes the default store and the team clones under it; stores and teams with their own `path`, vaults, and notes already pushed to a team stay. [docs/PRIVACY.md](docs/PRIVACY.md) and [docs/TERMS.md](docs/TERMS.md) restate this as a privacy policy and terms.

## Documentation

- [INSTALL.md](INSTALL.md): requirements, preflight, install, provision, verify, per-project stores, reminders, teams, update, uninstall.
- [docs/architecture.md](docs/architecture.md): session lifecycle, components including the hooks, operating principles, [repository layout](docs/architecture.md#repository-layout).
- [docs/design/](docs/design/): design records.
- [CHANGELOG.md](CHANGELOG.md): what changed in each version.
- [AGENTS.md](AGENTS.md): working on this repository.
- [evals/](evals/): how the plugin is measured.
