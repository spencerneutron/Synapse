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

1. Find which layout the project uses:

   - `.claude-work/efforts/` exists: the project uses effort folders. Go to
     step 2a.
   - It does not: the project uses `.claude-work/current/`. Go to
     step 2b. Effort folders start only when the user asks
     for them (or asks to split a large PLAN); never start them on your own.

2a. Pick or start an effort (a project with `.claude-work/efforts/`):

   - The SessionStart index (or `synapse effort list`) names the open
     efforts. Read no planning file yet.
   - The effort the user names wins. Otherwise match the task to the list.
     Ask only when two efforts fit.
   - Take one up: `synapse effort resume <slug>`. Then read only
     `.claude-work/efforts/<slug>/PLAN.md` and `EXECUTION.md`, once, and
     extract objective, constraints, progress and prior decisions.
   - No effort fits: propose a slug (lower case, `a-z`, `0-9`, `-`) and run
     `synapse effort start <slug> --title "..."`. It creates PLAN.md and
     EXECUTION.md from the templates; fill them in.
   - Never read another effort's files. New work is a new effort, not a new
     section of this one.
   - Status changes only through the CLI: `synapse effort wait <slug> --on
     "..."` or `synapse effort park <slug>` when that is the state;
     `synapse effort done <slug>` or `cancel <slug> --reason "..."` only on
     the user's word.
   - To split a large `current/PLAN.md` into efforts: `migrate.md` next to this file.

2b. Without effort folders. Check for planning files:

   - `.claude-work/current/PLAN.md`
   - `.claude-work/current/EXECUTION.md`

   If present:

   - Read both files once
   - Extract:
     - objective
     - constraints
     - current progress
     - prior decisions

   If absent and the task justifies structured planning, start them from
   `${CLAUDE_PLUGIN_ROOT}/templates/PLAN.md` and
   `${CLAUDE_PLUGIN_ROOT}/templates/EXECUTION.md`.

   When you reset the planning files for a new task, reset the rest too: an
   `EXECUTION.md` `## Resume` section from the previous task is replaced or
   removed, and a working `NOTES.md` is started fresh only if its last line is
   a merge marker or end-session has run.

3. Run session hooks (optional, per project):

   - If `PLAN.md` has a `## Session hooks` section, run each command or skill
     it lists before choosing the next step. Typical hooks pull outside state
     into the plan: an issue-tracker or roadmap sync, a CI status check, a
     dependency audit.
   - Fold anything new the hooks surface (fresh issues, failing checks, drift)
     into the plan **before** choosing the next step.
   - Skip this step when the section is absent.

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
