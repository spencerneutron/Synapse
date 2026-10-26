---
name: doctor
description: Read-only health and conflict check for Synapse — runtime (Python, venv, vector DB, Ollama, Obsidian), where data resolves, and conflicts with the user's existing setup (same-named skills, competing rules, other Stop hooks, output styles, disabled hooks, old installs, unignored working files). Use after install, when Synapse misbehaves, or before changing the user's Claude Code setup.
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
| output-style | settings `outputStyle` | May contradict the emission contract |
| hooks | `disableAllHooks`, managed `allowManagedHooksOnly` | Synapse's rules and Stop hook never load |
| old-install | `kb/scripts`, `.claude-work/archive`, `.claude-work/kb` in the project and parents | A V1/v1.5 memory system running beside the plugin |
| gitignore | the project's git repo | `.claude-work/` working files would be committed |
| runtime | Python, venv, `vectors.db`, Ollama, `obsidian` CLI, the vault | Memory features degrade without them |

## Output Behavior

Lead with the summary line (counts of ok / info / warn / error), then the warn
and error items with their fixes. Mention info items only when they lead to an
action.
