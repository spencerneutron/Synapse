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
| PostToolUse | Below that threshold, a reminder at the same counts; a context-size line at 60% and 90% of the window |
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

## Documentation

- [INSTALL.md](INSTALL.md): requirements, preflight, install, provision, verify, per-project stores, reminders, teams, update, uninstall.
- [docs/architecture.md](docs/architecture.md): session lifecycle, components including the hooks, operating principles, [repository layout](docs/architecture.md#repository-layout).
- [docs/design/](docs/design/): design records.
- [CHANGELOG.md](CHANGELOG.md): what changed in each version.
- [AGENTS.md](AGENTS.md): working on this repository.
- [evals/](evals/): how the plugin is measured.
