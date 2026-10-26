# Synapse rules

Synapse is installed as a Claude Code plugin. These rules load at the start of
every session; its skills are `/synapse:<name>`, and its `synapse` command is
on the Bash PATH. Where a project's own instructions conflict with these
rules, follow the project's and say so once.

---

## Session Lifecycle

Every non-trivial session runs the same loop. Skills describe *how*; these
rules decide *when*.

| Stage | Skill | When |
|-------|-------|------|
| Plan | `/synapse:plan-session` | Starting or resuming structured, multi-step work |
| Recall | `/synapse:recall` | See "Local Knowledge Recall" below |
| Execute | (these rules) | Small verified steps, in waves when the work splits |
| Emit | `synapse:emission-contract` | Before the final user-facing message of every turn |
| Archive | `/synapse:end-session` | The session itself is closing, not just a task |
| Extract | `/synapse:extract-session` | After `/synapse:end-session`, once the user agrees |
| Recover | `/synapse:workflow-recovery` | A background workflow or agent fleet died or was stopped |

---

## Core Operating Principles

- Always plan before executing.
- Prefer small, verifiable steps over large speculative changes.
- Explore the repository before making assumptions.
- Reuse existing patterns wherever possible.
- Avoid unnecessary rework or repeated analysis.

---

## Planning Discipline

Before making changes: identify the objective, explore the repository for
relevant patterns, write a step-by-step plan, check that it produces an
observable outcome, and execute only once it is coherent and minimal.

During execution: re-evaluate after each step, update progress explicitly, and
stop if uncertainty becomes high.

---

## Planning Files

Working files live in the project, under `.claude-work/current/`:

- `PLAN.md` — long-lived strategy, constraints, Decision Log.
- `EXECUTION.md` — the active task and its immediate next steps.

Archives, the vector DB, and the vault belong to the active Synapse store.
Run `synapse where` to see them; never hard-code those paths.

- Read `PLAN.md` once at session start, or when direction is unclear.
- Read `EXECUTION.md` at the start of each task, or when resuming work.
- Do not re-read either after every step; assume they are unchanged unless you
  updated them.
- If the two conflict, follow `EXECUTION.md` and update `PLAN.md` to match.
- Update `EXECUTION.md` often. Update `PLAN.md` only for a durable decision, a
  scope or approach change, or a reusable insight.

If the files do not exist, proceed normally; create them only when the task's
complexity justifies structured planning.

---

## Repository Exploration and Execution

- Search for similar functionality and existing conventions first; modify
  existing structures before introducing new ones.
- Make the smallest change that achieves the objective. Keep it localized,
  testable, and observable. No speculative or unrelated refactors.

## Validation Requirements

Every meaningful change carries a way to run or test it, a clear expected
outcome, and a failure signal if it is wrong.

---

## Token / Context Discipline

- Do not restate large documents; load only relevant files and do not re-read
  unchanged ones.
- Summarize findings before acting.
- Cache conclusions in `PLAN.md` (Decision Log) instead of recomputing them.

## Parallel Tool Use

Batch independent reads, searches, and commands into one call: exploring a
repo, gathering evidence across files, checking several sources before a
decision. Do not batch when later calls depend on earlier output, for
destructive operations, or when batching hides which call produced what.

---

## Sub-agents and Waves

Use sub-agents (the Agent tool) for bounded work that would otherwise blow the
context or run serially: searching several repos for a pattern, extracting the
relevant parts of a large file, auditing a tree. A sub-agent returns a summary,
not a transcript. Not a fit: work that needs dialogue with the user, depends on
this session's full context, or is a single read or grep.

Once the plan is set and the work splits into independent parts, run it as
waves of role-specific agents:

| Wave | Job | Writes? |
|------|-----|---------|
| Implementation | Make one planned change each | Yes — one writer per set of files |
| Verification | Build, test, and check the change across affected repos | No |
| Research | Answer an open question from docs, code, or the web | No |
| Adversarial review | Try to break the change or the plan with fresh eyes | No |

- Give each agent a self-contained brief: goal, files, what done looks like,
  and what is already ruled out.
- Never let two writers touch the same files; use an isolated worktree when
  edits could overlap.
- Treat every result as a claim and verify it before reporting it as done.
- Record what each wave returned in `EXECUTION.md`.

**Model right-sizing.** Frontier models plan; right-sized models execute.
Frontier (Opus, as of 2026-10) for planning, architecture, adversarial review,
and ambiguous debugging; mid (Sonnet) for implementation and verification
against a clear brief; small (Haiku) for mechanical search and extraction.
Pass the tier through the Agent tool's `model` option. Escalate one tier when a
result fails verification twice.

**Interrupted runs.** If a background workflow or fleet stops early, run
`/synapse:workflow-recovery` before relaunching anything.

---

## Local Knowledge Recall

`/synapse:recall` searches past sessions, decisions, and patterns in the active
store and returns ranked snippets with source paths.

Invoke it proactively when planning work that resembles prior work, when a
decision may have been made before, when the user says "last time", "before",
or similar, when debugging something that may have been seen before, or when
entering a project area with session history. Skip it for self-contained, novel
tasks, when `EXECUTION.md` already has the context, or when the topic was
already recalled this session.

Treat results as navigation hints, not context: read a source only if its
snippet is relevant, and never paste recall output into planning files. Cite
the path and paraphrase.

---

## Emission

At the end of every turn, load the `synapse:emission-contract` skill
immediately before writing the user-facing message, and follow it for that
message only. Its rules stay out of the context while the work happens; the
plugin's Stop hook checks the message and asks for one rewrite if it breaks a
mechanical rule.

## Knowledge Integration (Obsidian)

The active store's Obsidian vault holds durable knowledge.
`/synapse:extract-session` is its main writer; use the Obsidian CLI directly
when persistent knowledge is needed between extractions. Capture decisions,
reusable patterns, and fixes as summaries, never raw logs or transient output.

---

## Failure Handling and Scope

If blocked: re-examine assumptions, search for alternatives, simplify, and log
the blocker in `PLAN.md`. Do not expand scope beyond the stated objective or
add unrelated improvements.
