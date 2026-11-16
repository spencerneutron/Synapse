# Effort folders: one planning folder per effort, a derived index, a session binding

Status: **design, 2026-11-15; built on the branch that adds this file
(2.9.0), after an adversarial review whose findings are folded in.** The owner
chose the mechanism (per-effort folders with a derived index, and a
session-to-effort binding in the first cut). This note records how it works,
what was checked, and what was rejected. `file:line` citations are to this
repository at 2.8.0, before the change. Claude Code facts were checked on
2026-11-15 against its docs (Claude Code 2.1.314 installed); each links to
its source.

## Problem

A project has one planning folder. `work_dir()` is
`<root>/.claude-work/current` and `find_work_dir()` takes no session or
effort (`lib/synapse/paths.py:349-366`), so every session in a checkout
resolves the same `PLAN.md` and `EXECUTION.md`. The always-on rule tells
every session to read `PLAN.md` at start (`instructions/core.md:62`).
`/synapse:plan-session` continues whatever files exist; its reset paragraph
says what to clear but nothing triggers it
(`skills/plan-session/SKILL.md:45-48`). The PLAN template assumes one
objective and letters its phases (`templates/PLAN.md:24-25`).

In a large repository where many unrelated efforts run from many sessions a
day, and efforts often wait, the result is one plan with phases lettered
past Z: interleaved threads, no cheap way to tie off finished or cancelled
work, and every session pays to read all of it. The existing design already
names the gap: two sessions in one checkout share the folder
(`docs/design/continuation-assist.md:382-384`).

The requirement: fit the main workflow, at worst modifying it and at best
reducing it, and let parallel work in a repository know about other work
there without carrying it.

## Mechanism

```
<project>/.claude-work/
  current/                    unchanged: the planning folder of a project
                              (or a session) that uses no efforts
  efforts/
    <slug>/
      effort.json             title, status, waiting_on, reason, dates: CLI-written
      PLAN.md  EXECUTION.md   the effort's own planning files
      NOTES.md  ARTIFACTS.md  REPORT.md   as in current/, when they exist
    _closed/
      <archive-id>/           a finished or cancelled effort's folder, moved here
                              later (see Closing)
```

- **An effort** is one piece of work with its own objective. It has a slug
  (`a-z`, `0-9`, `-`; 40 characters at most; lower case, so it is one folder
  on a case-insensitive disk; no Windows device name; not `v<N>` and no
  `-v<N>` ending, which archive IDs use for a clash), a title, and a status: `active`, `waiting`,
  `parked`, `done` or `cancelled`. A waiting effort records what it waits on.
