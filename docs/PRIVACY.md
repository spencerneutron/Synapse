# Synapse privacy policy

Synapse is a Claude Code plugin that runs on your computer. Its author runs no
server and receives no data from it: no account, no telemetry, no analytics.
This policy says what Synapse stores, where, and what it sends. The README's
"Security and data" section lists the same facts with the commands behind them.

## What Synapse collects and why

Synapse gives Claude Code a memory across sessions. To do that it keeps notes
derived from your sessions:

- **Planning files.** Under Synapse's skills, the model writes `PLAN.md`,
  `EXECUTION.md` and `NOTES.md` (the plan, the current task, open questions
  and decisions) in your project's `.claude-work/current/`. The Stop hook
  records the title and link of each Artifact the session published in
  `ARTIFACTS.md` there.
- **Session notes.** `/synapse:end-session` has the model write a session
  notes file (open questions, decisions, facts you stated, in your words or a
  close paraphrase) directly into the store's archive.
- **Archives and notes.** The archive copies the working files into a store.
  Extraction turns the archive into Session, Decision, Pattern and Fact notes
  in an Obsidian vault and into a local SQLite database (`vectors.db`) that
  holds the text of each chunk, its embedding and a full-text index.
- **Recall.** Later sessions get ranked snippets of those notes as hints, and
  the project's Fact notes at session start. To rank them, the first 1,000
  characters of each prompt are embedded through Ollama on your machine; the
  prompt itself is not stored.

Synapse does not copy Claude Code's session transcripts. Its hooks read the
end of the current transcript for token counts and Artifact links, and
`/synapse:workflow-recovery` reads a workflow's journal and agent transcripts
when you ask it to recover a run.

## Where it is stored

Everything stays on your computer, in folders you can list with
`synapse where`: the Synapse home (`synapse` under `$CLAUDE_CONFIG_DIR` or
`~/.claude`, or `SYNAPSE_HOME`), any store or team folder you configured
elsewhere, your project's `.claude-work/`, and your
Obsidian vault.

## What leaves your computer

- **Ollama**, on `localhost:11434`: embeddings are computed locally.
- **Setup**: `synapse setup` downloads `sqlite-vec` from PyPI;
  `/synapse:setup` downloads the `nomic-embed-text` model from Ollama's
  registry after you agree.
- **Teams (only if you create or join one).** `synapse share add` refuses a
  note that fails its check for paths and secrets, and accepts only Decision,
  Pattern and Fact notes. Synapse's rules ask the model to share only the notes
  you approve one by one and to run `synapse shared push` only after you say
  yes; the command itself pushes when run. A git team gets a commit and is
  pulled in the background when a sync is due; a folder team's file is carried
  by your sync service. Your teammates and the host of that repository or
  folder see what you share.
- **Detached extraction (off by default).** With `[extract] on_exit = true`,
  a headless Claude Code session runs extraction at session end. It uses your
  own Claude login and is covered by Anthropic's terms and privacy policy.

- **The model.** Notes Synapse puts into a session (recall hints, Facts, the
  resume pointer) are part of that session's context, so they reach Anthropic
  like anything else in the session, under Anthropic's terms.

Synapse sends nothing else anywhere.

## Retention and deletion

Synapse keeps what it stores until you delete it. Deleting the Synapse home
removes the default store and the team clones under it; delete any store or
team with its own `path`, your vault notes and `.claude-work/` folders
yourself. Notes already
pushed to a team stay in that team's repository. [INSTALL.md](../INSTALL.md)
covers uninstall.

## Contact

Questions and security reports: <https://github.com/spencerneutron/Synapse/issues>.

This policy can change with a release; the version at a release tag applies to
that release.
