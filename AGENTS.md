# AGENTS.md

How agents (Claude Code and its sub-agents) work in a Synapse workspace: a shared
root that holds several repositories, where one task may span more than one repo.

The goal is to maximize:
- planning quality
- execution correctness
- token/credit efficiency
- reuse of prior knowledge

This is the only instruction file. Claude Code reads `AGENTS.md` natively when
the working directory and the folders above it have no `CLAUDE.md`,
`.claude/CLAUDE.md`, or `CLAUDE.local.md`. Shell and
path conventions are not here: install the matching profile from `platform/` as
`.claude/rules/platform.md`, which loads alongside this file.

---

## Session Lifecycle

Every non-trivial session runs the same loop. Skills describe *how*; this file
decides *when*.

| Stage | Skill | When |
|-------|-------|------|
| Plan | `/plan-session` | Starting or resuming structured, multi-step work |
| Recall | `/recall` | See "Local Knowledge Recall" below |
| Execute | (this file) | Small verified steps, in waves when the work splits |
| Emit | `emission-contract` | Before the final user-facing message of every turn |
| Archive | `/end-session` | The session itself is closing, not just a task |
| Extract | `/extract-session` | After `/end-session`, same session ID, once the user agrees (`/end-session` recommends it; it never chains it) |
| Recover | `/workflow-recovery` | A background workflow or agent fleet died or was stopped |

---

## Core Operating Principles

- Always plan before executing.
- Prefer small, verifiable steps over large speculative changes.
- Explore the repository before making assumptions.
- Reuse existing patterns wherever possible.
- Avoid unnecessary rework or repeated analysis.

---

## Planning Discipline

Before making changes:

1. Identify the objective clearly.
2. Explore the repository for relevant patterns.
3. Formulate a step-by-step plan.
4. Validate that the plan produces an observable outcome.
5. Execute only after the plan is coherent and minimal.

During execution:

- Re-evaluate after each step.
- Update progress explicitly.
- Stop if uncertainty becomes high.

---

## Planning Files

Working files live in `.claude-work/current/`:

- `PLAN.md` — long-lived strategy, constraints, Decision Log.
- `EXECUTION.md` — the active task and its immediate next steps.

Archives live in `.claude-work/archive/`. Blank starting points are in `templates/`.

Usage:

- Read `PLAN.md` once at session start, or when direction is unclear.
- Read `EXECUTION.md` at the start of each task, or when resuming work.
- Do not re-read either after every step; assume they are unchanged unless you
  updated them.
- Prefer `EXECUTION.md` for immediate actions; use `PLAN.md` to avoid
  rethinking prior decisions.
- If the two conflict, follow `EXECUTION.md` and update `PLAN.md` to match.

Updates:

- Update `EXECUTION.md` often, as meaningful progress lands.
- Update `PLAN.md` only for a durable decision, a scope or approach change, or a
  reusable insight.

If the files do not exist, proceed normally. Create them only when the task's
complexity justifies structured planning.

---

## Repository Exploration

Before implementing anything:

- Search for similar functionality.
- Identify existing patterns or conventions.
- Prefer modifying existing structures over introducing new ones.
- Introduce a new pattern only when it is clearly justified.

---

## Execution Rules

- Make the smallest change that achieves the objective.
- Keep changes localized.
- Ensure changes are testable and observable.
- Avoid speculative or unrelated refactors.

---

## Validation Requirements

Every meaningful change carries:

- a way to run or test the result
- a clear expected outcome
- a failure signal if it is wrong

---

## Token / Context Discipline

- Do not restate large documents unnecessarily.
- Load or reference only relevant files; do not re-read unchanged ones.
- Summarize findings before acting.
- Cache conclusions in `PLAN.md` (Decision Log) instead of recomputing them.
- Prefer incremental reasoning over full re-analysis.

---

## Parallel Tool Use

When a step needs several independent reads, searches, or shell commands, issue
them in one batch.

Apply when:

