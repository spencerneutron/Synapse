---
name: plan-session
description: Use when starting or resuming a structured multi-step task that involves PLAN.md and EXECUTION.md, or when picking or starting an effort in a project with effort folders
---

# Plan Session Skill

## Purpose

Establish a clear, efficient execution loop using PLAN.md and EXECUTION.md.

---

## When to Use

Use this skill when:

- starting a new structured task
- resuming an existing task
- task complexity requires planning
- multiple steps or repos are involved

---

## Procedure

1. Find which layout applies, in this order:

   - `.claude-work/efforts/` exists: the project uses effort folders. Go to
     step 2a.
   - It does not, but `.claude-work/current/` holds `PLAN.md` or
     `EXECUTION.md`: continue in `current/` (step 2b). An existing project is
     not moved; splitting it happens only on the user's request (`migrate.md`).
   - Neither exists and the task justifies structured planning, or the
     `synapse` command is not available (command not found): read
     `branches.md` section "Start the first effort" before anything else.

2a. An effort project (`.claude-work/efforts/`). The SessionStart index (or
   `synapse effort list`) names the open efforts. Read no planning file yet.

   - When the index says "This session is on <slug>" and the request belongs
     to that effort, do not run `resume`. Read only
     `.claude-work/efforts/<slug>/PLAN.md` and `EXECUTION.md`, once, and
     extract objective, constraints, progress and prior decisions.
   - If the session is on no effort, the request belongs to another effort,
     the effort is `waiting`, or the index shows an open effort untouched for
     7 days or more: read `branches.md` section "Choose or start an effort"
     before reading any effort's files.
   - Never read another effort's files. New work is a new effort, not a new
     section of this one.
   - Status changes only through the CLI. To wait, park, finish or cancel an
     effort, read `branches.md` section "Status changes".
   - To split a large `current/PLAN.md` into efforts: `migrate.md` next to this file.

2b. In `.claude-work/current/` (an existing project, or the fallback). Check for planning files:

   - `.claude-work/current/PLAN.md`
   - `.claude-work/current/EXECUTION.md`

   If present:

   - Read both files once
   - Extract:
     - objective
     - constraints
     - current progress
     - prior decisions

   If absent (the fallback): `branches.md` section "Start the first effort".

   When you reset the planning files for a new task: `branches.md` section
   "Reset current/ for a new task".

3. Session hooks: if `PLAN.md` has a `## Session hooks` section, read
   `branches.md` section "Session hooks" and follow it before choosing the
   next step. Skip this step when the section is absent.

4. Explore in parallel:

   - Issue grep and read calls in batches when scoping the problem.
   - Spawn a sub-agent for cross-repo searches that would otherwise serialize.
   - If the work resembles prior work, run `/synapse:recall` (triggers are
     in the Synapse rules — Local Knowledge Recall).

5. Summarize internally:

   - what is being done
   - what remains
   - next immediate step

6. Validate alignment:

   - ensure EXECUTION.md matches PLAN.md
   - resolve inconsistencies
   - confirm the plan reflects what the session hooks surfaced

7. Run each step by its role:

   - a step whose role is `main` (dialogue, decisions, planning files, a
     handful of calls) runs in the main session
   - every other step gets a brief: goal, files, done condition, what is
     ruled out, run path, attempt limit
   - dispatch it to the step's role (`synapse:implementer`, `verifier`,
     `researcher`, `reviewer`, `scout`)
   - verify the report; treat it as a claim
   - log the result in `EXECUTION.md` under `## Progress log`
   - a step needing more than about five tool calls or three files is not
     `main`; give it a role and a brief
   - if steps in `EXECUTION.md` carry no role, add one when you read it

8. Update PLAN.md only when:

   - a decision is made
   - scope changes
   - a reusable insight is discovered

---

## Execution Rules

- Do not reload or restate planning files unnecessarily
- Prefer the smallest viable step
- Stop if uncertainty becomes high

---

## Output Behavior

When invoked:

- provide a short summary of:
  - current objective
  - next step
  - who runs the next step
- proceed with execution without unnecessary verbosity
