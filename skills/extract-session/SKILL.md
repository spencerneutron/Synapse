---
name: extract-session
description: Use after end-session to project the just-archived session into the Obsidian vault and the local vector database. Runs once per session at teardown. Idempotent.
allowed-tools: Bash(synapse extract *), Bash(synapse vault *), Bash(synapse where *), Bash(synapse shared status*), Bash(rm -rf *.claude-work/.tmp/extract-*)
---

# Extract Session

Promote a closed session's knowledge into the vault (Session, Decision,
Pattern, Fact notes) and the vector DB. The `synapse:extractor` agent judges;
this skill orchestrates. Use it after `/synapse:end-session` or when asked,
never before the archive exists. Vault commands start Obsidian themselves;
embedding needs Ollama with `nomic-embed-text`.

Input: a session ID (default: the one just archived, else the newest unprocessed) and a project (default: the one end-session used; ask once if clearly another).

## Steps

1. **Locate.** In one batch run `synapse where --project NAME` and
   `synapse vault verify`. Look in `archive_dir` for the ID's PLAN, EXECUTION,
   NOTES files; none: stop, report. If `.processed/ID.json` exists, ask to re-run
   (`--force`); "extract this" means yes. If verify fails twice (or Obsidian is out of date, or Linux): stop,
   quote the error, write nothing.
2. **Dispatch** `subagent_type: synapse:extractor` with the archive folder,
   the session ID, the project, whether this is a `--force` re-run, and the
   spec folder: absolute path, forward slashes, of `.claude-work/.tmp/extract-ID`
   under the project root (the folder holding `.claude-work`, else the git top level).
3. **Accept mode.** Read `accept` from the output of `synapse extract
   check-candidates --json`; missing or unreadable means `auto`. If the user
   said in this conversation to review first, treat it as `review`.
   - `auto`: ask nothing. Write every proposal as the extractor gave it
     (duplicates skipped, supersedes honoured), passing `--review-batch
     SESSION_ID` to each create-note in step 4. After step 5 print one line:
     counts per folder (e.g. "Wrote 2 Decisions, 1 Pattern, 3 Facts, 1 Session")
     and "review with `synapse extract review`". Skip the rest of this step.
   - `review`: the single question below.

   **Ask once.** Show the extractor's summary as given, with its
   "Proceed?" line, the only question. If its prior-note check was skipped,
   add that embedding needs Ollama too. Replies: yes (all), no (write nothing; `rm -rf` the spec folder),
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
   run `synapse extract supersede "[[OLD]]" --by "[[NEW]]"` (`--folder Facts` for a Fact). Report `chunks_marked`; zero is fine. If it warns the
   front matter was not updated, tell the user to set `vault_path`
   (`/synapse:doctor`).
5. **Embed.** Once: `synapse extract embed-note` with every Decision, Pattern,
   and Fact `vault_relative_path` from create-note's output (no absolute
   paths or shell loops; Facts must be embedded to show at session start),
   `--project NAME`. Then `synapse extract embed-archive SESSION_ID --project
   NAME`, plus `--force` on a re-run and `--include-report` if the user wants
   REPORT embedded. It writes the `.processed` marker. Then remove the spec
   folder (only that folder).
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
