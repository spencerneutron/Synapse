---
name: extract-session
description: Use after end-session to project the just-archived session into the Obsidian vault and the local vector database. Runs once per session at teardown. Idempotent — safe to re-run.
allowed-tools: Bash(synapse extract *), Bash(synapse vault *), Bash(synapse where *), Bash(synapse shared status*)
---

# Extract Session

Promote a closed session's durable knowledge into the vault (Session,
Decision, Pattern, Fact notes) and the vector DB. The judgment runs in the
`synapse:extractor` agent; this skill orchestrates. Use it right after
`/synapse:end-session`, or when the user asks to extract a session. Not
before the archive exists. Vault commands start Obsidian themselves;
embedding needs Ollama with `nomic-embed-text`.

Input: a session ID (default: the one just archived, else the newest without
a `.processed/ID.json`) and a project (default: the one end-session used).

## Steps

1. **Locate.** In one batch run `synapse where --project NAME` and
   `synapse vault verify` (it starts Obsidian while the user answers). Look
   in `archive_dir` for the ID's PLAN, EXECUTION, NOTES files; if all are
   missing, stop and report. If `.processed/ID.json` exists, ask whether to
   re-run (`--force`); "extract this" means yes. If verify fails,
   run it once more; still failing (or Obsidian out of date, or Linux): stop
   and quote the error. Write nothing.
2. **Dispatch** `subagent_type: synapse:extractor` with the archive folder,
   the session ID, the project, and whether this is a `--force` re-run.
3. **Ask once.** Show the extractor's summary as given, with its
   "Proceed?" line; that is the only question. If its prior-note check was
   skipped, add that the embed steps need Ollama too. Replies: yes (write all), no (write nothing), skip with item
   numbers, or overrides ("keep decision 2 without supersedes", "keep the
   duplicate", renames). After a rename, show the summary once more. For
   edits, change the spec files in the extractor's folder.
4. **Write.** For each approved spec file, Decisions, Patterns, and Facts
   first, the Session note last (links resolve):
   `synapse vault create-note --from-md PATH`. Never pipe a spec or pass it
   inline: brace-and-quote command lines trigger safety prompts. Check exit 0 and
   `"created": true` each time. A title that exists: pass
   `--on-conflict suffix`, always for the Session note on a re-run. Never
   suffix a Fact: drop it, or if it changed, retitle it with `supersedes`.
   For each note with `supersedes`, create-note does not mark the old one, so
   run `synapse extract supersede "[[OLD]]" --by "[[NEW]]"` (add `--folder
   Facts` for a Fact). Report `chunks_marked`; zero is fine. If it warns the
   front matter was not updated, tell the user to set `vault_path` (see
   `/synapse:doctor`).
5. **Embed.** Once: `synapse extract embed-note` with every Decision, Pattern,
   and Fact `vault_relative_path` from create-note's output (no absolute
   paths, no shell loops; Facts must be embedded to show at session start),
   `--project NAME`. Then `synapse extract embed-archive SESSION_ID --project
   NAME`, plus `--force` on a re-run and `--include-report` if the user wants
   REPORT embedded. It writes the `.processed` marker. Then remove the extractor's
   spec folder (from `mktemp -d`; only that folder).
6. **Report** briefly: notes created (store-relative, forward slashes),
   chunks embedded, marker. If `synapse shared status` lists a team and notes
   were promoted, offer `/synapse:share` in one line; never share here.

## Failures

- A write fails midway: do not roll back. Report what worked and what
  failed; stop.
- Embedding fails (Ollama): the notes stay. Say so; the user can re-run
  `synapse extract embed-archive SESSION_ID --project NAME --force`.
- Nothing worth promoting: the Session note is still created and the archive
  embedded; say "Session ID had no decisions, patterns, or facts worth
  promoting."

Work silently.
