# Changelog

## 2.8.0 — 2026-11-09 — Notes without Obsidian

No store schema change; existing configs keep Obsidian mode. Update with
`claude plugin update synapse@synapse` and start new sessions.

### Added

- **Folder mode.** A store with `notes = "folder"` in `[stores.<name>]` keeps
  its notes in a plain folder: `vault_path`, default `<store>/vault` (inside the
  store). The subfolders and Markdown notes are the same, extraction,
  recall, facts, review, share and supersede work unchanged, and the
  `obsidian` CLI is never run.
- **`synapse setup --notes obsidian|folder`.** When setup creates
  `config.toml`, it uses the flag; otherwise it asks once in a terminal;
  otherwise it picks Obsidian if the CLI or Obsidian's config file is present,
  else a folder. An existing config is not changed; a differing `--notes`
  prints a to-do line.

### Changed

- **`synapse doctor` checks only the mode in use.** Folder mode gets a `notes`
  check (folder exists, is absolute, is writable, has the subfolders).
- **`synapse vault verify` in folder mode** creates missing subfolders;
  `synapse vault search` there points to `synapse recall`. No Obsidian Base
  file for Artifacts is written.

## 2.7.4 — 2026-11-08 — The wait message says what to do

No store schema change; update with `claude plugin update synapse@synapse`
and start new sessions.

### Changed

