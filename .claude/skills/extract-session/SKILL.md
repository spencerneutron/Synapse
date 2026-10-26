---
name: extract-session
description: Use after end-session to project the just-archived session into the Obsidian vault and the local vector database. Runs once per session at teardown. Idempotent — safe to re-run.
---

# Extract Session Skill

## Purpose

Promote the durable knowledge from a just-closed session into two places:

1. **Obsidian vault** — atomic, browseable notes for decisions and patterns
   that future sessions might want to reference.
2. **Local vector DB** — embedded chunks of the archive (and any vault notes
   created here) so `/recall` can surface them later.

The session itself is captured 1:1 as a Session note linking back to its
archive files.

This skill runs at session teardown, when the full session context is still
in working memory. That recency is the point: judgment about what's worth
promoting is more accurate now than it would be from a heuristic scan
later.

---

## Environment

Commands below say `python3`; use the Python named in the active platform
profile (`.claude/rules/platform.md`). Platform-specific gotchas live there too.

- **Vector-DB scripts auto-bootstrap into the venv.** `extract.py` (and
  `recall.py`, which imports it) need `sqlite-vec`, which lives only in
  `kb/.venv`. Never pip-install into a system Python. Invoke the scripts with
  the plain interpreter: `extract.py` detects a missing `sqlite_vec` and
  re-execs itself under `kb/.venv` automatically, so you never have to name
  the venv interpreter.
- **`vault_write.py` needs Obsidian.** It must be running with the vault named
  by `SYNAPSE_VAULT` (default `Synapse`) open, and the app must be **up to
  date** — an out-of-date installer pollutes the CLI output and breaks
  vault-name parsing. `vault_write.py` does not touch the vector DB, so it runs
  fine under the system Python.
- **Never rely on the `obsidian` CLI's own auto-launch.** An Obsidian it starts
  is a child of the calling shell and quits when that shell exits, so the next
  call finds nothing. On macOS `vault_write.py` checks for a running Obsidian
  and, if needed, launches it detached (`open -a Obsidian`) and waits. On
  other platforms, start Obsidian by hand before extracting.
- **Embeddings need Ollama.** The local Ollama server must be running with
  `nomic-embed-text` pulled (`ollama pull nomic-embed-text`).

---

## When to Use

Use this skill:

- Immediately after `/end-session` succeeds, on the same session ID.
- When the user explicitly asks to "extract", "ingest", or "promote" a
  session into the knowledge base.
- When re-running extraction on a session whose archive was edited
  post-hoc (use `--force` semantics described below).

Do **not** use:

- Before `/end-session` has run — the archive files won't exist.
- During an active session — extraction is for closed sessions only.

---

## Inputs

- **Required:** A session ID matching files at
  `.claude-work/archive/PLAN_<id>.md`,
  `.claude-work/archive/EXECUTION_<id>.md`, and/or
  `.claude-work/archive/NOTES_<id>.md`. If no ID is provided, use the most
  recently archived session that has no `.processed/<id>.json` marker.

- **Optional:** Project name. If not provided, infer from the working
  directory, the archive content, or ask the user once.

- **Optional:** `--include-report` if a `REPORT_<id>.md` exists and the
  user wants it embedded for recall.

---

## Procedure

### 1. Locate the archive

- Check `.claude-work/archive/` for files matching the session ID.
- If `PLAN`, `EXECUTION`, and `NOTES` are all missing, stop and report.
- If only some exist, proceed with what's present and note the absence.
- Check `.claude-work/archive/.processed/<id>.json`. If present, the
  session was already processed. Default behavior: ask the user whether
  to re-run (uses `--force`). If the user just said "extract this
  session" explicitly, assume yes.

### 2. Read the archive

Read the full contents of all archive files for the session. The user's
session context will already contain most or all of this — the read is
to ensure complete information, not to discover it.

### 3. Identify Decision notes to promote

A piece of content qualifies as a **Decision note** if and only if it
satisfies all four criteria:

- **It is a choice.** Not an observation, not a discovery, not a status
  update. Something was selected from at least one alternative.
- **It has rationale.** A *why* exists — not just a *what*. "Use
  sqlite-vec" alone is not a decision; "Use sqlite-vec because no daemon
  overhead" is.
- **It is durable.** It would still be a defensible choice in three
  months, in a different project, with different constraints. Tactical
  picks that only make sense for this exact session don't qualify.
- **It is non-obvious.** A future session might reasonably make the
  opposite choice without this context. Decisions like "use UTF-8 for
  source files" are not durable knowledge; they're table stakes.

Bias toward fewer, higher-signal decision notes. If a session produces
zero decisions worth promoting, that is a valid outcome — say so.