- exploring an unfamiliar repo (list the directory and read 3-5 key files)
- gathering evidence across files (grep, then read the affected files)
- checking several sources before deciding (recall, a read, and git log)

Do not parallelize:

- when later calls depend on earlier output
- destructive operations (writes, deletes, migrations)
- when batching hides which call produced which result

---

## Sub-agents and Waves

Use sub-agents (the Agent tool) for bounded work that would otherwise blow the
context or run serially. A sub-agent returns a summary, not a transcript: spawn
one for the answer, not the journey.

Strong fit for a single sub-agent:

- "Search these N repos for pattern X and summarize occurrences"
- "Read this large file and extract only the parts about Y"
- "Audit this directory tree for files matching criteria Z"

Not a fit:

- work that needs ongoing dialogue with the user
- work that depends on this session's full context
- a single file read or grep (use the tools directly)

### Waves

Once the plan is set and the work splits into independent parts, run it as
waves of role-specific agents rather than one long serial loop:

| Wave | Job | Writes? |
|------|-----|---------|
| Implementation | Make one planned change each | Yes — one writer per set of files |
| Verification | Build, test, and check the change across affected repos | No |
| Research | Answer an open question from docs, code, or the web | No |
| Adversarial review | Try to break the change or the plan with fresh eyes | No |

- Give each agent a self-contained brief: goal, files, what done looks like, and
  what you have already ruled out.
- Never let two writers touch the same files. Use an isolated worktree when
  edits could overlap.
- Treat every agent's result as a claim: verify it before reporting it as done.
- Record what each wave returned in `EXECUTION.md`.

### Model right-sizing

Pick the model per wave. Frontier models plan; right-sized models execute.

| Tier | Use for | As of 2026-10 |
|------|---------|---------------|
| Frontier | Planning, architecture, adversarial review, ambiguous debugging | Opus |
| Mid | Implementation and verification against a clear brief | Sonnet |
| Small | Mechanical search, extraction, bulk formatting | Haiku |

Pass the tier through the Agent tool's `model` option. Escalate one tier when an
agent's result fails verification twice; do not start every wave on Frontier.

### Interrupted runs

If a background workflow or fleet stops early (session exit, pause, usage
limit), run `/workflow-recovery` before relaunching anything. Completed agents'
results are usually still on disk, and a relaunch pays for them again.

---

## Local Knowledge Recall

`/recall` queries the local knowledge base of past sessions, decisions, and
patterns. It returns ranked snippets with source paths, not full content.

Invoke it proactively when:

- planning work that resembles or extends prior work
- a decision is being made that may have been made before
- the user references "what we did", "last time", "before", or similar
- debugging an issue that may have been seen before
- entering a project area with prior session history

Do not invoke it when:

- the task is self-contained and novel
- `EXECUTION.md` already holds enough context
- the topic was already recalled this session

Treat results as navigation hints, not context. Read a source path only if its
snippet is genuinely relevant. Never paste recall output into `PLAN.md` or
`EXECUTION.md`: cite the source path and paraphrase.

---

## Emission

At the end of every turn, load the `emission-contract` skill immediately before
writing the user-facing message, and follow it for that message only.

The contract is bound late on purpose: its style rules stay out of the
reasoning context while the work happens. A Stop hook
(`.claude/hooks/emission_check.py`) checks the message and asks for one
rewrite if it breaks a mechanical rule.

---

## Knowledge Integration (Obsidian)

The Synapse vault holds durable knowledge. `/extract-session` is its main
writer; use the Obsidian CLI directly when persistent knowledge is needed
between extractions.

- Capture decisions, reusable patterns, and fixes.
- Write summaries and outcomes, never raw logs or transient output.
- Do not store redundant information.

---

## Failure Handling

If blocked:

1. Re-examine assumptions.
2. Search for alternative implementations.
3. Simplify the approach.
4. Document the blocker in `PLAN.md`.

---

## Scope Control

- Do not expand scope beyond the stated objective.
- Do not introduce unrelated improvements.
- Keep changes aligned with the current task only.

This file governs all agent behavior. Follow it strictly.
