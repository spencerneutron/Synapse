---
name: end-session
description: Use when the session itself is closing (not merely when a task finishes). Archives PLAN.md and EXECUTION.md under a session tag and ensures any open questions or deferred actions are captured in a session notes file.
---

# End Session Skill

## Purpose

Close out a planning session cleanly so that nothing in-flight is lost:

1. Archive the current `PLAN.md` and `EXECUTION.md` under a session-tagged filename.
2. Extract any open questions or deferred / blocked actions from those files and record them in a session notes file.
3. Leave the working `PLAN.md` and `EXECUTION.md` intact so the next session can pick up from the same place (or be reset by the next `plan-session` invocation).

---

## When to Use

Use this skill when:

- the user says the session is done, wrapping up, calling it for the day, etc.
- a milestone has been reached and the session is formally closing
- multiple deferred items have accumulated and need to be surfaced before handing off
- the user explicitly asks to "end the session" or invokes the skill

Do **not** use this skill just because a task finished — only when the session itself is closing.

---

## Inputs

- Required: `.claude-work/current/PLAN.md` and/or `.claude-work/current/EXECUTION.md`. If neither exists, report that and stop — there is nothing to archive.
- Optional: a session ID provided by the user. If not provided, generate one as `YYYY-MM-DD-HHMM` in local time (e.g. `2026-04-23-1645`). If a file already exists with that tag, append `-v2`, `-v3`, etc.

---

## Procedure

### 1. Determine session ID

- Use the user-provided ID if given.
- Otherwise generate `YYYY-MM-DD-HHMM`.
- Check the archive directory for collisions and disambiguate with `-v2`/`-v3` as needed.

### 2. Archive the planning files

Copy (do not move) to `.claude-work/archive/`:

- `.claude-work/current/PLAN.md` → `.claude-work/archive/PLAN_<session-id>.md`
- `.claude-work/current/EXECUTION.md` → `.claude-work/archive/EXECUTION_<session-id>.md`

If the `archive` directory does not exist, create it.

If only one of the two files exists, archive what exists and note the absence in the session notes.

### 3. Extract open questions and deferred actions

Scan the **working** `PLAN.md` and `EXECUTION.md` for anything still in flight. Look for (non-exhaustive):

- Unchecked checkboxes (`- [ ]`)
- Sections or headings titled **"Open questions"**, **"Deferred"**, **"Blocked"**, **"Follow-ups"**, **"Next step"**, **"TODO"**, **"Out-of-scope for \<current track\>"**, or equivalent
- Lines starting with `TODO:` / `FIXME:` / `NOTE:` / `Revisit` / `Blocked:` / `Pending:`
- "User decision" prompts that were never answered
- `Validation blocked` / `Build blocked` style notes
- Steps marked in-progress that never completed
- Explicit "out-of-scope" or "scope deliberately skipped" items the user may still want to track

Also scan current in-memory task list for tasks still `pending` or `in_progress` — those are deferred by definition.

Be selective: only capture items that a future session would actually act on. Don't transcribe every historical decision.

### 4. Write the session notes file

Write to `.claude-work/archive/NOTES_<session-id>.md` with this structure:

```markdown
# Session Notes — <session-id>

**Closed:** <YYYY-MM-DD HH:MM> (local)
**Archived plans:** `PLAN_<session-id>.md`, `EXECUTION_<session-id>.md`

## Open questions

- …one per item, with enough context to be actionable cold…

## Deferred / out-of-scope work

- …

## Blocked

- …with the specific blocker and what unblocks it…

## In-flight at close

- …tasks that were in_progress or pending when the session ended…
```

Omit any section that has no entries. If all sections are empty, write a single line: `_No open items — session closed clean._`

### 5. Verification step (required)

Before reporting "done":

- Confirm both archive files exist at the expected paths (re-list the directory).
- Confirm the notes file exists.
- Cross-check: for every `- [ ]` unchecked item and every `Blocked`/`Open question`/`Deferred` heading content in the working files, ensure it is reflected (or deliberately excluded) in the notes file. If something in the working files is *not* in the notes and was *not* deliberately excluded, that's a miss — add it.
- Report the three file paths and a one-line summary of what was captured.

### 5b. Suggest extraction (recommended)

After verification succeeds, recommend that the user run
`/extract-session <session-id>` to project this session into the
Obsidian vault and the local knowledge base. Phrase it as a default
next step, not an open question:

> "Archive complete. Recommend running `/extract-session 2026-04-23-1645`
> to promote this session's decisions and patterns into the vault and
> embed it for recall. Skip if this was a throwaway session or if
> Obsidian isn't running."

Do **not** invoke `/extract-session` automatically. Skill-to-skill
invocation makes orchestration hard to reason about; the user should
make the call. Extraction can also be run later — there's no expiration.

If the user has previously declined extraction in this workspace and
explicitly indicated a "stop suggesting" preference, omit this step.

### 6. Do not modify the working PLAN.md / EXECUTION.md

The skill is archival, not destructive. The next `plan-session` invocation is responsible for deciding whether to reset, continue, or back up the working files again.

---

## Output Behavior

When invoked, respond with:

- the chosen session ID
- the three file paths created
- a short bullet list of what was captured in the notes (or "nothing open — clean close")

Keep output terse. The user doesn't need a recap of the archived content; the archive itself is the recap.

---

## Failure Handling

- If archive writes fail (permissions, path issues), stop and report — do not silently swallow.
- If nothing exists to archive, say so and exit.
- If the user-supplied session ID contains path separators or characters unsafe for a filename, reject it and ask for a safe ID.
