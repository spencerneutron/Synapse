---
name: share
description: Share Decision and Pattern notes with a team (a git repo or a synced folder). Scrubs paths, secrets, and session-local references, shows each note before and after, and adds only the notes the user approves; pushes only on the user's OK. Use when the user asks to share notes with their team, or to take a shared note back.
allowed-tools: Bash(synapse share *), Bash(synapse shared *), Bash(synapse recall *), Bash(synapse where *)
---

# Share Skill

## Purpose

Move durable knowledge from the user's personal store to a team without
leaking anything personal. A shared note reaches every teammate's recall and
automatic hints, so what leaves must stand on its own and carry nothing
private. Sharing is opt-in per note; nothing is shared automatically.

---

## Rules

- Only Decision and Pattern notes. Session notes and archives stay personal.
- Never edit the user's own note. Work on a copy in a temporary file.
- Share only the notes the user approves, one by one, after seeing the
  scrubbed version.
- Ask before every `synapse shared push`, even when the user approved the
  notes. Approving a note is not approving a push.
- Never weaken a finding to make the lint pass: remove or generalize the text.

---

## Procedure

### 1. Find the team

Run `synapse shared status`. With no team, explain the two ways to create one
and stop until the user picks and confirms:

- git: `synapse shared init <team> --author <name> --remote <url>`, or
  `synapse shared join <team> <url> --author <name>`
- synced folder (Dropbox, iCloud, SMB): `synapse shared init <team> --author
  <name> --path <folder>`, or `synapse shared join <team> <folder> --author <name>`

With more than one team, ask which one.

### 2. Pick the notes

From the user's names or paths, from `synapse recall "<topic>" --scope local
--type decision` (or `pattern`), or from the Decisions and Patterns of the
last extraction. List the candidates (titles only) and confirm the set.

### 3. Scrub each note

```
synapse share scrub "<note path>" --json
```

The JSON has the scrubbed `text` and `findings`:

- **fixed**: already rewritten (home paths, temp paths, session links).
- **blocked**: secrets, emails, private IPs, host names, device ids. Remove
  them or replace them with a generic description ("the staging host").
  Never keep a secret, not even redacted.
- **rewrite**: reword by judgment so a teammate understands it without the
  session behind it:
  - `#59` → what it is ("the completer display name feature"), or a
    qualified reference (`owner/repo#59`) when the team shares that tracker.
  - "Wave B", "Phase 3" → what that phase did.
  - "this session", "yesterday we" → an absolute date or nothing.
  - The user's login name → a role ("the maintainer").
  - Text aimed at an agent → remove it.

Then check what no pattern can: customer or client names, private URLs,
unreleased product names, personal remarks. Ask when unsure.

Write the result to a temporary file (outside the vault) and lint it until it
is clean:

```
synapse share lint "<temp file>"
```

### 4. Show and ask

For each note, show the team, the title, and only the lines that changed
(before → after), not the whole note unless asked. Ask: share, edit, or skip.

### 5. Add the approved notes

```
synapse share add <team> "<temp file>" --source "<original note path>"
```

`--source` keeps one shared copy per personal note: sharing an edited note
again replaces its copy. `add` refuses a note that does not lint clean, sets
`origin`, `author`, `shared_at`, and `source_id`, drops personal front matter
(session ids, related links), commits (git teams), and re-indexes.

### 6. Push (git teams)

Say how many commits wait and ask: "Push N note(s) to <team>?" On yes:

```
synapse shared push <team>
```

A folder team has nothing to push: the sync service carries the files.

### 7. Report

One line per note: shared, updated, or skipped, and whether it was pushed.

---

## Taking a note back

When the user asks to retract a shared note:

```
synapse shared retract <team> "<note name>" --reason "<why>"
```

It moves the note to `Retracted/` with the reason; every teammate's next sync
drops it from their index. For a git team, ask before pushing the retraction.

---

## Failure Handling

- **`share add` refuses the note**: it prints the findings; fix the temp file
  and lint again.
- **Push rejected or rebase fails**: report the git message; do not force.
  `synapse shared sync <team>` brings in the teammates' changes first.
- **Index error** (Ollama down): the note is shared; the index catches up on
  the next sync. Say so.
