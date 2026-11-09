---
name: doctor
description: Read-only health and conflict check for Synapse — runtime (Python, venv, vector DB, Ollama, notes), where data resolves, and conflicts with the user's existing setup (same-named skills, competing rules, other Stop, PreCompact, PreToolUse, PostToolUse, and SessionEnd hooks, the auto-compact window, output styles, disabled hooks, old installs, unignored working files). Use after install, when Synapse misbehaves, or before changing the user's Claude Code setup.
allowed-tools: Bash(synapse doctor *), Bash(synapse where *)
---

# Doctor Skill

## Purpose

Tell the user exactly how Synapse sits next to their existing setup, without
changing anything. Synapse never edits files it does not own; this skill turns
each conflict into a finding and a recommendation the user decides on.

---

## Procedure

1. Run `synapse doctor` from the project the user cares about (or pass
   `--project-dir <path>`). Use `--json` if you need to process the output.
2. Group the findings:
   - **error** — Synapse cannot work until this changes (for example,
     `disableAllHooks` is set, or managed settings allow only managed hooks).
   - **warn** — Synapse works, but something will behave unexpectedly
     (a same-named skill, another Stop hook, a missing dependency).
   - **info** — worth knowing (rules files that mention the same topics, an
     old install that can be migrated, a vault path to record).
3. For each warn or error, explain the consequence in one sentence and give
   the fix the report suggests. Ask before applying any fix outside the
   Synapse home (`synapse where` shows it).

## What it checks

| Check | Looks at | Why it matters |
|-------|----------|----------------|
| skills | `~/.claude/skills/`, the project's and its parents' `.claude/skills/` | A skill with a Synapse skill's name loads next to `/synapse:<name>`; the model may pick the other one |
| rules | `~/.claude/CLAUDE.md`, `~/.claude/rules/`, `CLAUDE.md` / `AGENTS.md` / `CLAUDE.local.md` in the project and its parents | Competing always-on rules about planning files, recall, or output |
| stop-hooks | every settings layer, other enabled plugins | Two hooks that block on Stop can both ask for rewrites |
| precompact-hooks | every settings layer, other enabled plugins | Each PreCompact hook's stdout is capped on its own; two sets of compaction instructions can conflict |
| posttooluse-hooks | every settings layer, other enabled plugins | Info only: a PostToolUse hook conflicts with Synapse's nudge only if it blocks or adds its own context on the same calls |
| pretooluse-hooks | every settings layer, other enabled plugins | Info only: another PreToolUse hook conflicts with Synapse's gate only if it also denies or rewrites input on the same calls |
| sessionend-hooks | every settings layer, other enabled plugins | All SessionEnd hooks share one 1.5 s budget; a slow one can cut off Synapse's auto archive |
| autocompact-window | every settings layer (`autoCompactWindow`, also per model under `modelSettings`, `env`), the `CLAUDE_CODE_AUTO_COMPACT_WINDOW` and `ANTHROPIC_MODEL` environment | With no window set, a 1M-context model compacts near 967k tokens and the PreCompact hook rarely runs; info normally, warn when the model name has `[1m]`. Read-only: see the README's "Long sessions". When a window is set, it prints where Claude Code compacts (the window less its 33k buffer) and where Synapse's deny gate, 60% and 90% marks land. |
| output-style | settings `outputStyle` | May contradict the emission contract |
| hooks | `disableAllHooks`, managed `allowManagedHooksOnly` | None of Synapse's hooks load |
| agent-models | `CLAUDE_CODE_SUBAGENT_MODEL` / `_FORCE` in the environment or any settings `env` | A forced sub-agent model silently overrides every role agent's model |
| old-install | `kb/scripts`, `.claude-work/archive`, `.claude-work/kb` in the project and parents | A V1/v1.5 memory system running beside the plugin |
| gitignore | the project's git repo | `.claude-work/` working files would be committed |
| python, venv, vectors, ollama, obsidian, vault, vault_path, notes | Python, venv, `vectors.db` and its schema version, Ollama, `obsidian` CLI, the vault (only the active mode's checks) | Memory features degrade without them; an old schema needs `synapse setup` |
| triggers | `[recall]` and `[extract]` in `config.toml` | Whether automatic recall hints and the pending-extraction reminder are on, and the hint threshold |
| pending | `<store>/archive/<project>/` without a `.processed` marker | Archived sessions recall cannot find until they are extracted |
| teams | each `[shared.<team>]`: its notes folder, last sync, unpushed commits, sync-conflict copies | A team that stopped syncing or has unpushed notes leaves teammates without them |

## Output Behavior

Lead with the summary line (counts of ok / info / warn / error), then the warn
and error items with their fixes. Mention info items only when they lead to an
action.