- **The Stop hook's hold while a sub-agent runs says what to do.** It now
  asks for a one-line message naming what the session waits for, and says the
  agent's report or the user's next message resumes it, instead of "wait for
  its report". Sessions had read "wait" literally and started background
  polling shells (an `until grep` loop on the agent's output) that the
  harness never needed, since it resumes the model itself when the agent
  reports. The emission contract gains the same rule (Directive item 7 and a
  line in the hook's compact directive).

## 2.7.3 — 2026-11-08 — On-exit extraction works in every permission mode

No store schema change; update with `claude plugin update synapse@synapse`
(it refreshes the marketplace itself), then start new sessions.

### Fixed

- **On-exit extraction extracted nothing in default permission mode.**
  Through 2.7.2, with `[extract] on_exit = true`, the extractor wrote its
  spec files by shell (`mkdir -p`, `cat >` heredocs) and the skill ran
  `ls`, `cd` and variable chains. The headless run's allow list covers none
  of these, so in default mode they were denied and the session stopped
  without writing. It worked only when the user's own auto mode approved
  them. The extractor now writes spec files and `candidates.json` with the
  Write tool and clears its folder with `synapse extract cleanup`. The skill
  reads `PLAN_<id>.md`, `EXECUTION_<id>.md` and `NOTES_<id>.md` by name and
  runs each `synapse` command as its own call. It no longer cites a
  `check-candidates --json` flag, which does not exist.
- **The detached run is held to its allow list.** It runs with
  `--permission-mode dontAsk`, so it denies anything outside
  `Bash(synapse extract|vault|where|shared status …)`, Read, Write and Agent
  in every permission mode, including the user's auto mode. Sub-agents
  inherit the mode. The list no longer has `Edit` or a raw `rm -rf`. Live
  runs in default mode and under a user-level auto mode completed with no
  command approved outside the list.

### Added

- **`synapse extract cleanup <folder>`** deletes an extraction spec folder.
  It refuses symlinks and any path not shaped `.claude-work/.tmp/extract-*`.
- **`synapse doctor` warns about another plugin named `synapse`** in
  `enabledPlugins` (any settings layer) or `installed_plugins.json`, and
  INSTALL.md's preflight table has a row for it.
- **README "Security and data"**, rewritten as a full disclosure: what
  Synapse keeps from sessions, what hooks read, the network, the detached
  extraction, every write location, and removal. It links the new
  `docs/PRIVACY.md` and `docs/TERMS.md` (drafts).
- **Plugin directory fields** in `plugin.json`: `displayName`,
  `documentationUrl`, `supportUrl`, `privacyPolicyUrl`, `termsOfServiceUrl`
  and `icon` (a placeholder `.claude-plugin/icon.png`). The description
  says "Claude Code only".
- **`NOTICE`**: `lib/py.sh` is a modified version of `sg-python.sh` from the
  security-guidance plugin in anthropics/claude-plugins-official, under the
  Apache License 2.0.

### Changed

- **Hook commands carry no environment prefixes.** `hooks.json` runs each
  hook as a plain `bash "${CLAUDE_PLUGIN_ROOT}/…"` path; `lib/py.sh` takes
  `--optional` and `--min-py X.Y` as arguments (it still honours the old
  variables). Timeouts, matchers and order are unchanged.

## 2.7.2 — 2026-11-08 — Artifact links in the Session note

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.

### Added

- **Every published Artifact reaches the Session note.** At each stop,
  `synapse gate --hook` reads the turn's `Artifact` publishes from the same
  transcript tail it already reads, plus the links in the final message, and
  records each one in `.claude-work/current/ARTIFACTS.md` as
  `- [title](url)`. The title is the publish's title, else the file name,
  else the link's last segment. A republish of the same link updates its
  title in place. A link the turn only opened or read is not recorded, even
  when the final message repeats it. The file appears only when a session
  publishes an Artifact.
- **The archive carries it.** `synapse archive` and the SessionEnd archive
  copy the links recorded since the last archive as `ARTIFACTS_<id>.md`, then
  mark them archived in `ARTIFACTS.md`, so each session lists only its own
  links. A new link since the last archive is enough for the SessionEnd
  archive to run; a resumed session that adds links merges them into its
  unextracted archive.
- **Python writes the links, not the model.** `synapse extract
  embed-archive` adds a `## Artifacts` section to the session's Session note
  with the same lines, mirrors the links into an `artifacts:` property, and
  embeds the section, so recall finds the Session note by an Artifact's
  title. Text you add under the heading stays. Re-running it leaves one
  section and one property, on the newest version of the note. The
  extractor no longer lists Artifact links itself.
- **`Artifacts.base` in the vault.** An Obsidian Base at the vault root
  lists every note with an `artifacts` property: session, date, project and
  links. Synapse creates it when it is missing and never overwrites it.
- **`[extract] artifacts = true`.** `false` stops the recording.

### Known limits

- A turn the user interrupts gets no Stop hook, so an Artifact published
  in it is recorded only if a later final message repeats its link.
- A session with no `PLAN.md` or `EXECUTION.md` is never archived; its links
  wait in `ARTIFACTS.md` and go to the next session that is.

## 2.7.1 — 2026-11-08 — The window from the auto-compaction point

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.

### Fixed

- **The 90% mark never fired before the first compaction.** Claude Code
  auto-compacts 33k tokens before its auto-compact window (the buffer its
  context display reports, whatever the model). With the 300k window the
  README and `synapse setup --autocompact` recommend, compaction runs near
  267k, but Synapse measured against 300k, so its 90% mark (270k) sat above
  the compaction point. Only after a first auto-compaction did the window
  drop to that compaction's size and the mark start working.
- **The window now comes from the compaction point.** When `[nudge]
  context_window` is unset and Claude Code's settings set an auto-compact
  window for the session's model (`modelSettings.<model>.autoCompactWindow`,
  top-level `autoCompactWindow` in any settings layer, or
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, which wins), the nudge and the gates use
  that window, clamped to 100k-1M and capped at the model's window, less
  33k: 300000 gives 267000, so the deny gate opens at 134k and the marks land
  at 160k and 240k. The `modelSettings` key matches the transcript's model
  case-insensitively, ignoring a `[1m]` suffix or a date suffix. With no
  setting the defaults stay (300000 for 1M-window models, 150000 for older
  ones), and an observed auto-compaction still only lowers the window.
  `[nudge] context_window` remains the override.

### Changed

- `synapse doctor`'s `autocompact-window` line and `synapse setup
  --autocompact N` say where Claude Code compacts for each window found and
  where the deny gate, 60% and 90% land.
- The settings lookup moved from `doctor.py` into `lib/synapse/autocompact.py`,
  shared by doctor, setup and the hooks. It reads up to four small JSON files
  (about 0.05 ms); the hooks' per-call time is unchanged (about 49 ms).
- Tests point `CLAUDE_CONFIG_DIR` at a temporary folder, so the developer's
  own Claude Code settings never change a test's window.

## 2.7.0 — 2026-11-08 — Gates and the tail end

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.
Why: rules decay. Issues #11 and #18 measured that the main session's share
of cost stayed at 88-96%, that the context nudge fired three times with no
checkpoint after it, and that the emission skill was loaded in 5 of 91 turns.
A line the model reads is advice; a hook gate holds. 2.7.0 adds three, and
moves the session's tail end (archive, extraction) off the model's memory:
the archive runs from a SessionEnd hook, and extraction writes its notes
for review afterwards instead of asking first.

### Added

- **PreToolUse cost-aware deny.** `synapse gate --hook` runs before Edit,
  Write, MultiEdit, NotebookEdit, Bash and PowerShell calls. When the step's
  hands-on count reaches `[nudge] calls` (5), then 10, then 20, and the
  context is at least `[gate] min_context` (default 0.5) of the window, the
  next hands-on call is denied once with this reason: "Synapse gate: N
  hands-on calls in this step at about Xk context (each call here costs about
  Yk base-equivalent). Brief the rest of this step to synapse:implementer
  (goal, files, failing command, done condition, attempt limit) or
  synapse:scout / synapse:researcher for searches, then read the report. This
  gate lifts after a dispatch or on the next prompt." The retry is allowed.
  The `synapse` CLI, edits under `.claude-work/`, and `git commit`, `git
  push` and `gh pr` are never denied.
- **Stop checkpoint ask.** At 60% of the window or more, if `## Resume` in
  `EXECUTION.md` was not written since the context crossed that mark, the
  Stop hook blocks once: "Synapse: the context is about Xk tokens. Run
  /synapse:checkpoint now (rewrite ## Resume in EXECUTION.md, append to
  NOTES.md, `synapse checkpoint --stamp`), then finish your message." At most
  once at 60% and once at 90% per session; never when `stop_hook_active` is
  set; below 90% only when `.claude-work/current/` exists.
- **Project overrides.** A project's `.synapse.toml` may set `[nudge]` and
  `[gate]` keys for that project. Other tables there are ignored.
- **Config.** `[gate] enabled = true`, `min_context = 0.5`, `checkpoint =
  true`.
- **Eval cases** `long-loop-gate` and `checkpoint-gate` (tag `gate`).
- **Doctor** reports other `PreToolUse` hooks (`pretooluse-hooks`, info).
- **Wait-for-agents Stop ask.** After the checkpoint ask, when the Stop
  input's `background_tasks` lists a sub-agent still running, the Stop hook
  blocks once per prompt: "Synapse: a dispatched agent is still running.
  Wait for its report and verify it before ending the turn; if it asked a
  question, answer it or relay it." Never when `stop_hook_active` is set.
  The field does not say which turn started a task, so any running sub-agent
  counts. `[gate] wait_for_agents = false` turns it off.
- **Archive at session end.** A `SessionEnd` hook, `synapse archive --auto
  --hook`, copies `.claude-work/current/` (PLAN, EXECUTION, REPORT, NOTES)
  into the archive at exit, `/clear` and `/resume`. No model call, no
  embedding, no DB. It skips when nothing changed since this session's last
  auto archive or since the newest archived session (NOTES left out of that
  comparison, so a hand `/synapse:end-session` is not archived twice), and
  reuses the session's archive ID until that ID is extracted. Wall time on
  this Mac: median 61 ms when it writes, 58 ms when it skips (budget 1.5 s,
  shared by all SessionEnd hooks). SessionEnd never runs after a crash; INSTALL
  says how to raise the budget. `[archive] on_exit = false` turns it off.
  Doctor reports other `SessionEnd` hooks (`sessionend-hooks`, info).
- **Extraction writes notes without asking (`[extract] accept = auto`).**
  `/synapse:extract-session` now writes every proposed note and records the
  batch in `<store>/review.json`; `synapse extract review` lists the notes
  written since the last review (`--done` marks them reviewed, `--json` for
  skills). `accept = review` keeps the old one-by-one approval.
  `/synapse:end-session` runs extraction as its last step in either mode.
- **Start-of-session review line.** When automatic extraction wrote notes
  not yet reviewed, the session starts with: "Synapse: N notes were written
  by automatic extraction since YYYY-MM-DD; `synapse extract review` lists
  them."
- **Config.** `[gate] wait_for_agents = true`, `[extract] accept = "auto"`,
  `[archive] on_exit = true`, `[extract] on_exit = false`.
- **Detached extraction at exit (`[extract] on_exit`, off by default).**
  After an auto archive that wrote, the SessionEnd hook starts a detached
  headless `claude -p "/synapse:extract-session ID"` on Sonnet (new session
  group, hooks off, `SYNAPSE_DETACHED=1`, log at
  `<home>/state/extract-<id>.log`) and returns. Checked on macOS with a real
  `claude -p` parent: the child kept running with PPID 1 after the parent
  exited, signed in with the normal login, wrote one Session, Decision,
  Pattern and Fact note plus the review entries and the `.processed` marker,
  for $0.21 (4 turns, 18 s) on a small archive. The hook with the spawn takes
  61 ms. Off by default because it spends money at every exit. Windows
  (`DETACHED_PROCESS`) is untested.

### Measured (Sonnet, 3 runs per arm, eval contexts under 40k)

`checkpoint-gate` (window set to 30000 so the gate fires in an eval):

| Arm | `## Resume` written | Bug fixed | Reply ends on the answer | Cost per run |
|---|---|---|---|---|
| 2.6.1 (context nudge, same window) | 0/3 | 3/3 | 3/3 | $0.076 |
| 2.7.0 Stop gate | 3/3 | 3/3 | 3/3 | $0.116 |
| No plugin | 0/3 | 3/3 | 3/3 | $0.050 |

`long-loop-gate` (`min_context = 0`; the prompt calls the ten-round loop a
one-line fix, so the main session starts hands-on):

| Arm | Dispatched | Main hands-on calls before the dispatch | Suite passes | Cost |
|---|---|---|---|---|
| 2.6.1 nudge | 3/3 | 5, 5, 5 | 2/3 | $0.94 |
| 2.7.0 gate | 3/3 (each right after one deny) | 6, 6, 7 (the denied call included) | 2/3 | $1.11 |

In fresh eval sessions the nudge already works, so the deny adds nothing
measurable there; it is aimed at long sessions where the line stopped
working (#11, #18), which an eval cannot reach. The one failure per arm
dispatched in the background and ended the turn before the report came
back. With the case's first prompt ("get it passing") both versions
dispatched on the first call and the gate never fired. `emission-contract`
with the recalibrated grader: 1.00 with Synapse, 0.75 without.

### Changed

- **The nudge's dispatch line runs only below `min_context`.** Above it, the
  gate's deny replaces that line.
- **`core.md`, two edits.** The five-calls sentence now says the gate denies;
  the Checkpoint row adds "or when the Stop gate asks".
- **Grader calibration.** `evals/emission-contract/graders/outcome-and-substance.md`
  accepts one closing decision question ("Should I do that?") and still fails
  offers.

## 2.6.1 — 2026-11-08 — Enforcement over instruction

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.
Why: issues #11 and #18 measured that a rule the model reads holds only while
fresh. The emission contract was loaded in 5 of 91 turns, always in a
session's first two turns or the first turn after a compaction, and in none
of 18 turns after a resume. Hook gates hold. So the Stop hook now carries the
contract, and the per-turn skill load (one extra full-context request per
turn) is gone.

### Changed

- **The Stop hook carries the emission contract.** When `emission_check.py`
  blocks, its reason lists what it found and then the contract's directive in
  compact form: lead with the outcome, evidence not effort, size to the ask,
  specifics, end on substance, plain words. The rewrite needs no skill load,
  and the reason no longer asks for one. The directive lives in
  `hooks/emission_patterns.json` (`directive`), and a test keeps it in step
  with the skill's Directive. The hook still fails open, and now logs the
  exception type and message to stderr.
- **New mechanical checks.** A closing summary paragraph ("In summary",
  "To recap", "To summarize", "Overall,"). Offers in the last paragraph ("I
  can also", "Would you like me to", sentence-initial "Want me to", "Shall
  I", "I can … if you'd like", "I can fix any of these", "… if you want
  one"). "It's not just X, it's Y" in its plain forms. More than 3 headings
  in a message under 500 words. Over 729 real final messages on the
  maintainer's machine, the new checks fire on 2 (the same offer, counted
  twice) and on no false positive found.
- **`core.md` Emission** is two sentences: the Stop hook enforces the
  contract and its block reason carries the rules; `synapse:emission-contract`
  is the reference. The skill's description no longer asks for a load before
  every final message, and the lifecycle table's Emit row now reads
  "Reference only; the Stop hook checks every final message".
- **Context-nudge window is derived per session.** The default of 300000 never
  fired on 200k-window models. With `[nudge] context_window` unset, the 60%
  and 90% marks use a rule on the model name: 300000 for 1M-window models
  (Fable, Opus 4.7 and later, any 5-series model), 150000 for older ones
  (a bare alias such as `opus` counts as 1M-window). The smallest
  auto-compaction size seen in the session (a manual `/compact` is ignored;
  kept in `context-<sid>.json`) lowers that window, never raises it. No
  model table, so nothing goes stale when models ship. The nudge line names
  the window and its source, e.g. `(window 150k, from the model)`. An
  explicit value still wins, and `0` still turns the lines off.

### Added

- **Prompt digest.** On every prompt, `synapse nudge --hook` adds one line
  (148 characters): a step over about five tool calls or three files is a
  brief for a role, and the Stop hook checks the final message.
  `[nudge] digest = false` turns it off.
- **`synapse setup --autocompact N`** (`N` or `Nk`) writes top-level
  `autoCompactWindow` into the user's `~/.claude/settings.json`, after copying
  the file to `settings.json.synapse-backup-<time>` beside itself. It refuses,
  and changes nothing, when a window is already set at the top level or under
  `modelSettings`. Without the flag, `synapse setup` prints the doctor's
  advice and this command when no window is set; `/synapse:setup` asks before
  running it, and the flag form is not in the skill's allowed tools, so Claude
  Code asks too. `synapse doctor` reports every value found (top level and per
  model, with the file) or its absence. INSTALL.md's preflight table has a
  row for it.
- **`tools/emission-stats.py TRANSCRIPT...`** counts, per transcript and main
  session only: turns (`stop_hook_summary`), Stop-hook blocks (`hasOutput`),
  and emission-contract loads (deduped by tool_use id), split by turn origin
  (user prompt, slash command, notification or agent hand-back), with the
  Synapse version from the plugin cache path, the model, and compactions.
  `--json` for machine output.
- **Eval case `emission-contract`** (`core`): a small fix whose natural ending
  tempts a recap, an offer, and a header-heavy overview. Regex graders for
  the mechanical patterns and the header cap, an LLM judge for "leads with
  the outcome" and "ends on substance".
- **`[continuation] compact_guide = false`** turns the PreCompact guidance
  off: `synapse compact-guide --hook` then prints nothing. A missing or
  invalid config leaves it on.
- **`tools/live-check-compact.sh --arms on|off|both`.** The off arm runs the
  same planted-item session with the guidance turned off, so the two arms
  show what the hook adds over Claude Code's default summary (hook stdout is
  not in transcripts). Each arm first checks that the hook is on or silent
  as intended, before any paid call. A turn 2 that stops early (budget)
  after a compaction no longer skips the recall turn. About $0.55 per arm
  per run.
- **cp1252 usage-text test** (`tests/test_cli_encoding.py`). Runs every
  command's usage and `--help`, and every subcommand's `--help`, with stdout
  forced to cp1252 as on Windows, and fails unless the output is UTF-8.

### Fixed

- `synapse help`, `synapse archive --help` and `synapse compact-guide`
  (usage) printed their em dash as cp1252 byte 0x97 on Windows; they now
  write UTF-8, like the 2.5.1 and 2.6.0 fixes for `nudge` and `checkpoint`.
  `cli.main` now reconfigures stdout and stderr for every command, and the
  `tools/*.py` scripts do the same, so the fix is no longer per module. The
  test also covers `tools/*.py` and `hooks/*.py`, so the bug fails locally on
  any OS instead of on Windows CI (it caught `build_context.py`,
  `build_eval_home.py` and `eval-report.py`). Installed paths were never
  affected: `lib/py.sh` sets `PYTHONUTF8=1`.

### Dropped

- **Small-model judge for the judgment-only rules.** A `claude -p --model
  haiku` call does run inside a Stop hook (no nested-session refusal), but it
  took 4.1 s for a trivial prompt and 6.0 to 6.5 s for a 324-word message,
  over the 5-second budget for every turn end. `--bare` would be faster but
  needs an API key, which subscription users do not have. No config key.

## 2.6.0 — 2026-11-06 — Continuation assist

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.
The design is `docs/design/continuation-assist.md`.

### Added

- **`/synapse:checkpoint`.** Writes `## Resume` in
  `.claude-work/current/EXECUTION.md` and appends to the working
  `.claude-work/current/NOTES.md`: facts the user stated, patterns, decision
  rationale, open questions, deferred and blocked work. It does not end the
  turn and is safe to run twice. At the end it says once that `/clear` costs
  nothing after a checkpoint and `/compact` loses detail, then work goes on.
  `synapse checkpoint --stamp` writes `Checkpoint written: YYYY-MM-DD HH:MM
  +HH:MM` in the Resume section, because the model does not know the clock
  time and the resume pointer needs a stamp it can parse. Without a stamp
  the pointer uses the file's modification time.
- **Resume pointer.** On SessionStart after `compact` or `clear`, one line
  names `.claude-work/current/EXECUTION.md` `## Resume` and when it was
  written. It is silent for other sources. It points; it inlines nothing.
- **Context-size nudge.** The nudge hook reads the exact context from the
  last assistant `usage` in the transcript (input + cache read + cache
  creation), from the tail of the file only (64 KiB chunks, 2 MiB cap). At
  60% and at 90% of `[nudge] context_window` (default 300000; `0` turns it
  off) it adds one line. It fires again only after the context has dropped
  below 60% (after a compaction), at most 3 times per session, in the main
  session only.
- **Resume-time line.** On UserPromptSubmit, when the last request is older
  than the cache lifetime in use (1 hour or 5 minutes, from
  `usage.cache_creation`; unknown counts as 1 hour) and the context is at
  least 60% of the window, one line states the idle time, that the cache
  expired, about how many tokens the next request rewrites, and that a
  checkpoint before stepping away keeps `/clear` free.
- All three context features run inside the existing `synapse nudge --hook`
  process (`lib/synapse/continuation.py`). There is no new hook entry, no
  new matcher, and no new process start. The hook still exits 0, never
  blocks or returns a decision, stays silent on any error, and uses no
  Ollama or database.
- `tools/live-check-compact.sh` (paid, `--yes`, about $0.55 per run) checks
  what survives automatic compaction in a headless session.

### Changed

- `/synapse:end-session` step 4 starts from the working `NOTES.md` and
  appends `<!-- merged into NOTES_<id> -->`; the next checkpoint starts the
  file fresh. No archive or extractor code changed, and there is no
  `CHECKPOINTS.md`.
- `instructions/core.md` has a Checkpoint row in Session Lifecycle and one
  Token / Context bullet (8,323 to 8,615 characters).
- `tools/context-cost.py` counts cold resumes (gap longer than the cache
  lifetime, cache writes above reads, at least 1,000 writes) with their
  cost. It now dedupes entries by uuid, because Claude Code copies earlier
  entries into the same transcript; on a 203 MB local transcript
  compactions went from 6 to 5. An unreadable transcript path is an error
  (exit 1, stderr names the path) instead of an all-zero report, and a file
  with no requests prints a numbers-only diagnostic on stderr. Sub-agent
  transcripts are read recursively (Workflow agents), skipping
  `journal.jsonl`. Checkpoints count only real invocations (the slash
  command or a Skill call), not prose or compaction summaries that name
  it. Timestamps without an offset are read as UTC.

### Correction to earlier figures

- The figures for issue #11 in `docs/design/cost-sweep.md` and
  `docs/design/continuation-assist.md` were overstated about 2.4 times: the issue body counted
  transcript lines, and Claude Code repeats one response's usage on 2 to 3
  lines. Corrected (maintainer's re-measurement, #11 comments, 2026-11-06
  21:28 UTC): Session A 317 main requests (not 757), 114.4M main cache
  reads (not 275M), mean context 366k (not 364k), main share of cost
  85.6%; Session B 187 requests (not 452), 47.6M (not 114M), 66.5% once
  its six workflow agents are counted (21:38 UTC comment; the issue body's
  "9-agent workflow plus 3 Opus reviews" was 9 agents in all). Two
  more sessions: C 91.0% and D 95.6%, each auto-compacted once (385k and
  307k). The finding stands: the main session re-reading its context is 66
  to 96 percent of cost in six sessions on two machines that used
  sub-agents (this Mac's three largest: 94.8%, 88.5%, and 100% in one
  with none). The design
  docs are fixed; older entries below are not rewritten.
- Auto-compaction does not run only near 967k: observed runs on the
  maintainer's machines were at 307k, 385k, 393k, 461k, 854k and 968k. The
  300k recommendation stays as the setting that makes it predictable.

### Measured

- **Hook latency** on macOS (20 runs, 206 MB synthetic transcript), median
  and max in ms, after the review fixes: PostToolUse 55 and 56,
  UserPromptSubmit 56 and 58, SessionStart `compact` 53 and 57. The 2.5.1
  baseline was 48 ms median on the same transcript.
- **Compaction retention** (`tools/live-check-compact.sh`, one run, Sonnet,
  $0.52, 2026-11-06). Auto compaction went from 76,614 to 21,121 tokens. All
  7 planted words (a stated fact, a decision with its rationale, an open
  question) were recalled afterwards. The planted turn was not among the
  messages compaction keeps word for word, so the 5,037-character summary
  carried them. Hook stdout, including the PreCompact guidance, is not
  recorded in transcripts, so this checks retention, not the hook's effect
  on it.

### Unverified

- Hook latency on Windows.
- The effect on real long sessions. After installing, run
  `tools/context-cost.py` on your own transcripts to measure it.
- The checkpoint skill's live behavior. There is no eval case for it yet.

## 2.5.1 — 2026-11-06 — A hook for the dispatch rule

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.

### Added

- **A nudge hook for the dispatch rule.** A PostToolUse hook,
  `synapse nudge --hook`, counts consecutive hands-on tool calls in the
  main session (Bash, PowerShell, Edit, Write, MultiEdit, NotebookEdit).
  A sub-agent dispatch (Agent or Task) resets the count, and so does each
  new user prompt; a sub-agent's own calls are ignored. At 5 calls, then at
  10 and 20, it adds one line of context telling the main session to brief
  the rest to a role: `synapse:implementer` for changes, `synapse:scout`
  or `synapse:researcher` for searches. Synapse's own CLI calls and edits
  under `.claude-work/` do not count. It never blocks. Set `[nudge] calls`
  in `config.toml` to change the first point; `0` turns it off. Counters
  live in `<home>/state/`, and SessionStart prunes any idle over a day.
- **Why.** 2.5.0's rule, as text alone, measured 0 of 2 dispatches in
  `evals/loop-goes-to-implementer`, twice. The emission contract only held
  once a Stop hook enforced it; the dispatch rule gets the same treatment.
- **Doctor lists other PostToolUse hooks** (every settings layer and other
  enabled plugins) as info rows, and INSTALL.md's preflight table has a
  matching row. Another PostToolUse hook conflicts only if it blocks or
  adds its own context on the same calls.
- **Latency:** about 44 ms per matched call on macOS (bash, `lib/py.sh`,
  and Python startup; the counter itself is two syscalls). Windows is not
  measured.
- **Measured** (Sonnet, 2 runs per arm, $3.00 of evals in all). On the
  new `evals/long-loop-goes-to-implementer` (ten serial rounds, seven of
  them visible only at run time), with the hook off the main session ran
  the loop itself in 19 and 17 hands-on calls. With it on, both runs
  dispatched `synapse:implementer` right after the fifth call and made 6
  in all; `suite-passes` 2 of 2 in both arms. On the boundary case
  `evals/loop-goes-to-implementer` (5-8 calls to finish), 1 of 4 runs
  dispatched, against 0 of 4 on 2.5.0; `suite-passes` 4 of 4. Five short-task cases (`answer-first`,
  `scope-discipline`, `implement-with-validation`, `delegate-and-verify`,
  `verify-before-done`, once each, $0.63) all pass, and none reached five
  hands-on calls, so the nudge never fired on them.

### Changed

- **Evals.** `loop-goes-to-implementer`'s `few-main-session-calls` grader
  passes a dispatch that follows the nudge (at most six hands-on calls
  before it, two after). A new `guard` case, `long-loop-goes-to-implementer`,
  has ten serial fix rounds, seven of them visible only at run time.
- `instructions/core.md` says Synapse's hook reminds at five calls.

## 2.5.0 — 2026-11-06 — The main session conducts, roles work

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.
The sweep behind this release is in `docs/design/cost-sweep.md`.

### Changed

- **The main session conducts and roles work.** `instructions/core.md` has
  a rewritten Execution section: a step that needs more than about five
  tool calls or three files goes to a `synapse:` role, a step kept in the
  main session that passes five calls stops and briefs the rest, and a
  failing loop (fix, run, fix again) goes to `synapse:implementer` instead
  of growing the main context. A report is verified by running its
  validation command once, not by re-reading its diff. A fact or decision
  the user states is written to PLAN.md (created if missing) before the
  next step. The Obsidian section is one sentence. The core rules shrink
  from 8,795 to 8,288 characters.
- **The implementer finishes loops.** It stops at the brief's attempt limit
  (two when the brief gives none), and a run that fails on a new error
  after a fix counts as progress, not a failed attempt.
- **A role per step.** The `EXECUTION.md` template has a role for each
  step; `/synapse:plan-session` step 7 writes a brief, dispatches the step
  to its role, and verifies the report; `/synapse:end-session` fills the
  NOTES sections `## User-stated facts`, `## Patterns surfaced`, and
  `## Decision rationale` from `PLAN.md` and the conversation.
- **Extraction runs in a fresh context.** A sixth role,
  `synapse:extractor` (Sonnet), does the work of `/synapse:extract-session`,
  dispatched by that skill, reading the archive from disk (NOTES carries
  what the conversation held). Note specs go to the project's
  `.claude-work/.tmp/extract-SESSION_ID/`, removed after the write or a
  "no". The skill shrinks from 19,064 to 3,986 characters.
- **Every candidate is checked against prior notes** (#10). Extraction
  recalls each Decision, Fact, and Pattern candidate on its concept, not its
  title, and proposes `supersedes` or a duplicate for a prior note scoring
  0.70 or more. It is one batched call, `synapse extract check-candidates`
  (local scope, so `synapse extract supersede` can mark the hit; hits from
  the session being extracted are skipped; below 0.70 nothing is shown).
  Hits are ranked by score and carry `project`; a prior note from another
  project is never proposed as superseded.

### Added

- **PreCompact guidance, for when a session compacts.** `synapse
  compact-guide --hook` prints about 1,000 characters telling the
  compaction summary what to keep (objective, active step, decisions,
  user-stated facts, open questions, work state, planning file paths) and
  what to drop. It defers to `/compact` text or a CLAUDE.md Compact
  instructions section, never blocks compaction, and needs no venv, DB, or
  Ollama. It saves nothing by itself: on a 1M-window model auto-compaction
  triggers near 967k, so the README's "Long sessions" section recommends a
  window of about 300k (`/autocompact 300k`, `autoCompactWindow`, or
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW`). Synapse never changes it;
  `/synapse:doctor` reports it and warns about other PreCompact hooks, and
  INSTALL.md has preflight rows for both.
- Dev tooling: `tools/context-cost.py` (context, cache, and cost per
  session from local transcripts; numbers only), and the eval case
  `loop-goes-to-implementer`.
- Design docs: `docs/design/cost-sweep.md` and
  `docs/design/continuation-assist.md`.

### Calibration

The 0.70 threshold (the recall-hint default) was checked with
`synapse recall-check` and top-3 `synapse recall` over the hybrid ranking
on the author's store
(68 Decision notes, 2 projects; no Fact notes yet): 30 concept queries
whose prior Decision exists (22 naming the topic only, 8 naming the choice
the old note rejected) and 16 concepts with no prior Decision, half of them
close to the store's projects. These numbers were measured with top-3
recall during development; `check-candidates` looks at up to 50 chunks per
candidate, keeps one per note, and ranks by score, so it sees more
candidates. They are indicative for it, not re-measured.

| Threshold | Prior Decision shown | Unrelated concept shown a hit |
|-----------|----------------------|-------------------------------|
| 0.65 | 29/30 | 4/16 |
| 0.675 | 27/30 | 0/16 |
| **0.70** | **26/30** | **0/16** |
| 0.75 | 19/30 | 0/16 |

Unrelated concepts scored 0.54 to 0.66, prior Decisions 0.67 to 0.83
(median 0.77); top-3 retrieval found the prior Decision for 29 of 30. 0.70
stays: 0.675 adds one case with a 0.02 margin over the top unrelated score.
One positive's top hit at 0.70 was a different concept, so the step asks
the agent to read the snippet, not to trust the score alone. The check
would have caught a duplicate pair the store already holds: a concept query
for one note returns the other at 0.73 to 0.80.

## 2.4.0 — 2026-11-06 — Fact notes; create-note stays inside the vault

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.

### Added

- **Fact notes** (#7). A fourth kind of note beside Sessions, Decisions,
  and Patterns: what the user stated or confirmed about a project's
  real-world context that the code does not show (one customer despite
  multi-tenant code, a deploy target, a contract limit).
  `/synapse:extract-session` proposes them with Decisions and Patterns
  (stated or confirmed by the user, absent from the code, changes what an
  agent does) and writes them to the vault's `Facts/`.
- **Facts at session start.** A SessionStart hook lists the current
  project's active Facts, one line each (at most 20 lines and 8,000
  characters), on startup, `/clear`, and compaction. Teammates' Facts are
  listed apart and weighed like shared hits. It reads the DB only (no
  Ollama) and marks the listed notes as shown so recall hints don't repeat
  them. `synapse facts` prints the list; `[recall] facts = false` turns it
  off.
- Facts work everywhere notes do: `synapse recall --type fact`,
  `synapse extract supersede ... --folder Facts`, and `/synapse:share`
  (team folders gain `Facts/`).

### Fixed

- **A note written into the working directory** (#8). `synapse vault`
  now uses the store's configured `vault_path` first and asks the Obsidian
  CLI only when it is unset; an empty, relative, or missing path from the
  CLI is an error, and `create-note` refuses any target outside the vault.
  `synapse vault verify` prints the vault path and fails when `vault_path`
  is not the folder of the vault Obsidian has open; `/synapse:doctor` warns
  on the same mismatch and reports a `vault_path` that is relative or
  missing.

### Changed

- **`vault_path` now decides where notes are written**, not only where
  recall points. Set it to Obsidian's folder for the vault (doctor shows
  it); `SYNAPSE_VAULT` naming another vault ignores it.
- **A git worktree belongs to its repository's project.** Sessions in a
  linked worktree (such as the Claude desktop app's) now archive under the
  repository's folder name, not the worktree's, so Facts and pending
  reminders follow the project. Archives made in worktrees before 2.4.0
  stay under the worktree's name.
- `synapse extract supersede` finds the old note's folder (Decisions or
  Facts) when `--folder` is not given, and `--folder` accepts only vault
  folders.

## 2.3.2 — 2026-11-02 — Extraction on Windows without extra turns

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.

### Fixed

- **Obsidian starts itself on Windows** (#2). `synapse vault` launches a
  closed Obsidian detached with the store's vault
  (`explorer.exe obsidian://open?vault=…`) and waits, as it already did on
  macOS. `/synapse:extract-session` runs `synapse vault verify` first and no
  longer asks the user to start Obsidian.
- **Embedding several notes from Git Bash** (#3). `synapse extract
  embed-note` takes several notes in one call and accepts vault-relative
  paths (`Patterns/<title>.md`); `create-note` prints `path` with forward
  slashes. The skill embeds all new notes in one call, with no shell loop.
- **Backslashes in a note body** (#4). New `synapse vault create-note
  --from-md`: fields in front matter, body as plain Markdown, nothing to
  escape. The extract skill writes notes this way. `--from-file` (JSON)
  still works, and its `Invalid \escape` error now says how to fix it.
- **`synapse recall --limit`** (#5). `--limit N` and `-n N` work as
  aliases of `--top-k N`. Usage and errors of every subcommand name
  `synapse <command>`, not `cli.py`.
- **`&lt;numbers&gt;` in PowerShell** (#1). The extract prompt uses real
  examples instead of angle-bracket placeholders, and the Stop hook asks for
  a rewrite when a final message has one in prose (`angle-placeholder`).

## 2.3.1 — 2026-10-30 — Run the project's documented checks

No store schema change; update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.

### Changed

- **Core rules:** before calling a change done, run the project's own
  documented checks (CONTRIBUTING, README, `Makefile` or task-runner
  targets, CI config), not only the default test runner, and say which
  ran; if one cannot run, say so instead of calling the change done.

### Measured

- On the hard `hidden-second-suite` case (8 runs each), Synapse's score
  rose from 0.28 to 0.50 (no plugin: 0.44): `make check` run after the fix
  0/8 -> 2/8, truthful report 0/8 -> 4/8.
- No regression on the full bench (18 cases, both arms): the 15 earlier
  cases score as before; 0.94 with Synapse vs 0.61 without.

## Repository, after 2.3.0 — V2 slice A: eval bench

The plugin is unchanged (no runtime file), so the version stays 2.3.0.

- **`tools/run-bench.sh --yes`** runs every eval case with Synapse and
  without it (the no-plugin baseline), building the fixture homes it needs;
  about $6, capped at $13.50, reports local.
- **`tools/eval-report.py`**: with vs without per case and per grader, or
  `--compare OLD NEW`. It scores only graders that count in both arms,
  leaves errored and cost-skipped runs out (and says so), and pairs cases
  for the mean.
- **Two core-loop cases** (`verify-before-done`, `answer-first`); the
  release-gate case now relies on memory alone; `reviewer-minimum` gains a
  scored `finds-bug` grader.
- **Measured on 2.3.0:** 1.00 with Synapse vs 0.71 without, over 15 cases.
  The gain comes from memory (four cases, 0 to 1) and the general-purpose
  brief rule; the other ten cases tie.
- **Hard cases** (`hard` tag, in the bench; `tools/build_eval_home.py
  --hard`): compound-archived-lesson, superseded-decision,
  hidden-second-suite. 0.67 with Synapse vs 0.17 without; the
  hidden-second-suite case shows Synapse's agent skipping a project's
  documented `make check`. Two fair but easy cases are tagged `guard`.

## 2.3.0 — 2026-10-26 — V2 slice E: shared memory for a small team

No store schema change. Update with `claude plugin marketplace update
synapse` and `claude plugin update synapse@synapse`, then start new sessions.
Teams are opt-in: nothing changes until `synapse shared init` or `join`.

### Added

- **Teams.** A team shares Decisions and Patterns (never session archives)
  through a folder that reaches every member by **git** (any remote, even a
  bare repo on a NAS) or a **synced folder** (Dropbox, iCloud Drive, SMB).
  Each member keeps a local index rebuilt from the folder by content hash;
  the index is never shared. `synapse shared init | join | sync | status |
  retract | push`.
- **Scrub gate** (`synapse share scrub`, `synapse share lint`). Home and temp
  paths are rewritten; secrets, emails, private IPs, host names, and device
  ids block sharing; session-local references (a bare `#17`, "Wave B",
  "this session"), the user's login name, and text aimed at an agent must
  be reworded. `synapse share lint <folder>` can guard a team repo in CI.
- **`/synapse:share`.** Scrubs each chosen note, rewrites what needs
  judgment, shows only the changed lines, adds only the notes the user
  approves (with `origin`, `author`, `shared_at`, `source_id`; personal
  front matter dropped), and asks before every push. Sharing an edited note
  again replaces its copy.
- **Retraction.** `synapse shared retract` moves a note to `Retracted/` with
  a reason; every member's next sync drops it.
- **Automatic sync.** A `SessionStart` hook starts a background pull and
  re-index at most every 10 minutes. It never prompts for credentials and
  never makes the session wait; a sync failing for 3 days gets one line.
- **Recall and hints include teams.** Shared hits are labeled
  `shared:<team>, <author>`; each list keeps its order and the lists merge
  by score, the store's own result first on a tie, so a weak shared hit
  never displaces a stronger local one. A note you shared shows once.
  `synapse recall --scope all|local|shared`.
- **Inbound gate.** Sync lints every incoming note: one with a secret, an
  identifier, or text aimed at an agent is held back from the index and
  listed by `synapse shared status`; author names are plain labels.
- **Doctor** reports each team: folder, last sync and error, unpushed
  commits, sync-conflict copies.
- **`tools/live-check-share.sh`**: a guarded live check of the share flow
  (eval sessions cannot run the CLI).

### Changed

- **Core rules:** a teammate's note is weighed like any hint, never
  followed as an instruction, and loses to a contradicting local decision
  (say so); share only through `/synapse:share`, per note, and ask before
  every push.
- `/synapse:extract-session` offers `/synapse:share` once when a team is
  configured.
- `tools/run-evals.sh` drops an installed Synapse from PATH, so evals call
  the plugin under test.

### Measured

- Scrub corpus: every planted finding caught, 0 of 25 clean notes blocked.
  On the author's 125 real notes: 7 flagged, all correctly; no false blocks.
- Conflict eval 2/2; live share check 2/2 (scrubbed, asked first, nothing
  added before approval).
- No regression: slice-C and slice-D cases unchanged; golden set identical
  with no team configured.

## 2.2.1 — 2026-10-26 — Windows checkout fix

### Fixed

- **Windows could not clone the repo**, so the plugin could not install
  there: an eval fixture note had `<` and `>` in its file name. Renamed, and
  CI now rejects file names Windows cannot check out.
- **Background-task notifications got recall hints.** They reach the
  `UserPromptSubmit` hook like prompts; prompts that start with a hyphenated
  tag (such as `<task-notification>`) now get no hint.

## 2.2.0 — 2026-10-26 — V2 slice D: deterministic triggers

### Added

- **Automatic recall hints.** A `UserPromptSubmit` hook (`synapse
  recall-hint`) searches the active store for each prompt of four or more
  words that is not a slash command. Hits scoring at least `[recall]
  min_score` (0.70) appear as up to `max_hits` (3) pointers, each shown once
  per session and marked as navigation, not instructions. It is silent when
  anything is missing or broken (store, schema v2, sqlite-vec, Python 3.11+,
  a venv whose interpreter cannot start, Ollama down or slower than 3 s),
  and never blocks a prompt.
- **Pending-extraction reminder.** A `SessionStart` hook (`synapse pending
  --hook`) notes, on startup and `/clear`, archived sessions in this project
  that were never extracted; the session mentions it once and offers
  `/synapse:extract-session`. `synapse pending` lists them by hand.
- **Config switches:** `[recall] auto`, `min_score`, `max_hits`, and
  `[extract] remind` in `config.toml`. A wrong type (for example `auto =
  "false"`) is an error, never a guess. Doctor reports the switches, the
  pending count, config errors, and a home taken from `EVAL_SYNAPSE_HOME`.
- **`tools/run-evals.sh`:** the only documented way to run the eval suite.
  It refuses to start without `--yes`, keeps reports local, and caps cost.
- **Four `slice-d` eval cases** with a synthetic fixture memory
  (`evals/fixtures/memory/`, built by `tools/build_eval_home.py`).

### Changed

- **Core rules:** how to treat an automatic hint (check the source, never
  present a hint as a decision) and the reminder (mention once; never
  extract without the user's go-ahead).
- **`EVAL_SYNAPSE_HOME`** selects the Synapse home when `SYNAPSE_HOME` is
  unset. It exists for eval runs, which pass only `EVAL_*` variables.
- **AGENTS.md:** "run the tests" means unit tests; evals run only when the
  user asks, through the wrapper.

### Measured

- **Threshold** (author's store, 24 unrelated prompts, 17 eligible golden
  queries): at 0.70, 0 of 24 unrelated prompts get a hint, 16 of 17 golden
  queries do, and 15 of 17 hints contain the expected source. Warm hook
  latency: p50 0.18 s, worst 0.19 s.
- **Agent evals** (Sonnet, 2 runs per case): outcome graders 12/12 with
  triggers on, 6/12 off. A convention that lives only in memory was applied
  4/4 on vs 0/4 off; the un-extracted archive was mentioned 2/2 vs 0/2; the
  unrelated task stayed on task in both arms.
- **No regression:** the eight slice-C cases match 2.1 grader for grader.

## 2.1.0 — 2026-10-26 — V2 slice C: role agents

### Added

- **Five role agents**, dispatched as `subagent_type: synapse:<role>`:
  `implementer` (Sonnet; everything but nested agents), `verifier` (Sonnet;
  read + Bash, never edits), `researcher` (Sonnet; read + search + web,
  cites every fact), `reviewer` (inherits the session's model; adversarial,
  never edits), and `scout` (Haiku; exhaustive mechanical sweeps). Each
  body carries the rules its job needs, because sub-agents do not receive
  Synapse's `SessionStart` rules (verified live).
- **Reviewer minimum, suggested:** below the frontier tier, the session
  offers to run reviews on Opus or Fable once per session; a reviewer on a
  small model says so first and recommends a re-run.
- **`evals/`**: an 8-case `claude plugin eval` suite (outcome, discipline,
  and role-dispatch graders) for role agents.
- **Doctor** warns when `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` overrides every
  role's model.

### Changed

- **Core rules:** the waves section names the role agents, says sub-agents do
  not see these rules, and requires a `general-purpose` brief to carry the
  rules it needs. Model-tier prose shrinks to "the agents carry their models".

### Measured (2.0.0 vs 2.1.0, final suite, 8 cases × 2 runs, Sonnet sessions)

- Intended role dispatched: 2/16 -> **16/16**. Files left alone where they
  should be: 12/12 -> 12/12. Outcome graders: 22/24 -> **23/24**; 2.1 matches
  or beats 2.0 on every outcome grader.
- On a Haiku session, the offer of a frontier reviewer appeared in 6 of 7
  runs (2.0: 0 of 4), and the reviewer flagged its own small model in 2 of 3.
- Cost per suite: $1.61 (2.0) and $1.63 (2.1), effectively equal.

## 2.0.0 — 2026-10-26 — V2 slice 1: retrieval quality

Store schema v2: older plugin versions cannot use an upgraded store, so
update every machine that shares one, then run `synapse setup` once.

### Added

- **Hybrid recall.** Every query runs a vector search and an FTS5 keyword
  search, merged by reciprocal rank fusion. Exact names (`QuickAddTracker`,
  `#127`, file names) now surface. Each hit is labeled `vector`, `keyword`, or
  `both`; `--mode vector|keyword|hybrid` picks one search.
- **Supersession.** `synapse extract supersede <old> --by <new>` marks a
  replaced Decision in the DB and in its front matter; recall hides it unless
  `--include-superseded` is passed. `/synapse:extract-session` runs it for
  every Decision written with `supersedes`. Re-embedding keeps the status. It
  edits front matter through the store's `vault_path` and never calls the
  Obsidian CLI.
- **`synapse recall-check <golden.toml>`** scores recall against a golden set
  (hit rate and MRR, overall and per kind), so retrieval changes are measured
  without agent runs.
- **Store schema v2:** filter metadata inside the vector index, an FTS5 index,
  status and `superseded_by` columns, and `origin`/`author` reserved for
  shared stores.

### Changed

- **Filters are exact and run inside the search**, replacing v1.6.1's widening
  loop (kept only for `--since`). `--project` ignores case.
- **`synapse setup` upgrades an older store in place** (`synapse extract
  upgrade`): it backs up `vectors.db` first, rebuilds the indexes from the
  stored vectors without re-embedding, and verifies every vector is unchanged.
  Other commands stop on an old schema and say to run it.

## 1.6.1 — 2026-10-26

### Fixed

- **Filtered recall came back empty.** `--type` and `--project` filters ran
  after a fixed 20-neighbour search, so in a large store a `--type decision`
  query could return nothing while hundreds of decisions existed. The search
  now widens (×8 per round, up to sqlite-vec's 4,096 limit or the whole DB)
  until enough rows pass the filters. Unfiltered queries are unchanged.
- **Doctor kept suggesting a migration that was already done.** It now checks
  an old archive's sessions against the store and reports a fully migrated
  copy as `ok` (a backup), or how many sessions are still missing.
- **Windows CI.** The SessionStart tests called `bash`, which on GitHub's
  Windows runners resolves to the WSL launcher; they now use Git Bash, as
  Claude Code does.
- INSTALL.md's upgrade notes again cover session hooks for project commands
  that V1's `plan-session` ran, and how to retire V1 files restorably.

## 1.6.0 — 2026-10-26

Packages Synapse as a Claude Code plugin with a global knowledge base. No new
memory or retrieval capabilities; locations and installation change.

### Changed

- **Synapse is a plugin.** The repo is its own marketplace; install with
  `claude plugin install synapse --marketplace spencerneutron/Synapse` at user
  scope, and it applies in every project. Skills are namespaced
  (`/synapse:recall`), so they never collide with a user's own skills.
- **Rules load from a `SessionStart` hook** (`instructions/core.md`, 7,074
  characters, under the 10,000 cap) instead of a workspace `AGENTS.md`, so a
  project's own `CLAUDE.md` no longer hides them. The platform profile is
  picked by OS automatically. Where a project's rules conflict, Synapse defers
  to the project's.
- **One global store in `~/.claude/synapse/`** (archive, `vectors.db`, vault,
  plus the venv), resolved from any folder. V1 depended on the working
  directory and on files sitting next to the kb scripts.
- **Optional per-project stores:** a `.synapse.toml` with `store = "<name>"`
  splits a project's archive, vector DB, and vault together. `SYNAPSE_STORE`
  overrides it for a session.
- **Portable paths in the DB:** chunks record `archive/<project>/…` and
  `vault/<Folder>/…` instead of machine paths.
- **Python 3.11+** (config uses `tomllib`), found by `lib/py.sh`, which
  handles the Windows Store stub and Git Bash paths. The Stop hook no longer
  hard-codes `python3`.

### Added

- `synapse` CLI on the Bash PATH: `where`, `setup`, `doctor`, `archive`,
  `recall`, `extract`, `vault`, `backfill`, `migrate`, `version`.
- `/synapse:setup` (idempotent provisioning) and `/synapse:doctor` (read-only
  health and conflict report covering same-named skills, competing rules,
  other Stop hooks, output styles, disabled hooks, old installs, unignored
  working files).
- `synapse migrate --from <dir>`: copies a V1/v1.5 workspace's archive and
  vectors into the store without re-embedding; idempotent; never writes to
  the source.
- INSTALL.md as an agent-followable runbook (read-only preflight, consent
  points, expected outputs); AGENTS.md is now the guide for working on this
  repo.
- Unit tests, `tools/build_context.py`, and a CI workflow (tests on macOS,
  Linux, and Windows; cap check; personal-path scan; plugin validation).

### Removed

- The workspace-copy install (`docs/setup.md`, `templates/settings.json`,
  `platform/`, `kb/`).

## 1.5 — 2026-10-26

Consolidates V1 into one portable repo. No new memory or retrieval features.

### Changed

- **`AGENTS.md` is the only instruction file.** Claude Code reads it natively
  (2.1.277+), so `CLAUDE.md` is gone. V1's `CLAUDE.md` imported `AGENTS.md`
  and then repeated most of it; the two are now one deduplicated file.
- **OS-neutral core.** Shell conventions moved out of the instructions into
  `platform/macos.md` and `platform/windows.md`, installed as
  `.claude/rules/platform.md`. V1 mandated PowerShell while its memory skills
  said macOS and that the PowerShell rules did not apply.
- **One home for planning files:** `.claude-work/current/`. V1 gave three
  different answers.
- **`/plan-session` is project-neutral.** The hard-wired roadmap sync became
  a generic `## Session hooks` section that any project's `PLAN.md` can list.
- **`recall` and `extract-session` skills** defer to the platform profile
  instead of assuming macOS.
- **Vault name is configurable** with `SYNAPSE_VAULT` (default `Synapse`).
- The Agent tool replaces the old "Task tool" name; example project names in
  `backfill.py` are generic.

### Added

- **Waves and model right-sizing** in `AGENTS.md`: implementation,
  verification, research, and adversarial-review waves, one writer per file
  set, and model tiers per wave. Rebuilt from the V1 design notes. This
  reverses V1's rule that sub-agents never write to the workspace:
  implementation waves now write, one agent per set of files.
- **`emission-contract` skill** (late-bound directive plus exemplars) and the
  **`emission_check.py` Stop hook** with a pattern file. Rebuilt from the V1
  design notes; the originals were not available.
- `AGENTS.md` lifecycle table and a pointer to `/workflow-recovery` for
  interrupted multi-agent runs.
- `templates/` (PLAN, EXECUTION, NOTES, Stop-hook settings), `docs/setup.md`,
  `docs/architecture.md`, `kb/requirements.txt`, and `examples/`.

### Fixed

- `backfill.py` started `extract.py` with a hard-coded `python`, which does
  not exist on stock macOS; it now uses the running interpreter.
- `/recall` no longer offers `--type session` (Session notes are never
  embedded); `vault_write.py`'s docstring shows `note-exists <folder> <name>`.

### Removed

- Project-specific skills (`deploy`, `roadmap-sync`, `device-log-triage`).
  They belong to a single app, not the harness.

## 1.0 — 2026 (unreleased)

The harness as it ran day to day:

- `CLAUDE.md` + `AGENTS.md` instructions.
- Session skills: `/plan-session`, `/end-session`.
- Memory skills: `/recall`, `/extract-session`, backed by `extract.py`,
  `recall.py`, `vault_write.py`, and `backfill.py`.
- `workflow-recovery` and `language-sweep`.
- An emission contract with a Stop hook, and the multi-agent wave rules.