The Decision Log section of `PLAN.md` is a strong signal but not the
gate. Promote logged decisions only if they meet the four criteria.
Promote unlogged content if it does.

### 4. Identify Pattern notes to promote

A piece of content qualifies as a **Pattern note** if it satisfies:

- **It is a reusable insight.** A way of approaching problems, a
  workaround for a recurring issue, a structural technique.
- **It transfers.** Useful in projects other than the one this session
  worked on. If it's tied to a specific codebase, table, or API, it's
  probably project-specific knowledge — not a pattern.
- **It is condensable.** The pattern can be stated in 2–4 sentences.
  Anything requiring extensive setup is too narrow.

Patterns are rarer than decisions. Most sessions produce zero. That is
expected and correct.

### 5. Build the Session note spec

Always create exactly one Session note per extraction run. Schema:

```json
{
  "type": "session",
  "title": "<one-line description of what the session was about>",
  "session_id": "<id>",
  "project": "<name>",
  "date": "<YYYY-MM-DD from session_id>",
  "tags": ["session"],
  "related": [<links to prior session notes if this continued earlier work>],
  "body": "<see body structure below>"
}
```

Body structure for Session notes:

```markdown
## Objective
<one sentence — what the session set out to do>

## Outcome
<2-4 sentences — what happened, what shipped, what didn't>

## Decisions made
- [[<title of each Decision note created in this run>]]

## Patterns surfaced
- [[<title of each Pattern note created in this run>]]

## Open at close
<copied verbatim from NOTES_<id>.md "Open questions" / "Deferred" / "Blocked"
sections, or "_None_" if all clean>

## Source
- Archive: `.claude-work/archive/PLAN_<id>.md`
- Archive: `.claude-work/archive/EXECUTION_<id>.md`
- Archive: `.claude-work/archive/NOTES_<id>.md`
```

If a Decision or Pattern note is created in this run, the Session note's
body must link to it via `[[Title]]` syntax. Wikilinks are how the vault
becomes navigable.

### 6. Build Decision and Pattern note specs

For each Decision identified in step 3:

```json
{
  "type": "decision",
  "title": "<concise verb-led title, e.g. 'Use sqlite-vec for local vector store'>",
  "project": "<name>",
  "session_id": "<id>",
  "tags": ["decision"],
  "related": ["[[<session_id>]]"],
  "sources": ["[[<session_id>]]"],
  "supersedes": "[[<title>]]" or null,
  "body": "## Context\n<2-3 sentences>\n\n## Decision\n<one or two sentences>\n\n## Rationale\n<bullets>\n\n## Alternatives considered\n<bullets, optional>"
}
```

If this decision *replaces* an earlier decision (a recall of similar
prior work returned a Decision note that this one overturns), set
`supersedes` to that note's wikilink. Run a recall before promoting a
decision if it might be revisiting prior territory.

For each Pattern identified in step 4:

```json
{
  "type": "pattern",
  "title": "<concise title, e.g. 'Store embedding model name with each vector'>",
  "project": "<name>",
  "session_id": "<id>",
  "tags": ["pattern"],
  "related": ["[[<session_id>]]"],
  "sources": ["[[<session_id>]]"],
  "applies_to": ["<domain tags, e.g. 'python', 'retrieval'>"],
  "body": "## Problem\n<when this comes up>\n\n## Solution\n<what to do>\n\n## Why\n<the underlying reason>"
}
```

### 7. Show the user the proposed extractions

Before writing anything, display a compact summary:

```
Session 2026-04-23-1645 — proposed extractions:

Session note:
  - "Local KB pipeline build" (always created)

Decision notes (3):
  1. Use sqlite-vec for local vector store
  2. Use nomic-embed-text via Ollama for embeddings
  3. Cosine distance metric for vec0 table

Pattern notes (1):
  1. Store embedding model name with each vector

Embedding: 31 chunks across PLAN/EXECUTION/NOTES files.

Proceed? (yes / no / skip <number>)
```

Wait for the user's response. Three response shapes:

- **yes / proceed / go**: write everything.
- **no / cancel**: write nothing.
- **skip <numbers>**: drop the specified items, write the rest.
  Example: "skip decision 2 and pattern 1" means write decisions 1 and 3
  and the session note only.

If the user proposes title edits ("rename decision 1 to..."), incorporate
the changes and re-display the summary once before proceeding.

### 8. Write the vault notes

For each approved spec, in order: Decision and Pattern notes first,
Session note last.

Reason: the Session note's body links to the Decision/Pattern notes by
title. If those notes don't exist yet when the Session note is created,
the wikilinks will be unresolved. Writing the referenced notes first
keeps the vault link graph clean.

