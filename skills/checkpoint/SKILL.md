---
name: checkpoint
description: Use between stages of a multi-stage request, before stepping away, or when Synapse reports a large context. Writes the live state to .claude-work/current/ without ending the turn, so /clear afterwards loses nothing.
allowed-tools: Bash(synapse checkpoint *)
---

# Checkpoint Skill

Save what only this conversation knows (objective, position, facts the user stated, reasons for decisions) to disk, then keep working. `/clear` and `/compact` remove that record.

Working folder: `.claude-work/current/` at the project root.

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

It records the time inside `## Resume`. If it is unavailable or fails, carry on: the resume pointer then uses the file's modification time.

### 5. Say it once, then continue

Say once, in one or two sentences: the checkpoint is on disk; `/clear` is now free (the next session start points to the Resume section); `/compact` is lossy (a summary) and re-reads the whole context once. Do not repeat this on later checkpoints in the same session.

Then continue the work in the same turn. A checkpoint never ends the turn or waits for the user, unless the work itself is finished.

## Rules

- Idempotent: a second checkpoint updates Resume in place and never duplicates notes lines.
- Write no other files (no CHECKPOINTS.md).
