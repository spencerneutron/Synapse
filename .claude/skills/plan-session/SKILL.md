---
name: plan-session
description: Use when starting or resuming a structured multi-step task that involves PLAN.md and EXECUTION.md
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

1. Check for planning files:

   - `.claude-work/current/PLAN.md`
   - `.claude-work/current/EXECUTION.md`

2. If present:

   - Read both files once
   - Extract:
     - objective
     - constraints
     - current progress
     - prior decisions

   If absent and the task justifies structured planning, start them from
   `templates/PLAN.md` and `templates/EXECUTION.md`.

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
   - If the work resembles prior work, run `/recall` (triggers are in
     `AGENTS.md` — Local Knowledge Recall).

5. Summarize internally:

   - what is being done
   - what remains
   - next immediate step

6. Validate alignment:

   - ensure EXECUTION.md matches PLAN.md
   - resolve inconsistencies
   - confirm the plan reflects what the session hooks surfaced

7. Execute in short loops:

   - perform one step
   - validate result
   - update EXECUTION.md progress

8. Update PLAN.md only when:

   - a decision is made
   - scope changes
   - a reusable insight is discovered

---

## Execution Rules

- Do not reload planning files unnecessarily
- Do not restate their contents unless needed
- Prefer smallest viable step
- Re-evaluate after each step
- Stop if uncertainty becomes high

---

## Output Behavior

When invoked:

- provide a short summary of:
  - current objective
  - next step
- proceed with execution without unnecessary verbosity
