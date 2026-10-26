# Synapse

An operating layer for Claude Code in a multi-repo workspace. Every
non-trivial session plans, executes in small verified steps, archives its
working state, and promotes durable decisions into a local knowledge base that
the next session can recall.

**Version:** 1.5 (2026-10-26). See [CHANGELOG.md](CHANGELOG.md).

## How a session runs

1. **Plan:** `/plan-session` reads or starts `PLAN.md` and `EXECUTION.md`,
   runs the project's session hooks, and calls `/recall` when the work
   resembles past work.
2. **Execute:** small steps, each with a run path, an expected outcome, and a
   failure signal. Independent work runs as waves of sub-agents, with the
   model sized to each wave.
3. **Emit:** the `emission-contract` skill shapes each final message, and a
   Stop hook enforces its mechanical rules.
4. **Archive:** `/end-session` copies the planning files to
   `.claude-work/archive/` and writes session notes.
5. **Extract:** `/extract-session` promotes Decisions and Patterns to an
   Obsidian vault and embeds the session into a local vector DB.
6. **Recall:** later sessions get ranked pointers into that history.

Everything stays on the machine: sqlite-vec, Ollama embeddings, and an
Obsidian vault.

## Layout

```
AGENTS.md                 the only instruction file (Claude Code reads it natively)
platform/                 shell conventions → installed as .claude/rules/platform.md
  macos.md
  windows.md
.claude/
  skills/                 plan-session, end-session, recall, extract-session,
                          emission-contract, workflow-recovery, language-sweep
  hooks/                  emission_check.py + emission_patterns.json (Stop hook)
kb/
  scripts/                extract.py, recall.py, vault_write.py, backfill.py
  requirements.txt
templates/                PLAN.md, EXECUTION.md, NOTES.md, settings.json (hook registration)
docs/
  setup.md                install into a workspace root
  architecture.md         lifecycle, components, principles, loop diagram, V2 seams
examples/                 real PLAN/EXECUTION files from a mature project
```

## Install

See [docs/setup.md](docs/setup.md). In short: copy the harness into your
workspace root, install a platform profile as `.claude/rules/platform.md`,
register the Stop hook, then build the venv, pull `nomic-embed-text`, and
point it at an Obsidian vault.

Requires Claude Code 2.1.277 or later, Python 3.10+, Ollama, and Obsidian.

## What's next

V2 turns the remaining instruction-driven seams into deterministic ones: hook-
driven recall, chained extraction, agent definition files for wave roles,
supersession, hybrid retrieval, and a benchmark. See
[docs/architecture.md](docs/architecture.md#toward-v2).