For each note, write the spec JSON to a temp file, then invoke
`vault_write.py` with `--from-file`. **Do not pipe JSON through stdin
or pass it inline as a command-line argument** — multi-line JSON with
braces and quotes in command lines triggers shell-injection safety
prompts on every invocation, which makes the skill effectively
non-runnable.

Use a stable temp file path the user can audit if anything goes wrong.
The recommended pattern:

```
# Pseudocode — actual implementation depends on the agent's file tools.
write JSON spec to: .claude-work/.tmp/extract-<session-id>-<note-slug>.json
run: python3 kb/scripts/vault_write.py create-note --from-file <path>
delete the temp file after success
```

If `--on-conflict suffix` is needed (re-running on a session whose notes
already exist), pass it as an additional flag.

Example invocation (one note):

```
python3 kb/scripts/vault_write.py create-note --from-file ".claude-work/.tmp/extract-2026-04-23-1645-decision-1.json"
```

Verify each invocation succeeded (exit code 0 AND output contains the
`"created": true` confirmation) before moving to the next.

If a note already exists at that title (from a prior run), use
`--on-conflict suffix`. The Session note specifically should always use
`--on-conflict suffix` if re-running extraction on the same session, so
we get `<session-id>.md`, `<session-id> v2.md`, etc. and don't lose
history.

### 9. Embed the archive

Run:

```
python3 kb/scripts/extract.py embed-archive <session-id> --project <name>
```

If `--include-report` was specified, add it to the command. If this is a
re-run on a previously processed session, add `--force` to refresh the
chunks.

The script will write `.claude-work/archive/.processed/<id>.json` with
the extraction metadata.

### 10. Embed the new vault notes

For each Decision/Pattern note created in step 8, use the **`path`
field** from `vault_write.py`'s JSON output as the absolute path to
embed. Do not guess where the vault lives — `vault_write.py` already
queried Obsidian for the actual path and reported it.

```
python3 kb/scripts/extract.py embed-note "<path from vault_write output>" --project <name>
```

This makes the promoted notes discoverable via `/recall` immediately,
not just on the next session's run.

The Session note does not need separate embedding — its body content is
mostly a duplicate of archive content that's already embedded.

### 11. Report

When complete, show:

```
Session 2026-04-23-1645 extracted:
  Vault notes created:
    Sessions/2026-04-23-1645.md
    Decisions/Use sqlite-vec for local vector store.md
    Decisions/Use nomic-embed-text via Ollama for embeddings.md
    Decisions/Cosine distance metric for vec0 table.md
    Patterns/Store embedding model name with each vector.md
  Embedded: 31 archive chunks + 4 note chunks
  Marker: .claude-work/archive/.processed/2026-04-23-1645.json
```

---

## Failure Handling

- **Shell-injection safety prompts.** If you find yourself attempting to
  pipe JSON through stdin or pass it as an inline argument, stop. Every
  invocation will trigger a "brace with quote character" safety prompt
  that the user has to dismiss, which kills the skill's usability.
  Always write the spec to a temp file first and use `--from-file`.
  This is not optional.

- **`vault_write.py verify` fails first.** Always run verify before any
  write step. If it times out, check whether Obsidian is running (macOS:
  `pgrep -x Obsidian`). A missing app is the child-process case above: start
  it detached (macOS: `open -a Obsidian`; elsewhere, by hand), wait, and run verify again
  (the script does this itself). If Obsidian is running but verify still fails,
  or the app is out of date (polluted CLI output, broken vault-name parsing),
  stop and tell the user. Do not attempt writes.

- **A vault write fails midway.** If decision notes 1 and 2 wrote
  successfully but decision 3 fails, do not roll back. Report what
  succeeded, what failed, and stop. The user can re-run extraction with
  the failed item only, or fix and re-run from scratch.

- **Embedding fails.** If `extract.py embed-archive` fails (Ollama
  unreachable, etc.), the vault notes are still written. Report the
  embedding failure clearly. The user can re-run the embed step alone:
  `python3 kb/scripts/extract.py embed-archive <id> --project <name> --force`.

- **No decisions or patterns found.** This is a valid outcome. Create
  the Session note only, embed the archive, and report:
  "Session 2026-04-23-1645 had no decisions or patterns worth promoting.
  Archive embedded; session note created."

---

## Output Behavior

- **Step 7 (proposal)** is the user's main interaction point. Keep it
  compact — titles plus one-line summaries. Don't paste the full body of
  each proposed note unless asked.

- **Step 11 (report)** confirms what was done. Brief is fine. The user
  doesn't need a recap of the content — they just need to know the run
  succeeded and where things landed.

- Between steps, work silently. Don't narrate "I'm now going to write
  Decision note 1." Run the commands, check the results, move on.