- **Status is machine-set.** `effort.json` is written only by the `synapse
  effort` commands, atomically (temp file, `os.replace`). The model edits
  PLAN and EXECUTION as before and never edits status as prose. Anthropic's
  long-running-agent harness keeps its feature list in JSON for this reason:
  "the model is less likely to inappropriately change or overwrite JSON
  files compared to Markdown files"
  ([source](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
- **A project uses effort folders once `.claude-work/efforts/` exists.**
  Nothing creates that folder except `synapse effort start` and `synapse
  effort migrate --apply`. `start` puts it beside an existing
  `.claude-work/` found from the working folder upwards; with none, at the
  repository root (the folder holding `.git`), else in the working folder.
- **Only `paths.py` decides locations**: `work_root`, `efforts_dir`,
  `effort_dir`, `closed_dir`, the binding state file, and `find_work_dir`,
  which gains two optional arguments (below).

The folder-per-unit layout with a dated archive on close is OpenSpec's:
one folder per change under `openspec/changes/<name>/`, "multiple changes
can exist simultaneously without conflicting", and archiving moves the
folder to `changes/archive/` with a date prefix
([concepts](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md)).
OpenSpec documents no path for an abandoned change, so `cancel` below is
Synapse's own.

## Commands

```
synapse effort list [--all] [--json]       the index as this session sees it; --all adds parked and closed
synapse effort start <slug> [--title T]    new effort: folder, effort.json, PLAN and EXECUTION from the templates
synapse effort resume <slug>               take up an open effort; a waiting or parked one becomes active
synapse effort wait <slug> --on TEXT       status waiting, with what it waits on
synapse effort park <slug> [--reason T]    status parked: kept, out of the index
synapse effort done <slug> [--reason T]    close: archive with an Outcome line, status done
synapse effort cancel <slug> --reason T    close as cancelled: the same steps; the reason is required
synapse effort migrate [--apply FILE]      split current/PLAN.md into efforts (below)
```

`start` and `resume` also bind the calling session (next section). Each
verb is one call and prints one status line first (`Synapse effort
started: <slug>`), so a transcript shows what happened. `wait` and `park`
are the session's own call; `done` and `cancel` cannot be undone in this
cut (no reopen), so the rules and skills run them on the user's word.

## Session binding

Every hook that reads planning files must know which effort its session is
on. The binding is a small JSON file in the Synapse home,
`state/effort-<session>.json`, holding the project root and the slug: the
same session-keyed pattern as the hint, nudge and context state
(`lib/synapse/paths.py:373-388`).

**How a session is bound.**

1. *The CLI binds itself.* Claude Code sets `CLAUDE_CODE_SESSION_ID` "in
   Bash and PowerShell tool subprocesses, hook command subprocesses, and
   stdio MCP server subprocesses", and "for Bash, PowerShell, and hooks this
   matches the `session_id` field in the hook JSON input and is updated on
   `/clear`" ([env-vars](https://code.claude.com/docs/en/env-vars)). Checked
   live on macOS, 2.1.314: the variable in a Bash tool call equals the
   session's ID. So `synapse effort start|resume` writes the binding for the
   session that ran it, with no ID passed by the model. This answers the
   open question "can a skill learn its session ID": it does not need to.
2. *The hook binds an unbound session that writes an effort's files.* The
   PostToolUse hook already runs after every Edit, Write and MultiEdit with
   `session_id` and `tool_input.file_path` (`hooks/hooks.json:52-63`;
   paths are "always absolute",
   [hooks](https://code.claude.com/docs/en/hooks)). When a main-session
   call (no `agent_id`) writes the `PLAN.md`, `EXECUTION.md` or `NOTES.md`
   of an open effort and the session has no valid binding, the hook records
   one. This covers a Claude Code too old to set the variable and a session
   that edits without running the command. It never replaces an existing
   binding: only `start` and `resume` move a session, and a session that
   was bound this way moves the same way.
3. *`/clear` hands the binding over.* `/clear` starts a new session ID
   (`CLAUDE_CODE_SESSION_ID` "is updated on `/clear`"; SessionEnd fires with
   reason `clear` and SessionStart with source `clear`,
   [hooks](https://code.claude.com/docs/en/hooks)). At SessionEnd with
   reason `clear`, a bound session's archive hook writes a handoff before
   it does anything else: one small file per ending session,
   `state/effort-handoff-<root hash>-<old session>.json`. It comes first
   because all SessionEnd hooks share 1.5 seconds and a plugin's `timeout`
   does not raise that (`docs/design/continuation-assist.md:206`), and
   because the archive returns early in several cases
   (`lib/synapse/archive.py:126-136`, `:148-149`, `:160-161`). At
   SessionStart with source `clear`, a session with no binding looks for
   handoffs for its root written in the last 20 seconds. Exactly one: it
   claims it by rename (so one session gets it) and is bound; the resume
   pointer then names that effort. None or several: no binding, and the
   pointer falls back to a list (below). The wrong session can claim a
   handoff only when two sessions in one checkout run `/clear` within about
   a second and the bound one's hook loses the race; the index then says
   which effort the session is on, and `resume` corrects it.

**How the folder resolves.** `find_work_dir(start, session_id=None,
effort=None)`:

1. Find the work root: `start` or the nearest parent holding
   `.claude-work/current` or `.claude-work/efforts`, stopping at a `.git`
   folder as today.
2. `effort` given (the CLI's `--effort`): that effort's folder.
3. `session_id` given and its binding is valid: that effort's folder.
4. Otherwise `current/`, exactly as today.

In a project with efforts, a session with no binding still gets
`current/`. So that this is not silent: the index says the session is on no
effort; `synapse checkpoint --stamp` without a binding or `--effort` says so
and names the open efforts; the checkpoint and plan-session skills take up
an effort first. The artifact record and the checkpoint ask behave for such
a session as they do today in a project with no planning files
(`lib/synapse/gate.py:192`, `:233`).

A binding is valid when its root is this work root and
`efforts/<slug>/effort.json` exists with an open status. Hooks pass the
`session_id` from their input; `synapse checkpoint --stamp` and `synapse
archive` pass `CLAUDE_CODE_SESSION_ID` and accept `--effort <slug>` for a
shell with no session.

**The cases.**

| Case | What happens |
|------|--------------|
| No binding yet | Hooks use `current/` as today. The index says the session is on no effort and names the two commands. |
| Stale: the effort was closed | The binding no longer validates; the session is unbound. If another session closed it, the next prompt carries one line saying so, once, and the binding file is removed. |
| Stale: crashed or ended session | The file stays, harmless; SessionStart prunes bindings idle for 7 days, as it prunes the context state (`lib/synapse/nudge.py:100-107`), and handoffs after a day. |
| `/clear` | Handoff, above. If none is claimed, the pointer lists up to three efforts with the freshest `## Resume` and the command to take one up. |
| `claude --resume <id>` | The ID is kept ("Resumes the session with that ID", [sessions](https://code.claude.com/docs/en/sessions)), so the binding is still there. |
| Fork or `/branch` | A new ID ("get their own session IDs", same page), so no binding; the restored conversation names the effort and the index names the command. |
| Compaction | The docs do not say whether the ID changes. Existing code relies on the session continuing: it finds the `compact_boundary` in the same transcript and keeps the observed window under the same session ID (`lib/synapse/continuation.py:119-130`, `:299-303`). If the ID did change, the session would be unbound and get the same fallback list as after `/clear`. Needs a live check. |
| Two sessions on one effort | Advisory only. Each prompt touches the session's binding file; `resume` and the index say when another session's binding to the same effort was touched in the last 30 minutes. No lock: a lock needs a release on crash, and the cost of a miss is an overwritten planning line, which the archive keeps. |
| Sub-agent calls | Ignored by the hook binding (the hook input carries `agent_id`, [hooks](https://code.claude.com/docs/en/hooks)): the main session conducts the planning files. |
| Worktrees | Each worktree has its own `.claude-work/` (it is git-ignored), so its own efforts; a session binds only to efforts of its own checkout. The index adds the open efforts of the repository's other checkouts, read-only (next section). Archives of all worktrees share one project (`lib/synapse/paths.py:197-213`). Removing a worktree removes its working files, efforts included, as it removes `current/` today; what was archived stays in the store. |

Beads has the same two ideas as an atomic claim (`bd update <id> --claim`)
and a ready list (`bd ready`)
([README](https://github.com/steveyegge/beads)); Synapse borrows the ideas
and not the storage (see Rejected).

## The index

At SessionStart the nudge hook (already there for the resume pointer,
`lib/synapse/nudge.py:182-184`) prints the index when the project has
efforts. It is computed from each open effort's `effort.json` and the
modification time of its `EXECUTION.md`: no file is generated, so two
sessions cannot conflict on it, and no Markdown is parsed.

```
Synapse efforts in this project: 3 open, 2 parked. This session is on none yet.
Take one up with `synapse effort resume <slug>`, or start new work with `synapse effort start <slug> --title "..."`; read only that effort's files (.claude-work/efforts/<slug>/).
- auth-token-rotation [active] Rotate the service tokens (2h ago)
- billing-export [waiting on: finance sign-off on the CSV columns] Billing export v2 (3d ago)
- ci-cache [active] Speed up the CI cache restore (5m ago; another session 5m ago)
```

One line per active or waiting effort, newest first, 15 at most and then a
count; parked efforts are a count; closed efforts do not appear. Titles and
waiting text are clipped to 80 characters. A bound session's own effort is
marked `(this session)`. When `current/` still holds a PLAN or EXECUTION
beside the efforts, one line says so. `synapse effort list` prints the same
text. Measured size: see "Measured" at the end.

**Other checkouts.** Sessions in separate worktrees do not share a
`.claude-work/`, and the desktop app starts each session in its own
worktree (`docs/design/continuation-assist.md:382-384`). So the index ends
with up to five lines for open efforts in the repository's other checkouts
(the main checkout and its linked worktrees, found from `.git` as
`repo_name` does, `lib/synapse/paths.py:197-213`, with no `git` call), each
marked with its checkout's folder name. They are for awareness only: a
session cannot resume another checkout's effort.

This is the "lightweight identifiers" pattern: keep "file paths, stored
queries, web links" in context and "dynamically load data into context at
runtime"
([source](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).
The counter-example is a memory bank whose files are all read "at the start
of EVERY task"
([source](https://docs.cline.bot/prompting/cline-memory-bank)), which is
what `core.md:62` does today.

## Closing

`done` and `cancel` do the same steps, in this order:

1. Claim the close: create `efforts/<slug>/.closing` exclusively. A second
   closer stops here; a claim older than a minute (a crashed close) is
   taken over. The status is read again under the claim. Once the archive
   is copied, the claim holds its ID, so a rerun after a crash reuses that
   archive instead of writing a second one.
2. Copy PLAN, EXECUTION, NOTES, REPORT and ARTIFACTS to the store's archive
   under `YYYY-MM-DD-HHMM-<slug>`. The archived PLAN gets one more line
   under `## Outcome`: the date, `Done` or `Cancelled`, and the reason. The
   archive then says how the effort ended, which the extractor needs
   because it reads only the archive. ExecPlans close the same way, with a
   required "Outcomes & Retrospective" section
   ([source](https://developers.openai.com/cookbook/articles/codex_exec_plans)).
   A failure here leaves the effort open and unchanged.
3. Write the status, reason and archive ID to `effort.json`. The effort is
   now out of the index.
4. Add the same Outcome line to the working `PLAN.md` and release the
   claim. The command then drops the closing session's own binding; other
   sessions bound to the effort get the stale notice once.

What remains in view is the archive ID (`effort list --all`) and the
store's archive: "compression strategies are always designed to be
restorable ... a document's contents can be omitted if its path remains
available"
([source](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)).

**The folder moves later.** A closed effort's folder stays where it is for
at least an hour, so the session that closed it (end-session, below) can
still read and finish its files. After that, the next `start` or close in
the project moves it to `efforts/_closed/<archive-id>/` with a plain
rename, never a copy-and-delete. The folder is named by the archive ID
when that is a safe ID, else by date and slug. The move is housekeeping: status is what
takes an effort out of the index. On Windows a folder with an open file
cannot be renamed; then it stays and the next sweep tries again. `start`
on the slug of a closed effort moves that folder first and fails with a
clear message if it cannot. Nothing is ever deleted.

**end-session.** For a finished effort, `/synapse:end-session` runs
`synapse effort done <slug> --json` in place of `synapse archive`. It
prints the same keys (`session_id`, `copied`, `missing`, `notes_path`) plus
`folder`, the effort's folder, which the skill uses for its remaining steps
(the scan of the working files and the merge marker in `NOTES.md`). `done`
copies an unmerged working `NOTES.md` as `NOTES_<id>.md`, as the SessionEnd
archive does, so a close outside end-session keeps the notes; end-session
then writes its fuller notes over that copy. For an effort that continues,
end-session runs `synapse archive` as before, which follows the binding.

`park` and `wait` change status only: no archive, no move, and the session
stays bound, so a checkpoint or the exit archive still lands in the effort.
There is no reopen in this cut: start a new effort and cite the archive ID.

**Archive IDs.** An effort's archives are `YYYY-MM-DD-HHMM-<slug>` (and
`-v2` on a clash, as today, `lib/synapse/archive.py:70-77`); the ID
patterns already allow it (`lib/synapse/archive.py:46-47`), IDs still sort
by time, and no other module parses an ID (extract, pending, backfill,
recall, detach and vault_write treat it as opaque). The ID is for people.
Code never parses the slug back out of it, because a user's own `--id`
could look like one: each effort archive also gets a marker file in the
store, `archive/<project>/.effort/<archive-id>`, holding the slug.

The SessionEnd archive follows the bound effort: its per-session state is
keyed by session and effort, and its "same as the newest archive" check
(`lib/synapse/archive.py:150-161`) compares with the newest archive marked
for that effort. In a project with efforts, `current/` compares with the
newest archive that has no marker, so leftover files there are not archived
again at every exit. In a project with no efforts the check is today's.

## Workflow

- **plan-session** becomes "pick or start an effort" in a project with
  efforts: the effort the user names wins; otherwise the task is matched to
  `synapse effort list`; otherwise the skill proposes a slug and starts it,
  asking only when two efforts fit. It then reads that effort's PLAN and
  EXECUTION. The reset paragraph goes: unrelated work is another effort.
- **checkpoint**, **end-session**, the **resume pointer**, the **checkpoint
  ask**, the **compaction guide**, the **artifact record** and the
  **SessionEnd archive** follow the bound effort through `find_work_dir`.
- **core.md** (`instructions/core.md:52-67`, which names `current/` and the
  read at session start) says where the files are in both layouts and drops
  the unconditional `PLAN.md` read for a project with efforts: a session
  reads the index, and one effort's files when it takes that effort up. The
  file stays under its 9,500-character limit (8,876 before).
- **doctor** checks the efforts folder (a folder with no readable
  `effort.json`, a closed effort that could not be moved, a `current/` plan
  large enough to split, working files not git-ignored), and INSTALL.md's
  preflight table gets the row.
- **Templates**: the PLAN has no phase letters; its header says one effort
  per plan.

Removed: the full-PLAN read at every session start, the reset step nothing
triggered, and the phase lettering. Added: one command group (eight verbs),
one small JSON file per effort, and one `resume` call when a session takes
up existing work.

## Compatibility

A project with no `.claude-work/efforts/` behaves as before: no index is
printed, `find_work_dir` returns `current/`, archive IDs are unchanged, and
plan-session, checkpoint and end-session read `current/`. A session with no
binding in a project that has efforts also uses `current/`. One existing
inconsistency is fixed on the way: `synapse archive` now finds the folder
as the hook does (`lib/synapse/archive.py:212` used `work_dir`, the hook
`find_work_dir`, `:133`), and files the session under the project of the
folder it found. The compaction guide keeps its text for `current/` (PLAN,
EXECUTION and `CHECKPOINTS.md`, a name that nothing writes:
`lib/synapse/compact_guide.py:65`; `skills/checkpoint/SKILL.md:63`; left
for a separate change) and lists PLAN, EXECUTION and NOTES for an effort's
folder.

**Default left to the owner.** As built, effort folders start only on
request: the user names an effort, asks for effort folders, or runs the
migration. A project with no planning files still gets `current/` from
plan-session. Making effort folders the default for a project with no
planning files is a one-paragraph change in `skills/plan-session/SKILL.md`.

## Migration

For an existing large `PLAN.md`, `synapse effort migrate`:

1. **Propose (read-only).** Parses `current/PLAN.md` and
   `current/EXECUTION.md` into units: headings and `Phase` items, each with
   its line range and whether it looks finished (checked boxes, a done
   mark). Prints a JSON proposal: one effort per open unit, one closed
   `history` effort for the finished ones, the constraint lines as Fact
   candidates, and a hash of each file.
2. **Confirm.** The session shows the proposal; the user renames, merges
   and corrects it, and assigns the parts of `EXECUTION.md` (its `## Resume`
   among them) to the effort they belong to.
3. **Apply.** `synapse effort migrate --apply FILE` refuses when a file's
   hash no longer matches the proposal or a target slug exists. It first
   snapshots `current/` to the archive (a copy of PLAN, EXECUTION, NOTES,
   REPORT and ARTIFACTS, ID `YYYY-MM-DD-HHMM-pre-split`) and changes nothing
   before that succeeds. Then it writes each effort's folder from the named
   line ranges, verbatim. Lines of either file assigned to no effort go to
   the history effort, with a working `NOTES.md`, so every line lands
   somewhere. The history effort is created closed, pointing at the
   snapshot. A failed apply removes the folders it created (and `efforts/`
   if it created that). A successful one writes `efforts/.split.json` (the
   snapshot ID and the hash of each file split); while `current/` still
   matches it, propose and apply refuse, unless given `--again`, so a second
   run cannot duplicate every effort. Apply leaves `current/` untouched, so
   the snapshot's `ARTIFACTS.md` copy is not marked archived there and a
   later ordinary archive of `current/` may repeat those artifact links once.
4. **Retire the old files, on request.** `current/` is left as it is by
   default: another session may be using it. `synapse effort migrate
   --retire-current` (with `--apply` or later) moves its planning files to
   `efforts/_closed/<snapshot-id>/` and removes the marker. Until then the index keeps its one
   line about `current/`.

**Constraints become Facts.** A session lists the project's Facts at start
(`lib/synapse/facts.py:1-14`), so a repo-wide constraint belongs there and
not in a new always-read file. For each constraint the user confirms, the
session writes a Fact note with `synapse vault create-note` (type `fact`,
which requires a project, `lib/synapse/vault_write.py:668-669`) and embeds
it with `synapse extract embed-note`: the commands `/synapse:extract-session`
uses, without the extractor. The constraint lines also stay in the history
effort's PLAN, so nothing depends on that step succeeding. The start-of-session
list shows 20 Facts at most (`lib/synapse/facts.py:33`), so only repo-wide
constraints go there; one effort's constraints stay in its PLAN.

## Rejected

- **Naming the effort only** (plan-session archives and resets on a title
  mismatch). Two sessions still share the folder, and it depends on the
  model noticing the mismatch.
- **A ledger in the Synapse home** (efforts as rows with dependencies,
  PLAN and EXECUTION as generated views, after Beads). It makes the
  project's working files secondary and needs a schema. Thoughtworks' Radar
  notes that Beads' later changes "make Beads heavier than the lightweight
  tracker it started as"
  ([source](https://www.thoughtworks.com/en-us/radar/tools/beads)).
- **Status in PLAN.md front matter.** The model rewrites that file; a
  status it can overwrite by accident is the failure the JSON file avoids.
- **A generated index file.** Two sessions would write it; deriving it
  costs a few small reads.
- **A hard lock per effort.** Needs crash recovery; the advisory line is
  nearly free.
- **Binding only through a hook that parses `synapse effort` commands.**
  It cannot tell a failed command from a successful one; the session ID in
  the environment makes the CLI the reliable place.
- **Claude Code's own grouping** (session names, the shared task list ID,
  agent-team task claims). A session's name reaches hooks only when the
  user set one (`session_title`,
  [hooks](https://code.claude.com/docs/en/hooks)); the shared task list
  and the claims belong to agent teams
  ([agent-teams](https://code.claude.com/docs/en/agent-teams)). None
  carries planning files.
- **Archiving every changed effort when an unbound session ends.** An
  unbound session wrote no effort file through a tool the hook sees, or it
  would be bound.
- **Parsing the effort out of the archive ID.** `--id 2026-11-15-1029-hotfix`
  would read as an effort; the marker file is exact.
- **Moving the folder inside the close.** end-session still needs the files,
  and on Windows the rename can fail; a later sweep has neither problem.
- **Dropping the `/clear` handoff and the hook binding** (the reviewer's
  simplification). Without the handoff, which effort the pointer names
  after `/clear` is a guess when several have a fresh Resume; without the
  hook binding, an older Claude Code has no binding at all.

## Risks that need a live test

- Whether the model picks the right effort from the index unprompted, and
  starts a new one for unrelated work instead of appending.
- `/clear`: that SessionEnd (`clear`) writes the handoff inside the shared
  1.5 seconds and before SessionStart (`clear`) looks for it.
- Compaction keeping the session ID.
- Windows: `CLAUDE_CODE_SESSION_ID` in Git Bash and PowerShell tool calls;
  the folder move at close while an editor holds a file; path length for a
  deep checkout (`.claude-work/efforts/_closed/<id>/EXECUTION.md` adds up
  to about 100 characters).
- A sub-agent that runs `synapse effort resume` or `synapse checkpoint
  --stamp`: whether its environment carries the parent's session ID (the
  docs do not say).

## Measured

Measured on 2026-11-15 with the implementation in this branch, driven
through `bin/synapse` against a throwaway Synapse home and project (macOS,
Python 3; character counts are exact, token counts are an estimate at four
characters per token, since no tokenizer runs offline).

| Case | Lines | Characters | Tokens (est.) |
|------|-------|------------|---------------|
| 3 open, 2 parked, session on none | 5 | 510 | about 130 |
| 3 open, 2 parked, session on one | 5 | 443 | about 110 |
| 17 open (15 shown, the cap), every title at the 80-character clip | 18 | 2,119 | about 530 |
| 17 waiting (15 shown), every slug at 40 characters, every title and waiting text at 80 | 18 | 3,745 | about 940 |

The hook's text is cut at 4,000 characters (about 1,000 tokens): when the
lines for other checkouts would push it past that, effort lines are dropped
first and the text ends with a `- more not shown` line that names `synapse
effort list`; the command itself prints everything. That is well below the
10,000-character cap on a hook's added context. The SessionStart handler took 0.07 s of wall time with 19 effort
folders (one run).

A real run: two sessions each start an effort, a third session opens, one
effort is parked, the other is closed. The text is what `synapse effort
list` and the SessionStart hook printed.

After session A ran `synapse effort start billing-export --title "Billing
export to CSV"` and session B ran `synapse effort start ci-cache --title
"Cache the CI dependencies"`, session B sees:

```
Synapse efforts in this project: 2 open, 0 parked. This session is on ci-cache.
Its files are in .claude-work/efforts/ci-cache/; read no other effort's files. Switch with `synapse effort resume <slug>`.
- ci-cache [active] Cache the CI dependencies (just now) (this session)
- billing-export [active] Billing export to CSV (just now; another session just now)
```

A new session C, at SessionStart:

```
Synapse efforts in this project: 2 open, 0 parked. This session is on none yet.
Take one up with `synapse effort resume <slug>`, or start new work with `synapse effort start <slug> --title "..."`; read only that effort's files (.claude-work/efforts/<slug>/).
- ci-cache [active] Cache the CI dependencies (just now; another session just now)
- billing-export [active] Billing export to CSV (just now; another session just now)
```

After `synapse effort park ci-cache --reason "waiting for the runner
upgrade"`, session A sees:

```
Synapse efforts in this project: 1 open, 1 parked. This session is on billing-export.
Its files are in .claude-work/efforts/billing-export/; read no other effort's files. Switch with `synapse effort resume <slug>`.
- billing-export [active] Billing export to CSV (just now) (this session)
```

After `synapse effort done billing-export --reason "export shipped"`
(archive ID `2026-11-15-2134-billing-export`, marker
`archive/<project>/.effort/2026-11-15-2134-billing-export`, and
`- (2026-11-15) Done: export shipped` under `## Outcome` in both copies of
the PLAN), `synapse effort list --all` prints:

```
- ci-cache [parked] Cache the CI dependencies (just now): waiting for the runner upgrade
- billing-export [done] Billing export to CSV (archive 2026-11-15-2134-billing-export)
```

Session A, which ran the close, is unbound by it; its index then reads `0
open, 1 parked. This session is on none yet.` and points at `synapse effort
list --all` for the parked effort. A different session that was on
`billing-export` gets one line on its next prompt: `Synapse: effort
'billing-export' that this session was on is closed (done, archive
2026-11-15-2134-billing-export). Take up another with ...`.
