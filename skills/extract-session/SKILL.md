---
name: extract-session
description: Project an archived session into the notes vault and the local vector database. Runs as the last step of end-session, on its own for a session the SessionEnd hook archived (the failsafe case), or when the user asks. Writes notes without asking under [extract] accept = auto and lists them for `synapse extract review`. Idempotent.
allowed-tools: Bash(synapse extract *), Bash(synapse vault *), Bash(synapse where *), Bash(synapse shared status*)
---

# Extract Session

Promote a closed session's knowledge into the vault (Session, Decision,
Pattern, Fact notes) and the vector DB. The `synapse:extractor` agent judges;
this skill orchestrates. It runs as the last step of `/synapse:end-session`; on its
own for a session the SessionEnd hook archived or when the
user asks; never before the archive exists. In Obsidian mode, vault commands start Obsidian themselves;
embedding needs Ollama with `nomic-embed-text`.

Input: a session ID (default: the one just archived, else the newest unprocessed) and a project (default: the one end-session used; ask once if clearly another).

Run every command as its own Bash call that starts with `synapse`: no `cd`,
variables, `ls`, loops, or `&&` chains. The on-exit run is headless and
approves only those calls and Read, Write, and Agent; anything else is denied.

## Steps

1. **Locate.** In one batch run `synapse where --project NAME` and
   `synapse vault verify`, then `synapse extract status ID --project NAME`.
   Read `PLAN_ID.md`, `EXECUTION_ID.md`, `NOTES_ID.md` (ID = the session ID) in `archive_dir` by full path;
   none: stop, report. If status says it was processed, ask to re-run
   (`--force`); "extract this" means yes. If verify fails twice (or, in Obsidian mode, Obsidian is out of date or on Linux): stop,
   quote the error, write nothing.
2. **Dispatch** `subagent_type: synapse:extractor` with the archive folder,
   the session ID, the project, whether this is a `--force` re-run, and the
   spec folder: absolute path, forward slashes, of `.claude-work/.tmp/extract-ID`
   under the project root (the folder holding `.claude-work`, else the git top level).
3. **Accept mode.** Run `synapse extract check-candidates
   SPEC/candidates.json --session ID` and read `accept` from its JSON; missing
   or unreadable means `auto`. If the user
   said in this conversation to review first, treat it as `review`.
   - `auto`: ask nothing. Write every proposal as the extractor gave it
     (duplicates skipped, supersedes honoured), passing `--review-batch
     SESSION_ID` to each create-note in step 4. After step 5 print one line:
     counts per folder (e.g. "Wrote 2 Decisions, 1 Pattern, 3 Facts, 1 Session")
     and "review with `synapse extract review`". Skip the rest of this step.
   - `review`: the single question below.

   **Ask once.** Show the extractor's summary as given, with its
   "Proceed?" line. If its prior-note check was skipped,
   add that embedding needs Ollama too. Replies: yes (all), no (write nothing; `synapse extract cleanup SPEC`),
   skip with item numbers, or overrides ("keep decision 2 without supersedes",
   "keep the duplicate", renames). After a rename, show it again.
   Edit specs in the spec folder. Skip `duplicate-*.md` unless kept. Keep the session spec's link lists (Decisions made,
   Patterns surfaced, Facts recorded) matching: drop a skipped note's link,
   add a kept duplicate's.
4. **Write.** For each approved spec file, Decisions, Patterns, and Facts
   first, the Session note last (links resolve):
   `synapse vault create-note --from-md PATH` (`auto`: add `--review-batch SESSION_ID`). Never pipe or inline a spec. Check exit 0 and `"created": true`. A title that exists: pass
   `--on-conflict suffix`, always for the Session note on a re-run. Never
   suffix a Fact: drop it, or retitle it with `supersedes` if changed.
   For each note with `supersedes`, create-note does not mark the old one, so
   run `synapse extract supersede "[[OLD]]" --by "[[NEW]]"` (`--folder Facts` for a Fact). Report `chunks_marked` (zero is fine). If it warns the
   front matter was not updated, tell the user to set `vault_path`
   (`/synapse:doctor`).
5. **Embed.** Once: `synapse extract embed-note` with every Decision, Pattern,
   and Fact `vault_relative_path` from create-note's output (no absolute
   paths or shell loops; Facts must be embedded to show at start),
   `--project NAME`. Then `synapse extract embed-archive SESSION_ID --project
   NAME`, plus `--force` on a re-run and `--include-report` if the user wants
   REPORT. It adds the Artifact links to the Session note (the extractor
   lists none) and writes the `.processed` marker. Then run
   `synapse extract cleanup SPEC_FOLDER`.
6. **Report** briefly (`auto`: the one summary line plus embed counts): notes created (store-relative paths, forward slashes),
   chunks embedded. If `synapse shared status` lists a team and notes were
   promoted, offer `/synapse:share` in one line; never share here.

## Failures

- A write fails midway: no rollback. Report what worked and failed, keep the
  spec folder, give its path; stop.
- Embedding fails (Ollama): the notes stay. Say so; re-run
  `synapse extract embed-archive SESSION_ID --project NAME --force`.
- Nothing to promote: still create the Session note and embed; say so.

Work silently.
