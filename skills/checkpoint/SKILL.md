---
name: checkpoint
description: Use between stages of a multi-stage request, before stepping away, when Synapse reports a large context, or when the Stop gate asks for it. Writes the live state to the session's planning folder without ending the turn, so /clear afterwards loses nothing.
allowed-tools: Bash(synapse checkpoint *), Bash(synapse effort *)
---

# Checkpoint Skill

Save what only this conversation knows (objective, position, facts the user stated, reasons for decisions) to disk, then keep working. `/clear` and `/compact` remove that record.

Working folder: the session's planning folder. With effort folders (`.claude-work/efforts/` exists) that is the effort the session is on, `.claude-work/efforts/<slug>/`. If the project has efforts and this session has taken none up, run `synapse effort resume <slug>` (or `synapse effort start <slug> --title "..."`) first. With no efforts folder, a project whose `.claude-work/current/` holds PLAN.md or EXECUTION.md keeps using `current/`. With neither, start an effort (`synapse effort start <slug> --title "..."`, a short lower-case slug from the task) and write `## Resume` in its EXECUTION.md; if the `synapse` command is not available (command not found), use `.claude-work/current/` and say so once. If it prints an `error:` line, fix the argument and run it again; do not fall back. Write only that folder's files.

## Procedure

### 1. Prepare the files

- `EXECUTION.md` missing: create it from `${CLAUDE_PLUGIN_ROOT}/templates/EXECUTION.md`, as plan-session does.
- `NOTES.md` missing, or it has a line starting `<!-- merged into NOTES_` (end-session already archived its entries): write it fresh. Title `# Working notes (checkpoints)`, one comment line saying /synapse:end-session merges it into the session's archived notes, then the headings from `${CLAUDE_PLUGIN_ROOT}/templates/NOTES.md`: `## User-stated facts`, `## Patterns surfaced`, `## Decision rationale`, `## Open questions`, `## Deferred / out-of-scope work`, `## Blocked`.

### 2. Write `## Resume` in EXECUTION.md

Replace the whole section if it exists (from its heading to the next `## ` heading); otherwise insert it right after the title line. Never two Resume sections. Short bullets, pointers not copies, about 25 lines at most:

- Objective, in the user's words
- Active step and next action
- State of the work: branch, uncommitted files (`git status --short`), last validation command and its result
- Background jobs still running, or "none"
- Planning files: PLAN.md, NOTES.md, any other notes the work uses
- What not to redo (optional)

### 3. Append to NOTES.md

Add only what is new since the last checkpoint and not already in NOTES.md or in PLAN.md's Decision Log. Read each section first: skip an entry an existing line already covers; edit a line whose item changed (an answered question leaves Open questions and becomes a decision). Do not miss these categories:

- **User-stated facts**: the user's words or a close paraphrase
- **Patterns surfaced**: reusable lessons
- **Decision rationale**: the decision, why, what was rejected
- **Open questions**: including decisions waiting on the user
- **Deferred / out-of-scope work**
- **Blocked**: the blocker and what unblocks it

Durable decisions also go to PLAN.md's Decision Log when PLAN.md exists.

### 4. Stamp

From the project root run:

```
synapse checkpoint --stamp
```

It follows the session's effort and records the time inside `## Resume`. With no effort taken up in a project with efforts it says so and names the open ones: take one up, then stamp again. If it is unavailable or fails, carry on: the resume pointer then uses the file's modification time.

### 5. Say it once, then continue

Say once, in one or two sentences: the checkpoint is on disk; `/clear` is now free (the next session start points to the Resume section); `/compact` is lossy (a summary) and re-reads the whole context once. Do not repeat this on later checkpoints in the same session.

Then continue the work in the same turn. A checkpoint never ends the turn or waits for the user, unless the work itself is finished.

## Rules

- Idempotent: a second checkpoint updates Resume in place and never duplicates notes lines.
- Write no other files (no CHECKPOINTS.md).
