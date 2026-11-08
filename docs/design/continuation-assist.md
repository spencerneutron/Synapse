# Continuation assist (design for issue #11)

Status: **proposal, for review.** No code. Written 2026-11-06. Every hook
behavior below was checked that day against the Claude Code docs (Claude
Code 2.1.314 installed); each claim links to its source.

## Status (2.6.0)

Shipped in 2.6.0 (see CHANGELOG.md). It differs from the phases below by
the maintainer's decisions of 2026-11-06:

- No `CHECKPOINTS.md`. A checkpoint writes `## Resume` in `EXECUTION.md` and
  appends to the working `NOTES.md`; `/synapse:end-session` starts from that
  file.
- Checkpoint and continue: `/synapse:checkpoint` does not end the turn.
- The context nudge uses the PostToolUse channel (the existing nudge hook),
  at 60% and 90% of `[nudge] context_window`.
- 2.7.0: gates. The nudge line proved advisory, so a PreToolUse gate now
  denies a hands-on call once per threshold above `[gate] min_context`, and
  the Stop hook asks once for a checkpoint at 60% and 90% when `## Resume` is
  stale. Below `min_context` the nudge line still runs.
- 2.7.0: the tail end. A SessionEnd hook archives `.claude-work/current/`
  at exit, `/clear` and a `/resume` switch; extraction writes its notes by
  default (`[extract] accept = auto`) and `synapse extract review` lists
  them; `/synapse:end-session` runs extraction last.
- 2.7.1: the window is Claude Code's auto-compact point when a per-model
  `autoCompactWindow` is set: the setting less the 33k compaction buffer
  (`lib/synapse/autocompact.py`), so 300k compacts near 267k and the marks
  land at 134k, 160k and 240k. The rest of this document is the 2026-11-06
  design record and keeps its figures.
- Pointers only. The resume pointer names the Resume section; nothing is
  inlined.
- The resume-time line (cache expired on a large context) is on
  UserPromptSubmit in the same hook process.

Compaction retention, measured with `tools/live-check-compact.sh` (one run,
Sonnet, $0.52, 2026-11-06): auto compaction went from 76,614 to 21,121
tokens, and all 7 planted words (a fact, a decision with its rationale, an
open question, stated only in conversation) were recalled. The planted turn
was not kept word for word, so the 5,037-character summary carried them.
Hook stdout is not in transcripts, so this does not show the PreCompact
hook's effect.

The phases below are the original proposal and are not rewritten.

Issue: [spencerneutron/Synapse#11](https://github.com/spencerneutron/Synapse/issues/11).

---

## Problem

Issue #11 records two parallel Opus sessions that used up the plan
allowance. Their transcripts show:

- Main contexts grew to 605k and 431k tokens (366k and 261k average per
  request, 317 and 187 main requests). Neither session compacted or
  restarted.
- Main-session cache reads were 114.4M and 47.6M tokens (90.6% and 74.6% of
  cache reads); the main session was 85.6% and 66.5% of each session's
  cost, B's six workflow agents included (#11 comment, 2026-11-06 21:38
  UTC). The main session re-reading its context is 66 to 96 percent of
  cost in the six sessions
  on two machines that used sub-agents (A to D here; this Mac's three
  largest sessions, measured 2026-11-06, at 94.8% and 88.5%), and 100
  percent in one that used none.
- The main session did the hands-on loops itself (Session A: 197 Bash,
  43 Edit, 42 PowerShell calls). Every call re-reads the whole context.
- One autonomous turn ran for 78 minutes. The issue said it read about
  100M cache tokens; that figure was not re-measured and probably carries
  the overcount below.

Source for the corrected figures: the maintainer's re-measurement in the
comments on #11 (2026-11-06, 21:28 UTC; it supersedes the 21:26 comment).
The issue body counted transcript lines, and Claude Code repeats one
response's usage on 2 to 3 lines, so its absolute figures (757 and 452
requests, 275M and 114M cache reads) were overstated about 2.4 times. The
sessions' shape and the main finding hold. Two more sessions from the same
project (C: 479 requests, mean 287k, 91.0% of cost; D: 297 requests, mean
226k, 95.6%) each auto-compacted once, at 385k and 307k.

The maintainer rejected ending sessions early. The direction is a
**continuation assist**: shrink the context while the work continues,
without losing knowledge, and feed what it saves into the real
`/synapse:end-session` at the true end.

### Why the sessions never shrank

Opus 4.7 and later run with a native 1M window and auto-compact "at about
967K tokens by default"
([model-config: default auto-compact thresholds](https://code.claude.com/docs/en/model-config#default-auto-compact-thresholds)).
Sessions at 605k and 431k are far from that point. The threshold is not
fixed near 968k in practice: auto-compactions on the maintainer's machines
ran at 307k, 385k, 393k, 461k, 854k and 968k. So a hook that acts only at
compaction has real occasions to run, but it cannot be relied on for
sessions like #11's unless the context shrinks earlier: the user runs `/compact` or `/clear`, or lowers the
auto-compact window with `/autocompact`, `autoCompactWindow`, or
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`
([model-config: set the auto-compact window](https://code.claude.com/docs/en/model-config#set-the-auto-compact-window)).
Every phase below is designed around that fact.

### What is lost today when the context shrinks

- **`/compact`** replaces the history with a model-written summary.
  Context that hooks added earlier is "summarized with the rest of the
  conversation"
  ([context-window: what survives compaction](https://code.claude.com/docs/en/context-window#what-survives-compaction)).
  The default summary decides alone what to keep.
- **`/clear`** starts "a new conversation with empty context"
  ([commands](https://code.claude.com/docs/en/commands#all-commands)).
  Only files on disk and SessionStart hook output survive.
- **`/synapse:extract-session`** proposes Decision, Pattern, and Fact notes
  "at teardown, while context is fresh" ([architecture](../architecture.md)).
  Fact notes need what "the user stated or confirmed"
  (`skills/extract-session/SKILL.md`, step 5). A user statement, or a
  decision's rationale, that was said in conversation but never written to
  `PLAN.md` is gone after `/clear`. After `/compact` it survives only if
  the summary kept it.

### Cost arithmetic

Weights as in #11: cache read 0.1x, cache write 1.25x, output 5x of base
input. A main request at context C costs about 0.1·C base-equivalent
tokens. Session A: 317 requests × 366k average = 116M cache reads, which
matches the measured 114.4M. **Main-session cost scales with the average context per
request**, so halving that average roughly halves the dominant cost.

Shrinking has its own price:

| Action | One-time cost at C = 400k | Source |
|--------|---------------------------|--------|
| `/compact` | One request that reads the whole conversation (about 40k if cached, 400k if the cache expired), plus the summary as output (5x), plus a cache write for the new, shorter history | "`/compact` reads the conversation it summarizes, so compacting a large context is itself a large request" ([costs: why usage climbs](https://code.claude.com/docs/en/costs#why-usage-climbs-in-a-long-session)); compaction invalidates the conversation cache layer by design ([prompt-caching: compacting](https://code.claude.com/docs/en/prompt-caching#compacting-the-conversation)) |
| `/clear` | Nothing | "`/clear` costs nothing" (same costs section) |
| Checkpoint, then `/clear` (Phase 3) | About 4 requests at C to write two files (about 160k), about 3k output tokens (15k), then re-orientation after the clear (a few small requests) | Estimate |

Break-even for checkpoint + `/clear`, at C = 400k and a restart context of
60k (#11's sessions started at 58–59k): each later request saves about
0.1 × 340k = 34k, so the checkpoint pays for itself after about 6 requests.
Session A made 317.

Two cache effects make this larger:

- **Overage drops the TTL to five minutes.** On usage credits, "Claude Code
  drops the main conversation to the five-minute TTL"
  ([prompt-caching: which TTL](https://code.claude.com/docs/en/prompt-caching#which-ttl-each-request-gets)).
  #11's sessions were in overage and soft-paused for 70 and 159 minutes.
  The first request after such a pause rewrites the whole context:
  605k × 1.25 ≈ 756k base-equivalent, as much as 12 cached requests at
  that size. A
  checkpoint and `/clear` before a pause avoids it. The built-in `/usage`
  already suggests "Compact before you step away"
  ([costs: /usage recommendations](https://code.claude.com/docs/en/costs#apply-recommendations-with-the-fix-shortcut)).
- **The one-hour TTL writes at a higher rate.** On a subscription within
  plan usage, the main conversation uses the one-hour TTL, which "charges a
  higher rate" for
  cache writes (same page). #11 priced writes at 1.25x; "Cache write
  tokens with a 1-hour TTL are 2 times the base input tokens price"
  ([API prompt caching: pricing](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#pricing)).
  The measurement below reports both.

---

## Goals and non-goals

Goals:

1. Let the main context shrink mid-work without losing the objective, the
   active step, decisions with rationale, user-stated facts, or open
   questions.
2. Carry what is saved into `/synapse:end-session` and
   `/synapse:extract-session`.
3. Never block or break a compaction. Every hook fails open.
4. Measure each phase from transcripts, the way #11 was measured.

Non-goals:

- Ending sessions early (rejected by the maintainer).
- Running `/clear` or `/compact` for the user. No hook output can run a
  command or skill (see the platform table), and the shrink is the
  user's call.
- Changing Claude Code's summarizer, or throttling parallel sessions
  (#11 avenue 4).

---

## What the platform allows (verified 2026-11-06)

Source: the [hooks reference](https://code.claude.com/docs/en/hooks)
unless the row says otherwise.

| Mechanism | Verified behavior | Consequence for this design |
|-----------|-------------------|-----------------------------|
| [PreCompact](https://code.claude.com/docs/en/hooks#precompact) matchers | `manual` (`/compact`) and `auto` (auto-compact window, and idle compaction) | One hook covers both; idle compaction also runs it |
| PreCompact input | Common fields (`session_id`, `transcript_path`, `cwd`) plus `trigger` and `custom_instructions`: "For `manual`, `custom_instructions` contains what the user passes into `/compact` … For `auto`, `custom_instructions` is `null`." | The hook can see whether the user gave their own focus |
| PreCompact output | "When a PreCompact hook exits 0 and doesn't block, Claude Code uses its stdout as instructions for the compaction summary. Keep that stdout under 10,000 characters per hook. Claude Code cuts longer output at the cap and appends a marker." | Phase 1's mechanism |
| PreCompact blocking | Exit 2 or JSON `"decision": "block"` blocks. "If compaction was triggered to recover from a context-limit error already returned by the API, the underlying error surfaces and the current request fails." `systemMessage` and `continue` are discarded. | Never exit 2, never print a `decision` |
| Stdout parsing | Stdout counts as JSON only when it is one JSON object; output that "doesn't start with `{`" is plain text ([exit code 0](https://code.claude.com/docs/en/hooks#exit-code-0)) | Phase 1 prints plain text that never starts with `{` |
| Hook failure | "On most events, when a hook fails or times out, Claude Code still carries out the action"; `onFailure` defaults to `"continue"` ([block the action when a hook fails](https://code.claude.com/docs/en/hooks#block-the-action-when-a-hook-fails)) | A crash or timeout lets compaction proceed. PreCompact is not named on its own: test it (Phase 1) |
| [PostCompact](https://code.claude.com/docs/en/hooks#postcompact) | Receives `trigger` and `compact_summary`. "PostCompact hooks have no decision control. They can't affect the compaction result." | Usable only for measurement (log the summary) |
| [SessionStart](https://code.claude.com/docs/en/hooks#sessionstart) sources | `startup`, `resume`, `clear`, `compact`, `fork`; the matcher filters on them | Phase 2 speaks on `compact` and `clear` only |
| SessionStart after compaction | SessionStart hooks matching `compact`: "Claude Code runs them and adds their output to the compacted context" ([context-window](https://code.claude.com/docs/en/context-window#what-survives-compaction)) | The resume pointer lands after the summary |
| SessionStart after `/clear` | Hooks run in the background; "Claude's first response still waits for the hooks to finish"; if the user runs `/clear` again while they run, "nothing they return applies" | Keep the hook fast |
| SessionStart output | `additionalContext` or plain stdout. Each string is capped at 10,000 characters; above that, Claude gets a file path and a 2,000-character preview ([JSON output](https://code.claude.com/docs/en/hooks#json-output)) | Stay far below the cap |
| Context wording | "Write the text as factual statements rather than imperative system instructions" or it can trigger prompt-injection defenses ([add context for Claude](https://code.claude.com/docs/en/hooks#add-context-for-claude)) | Phases 2 and 4 state facts, not orders |
| Token counts in hook input | Only SessionStart on `resume`/`fork` (`context_tokens`, when the transcript has a response) and PreModelSwitch carry one. UserPromptSubmit, Stop, PreCompact, PostCompact do not. | Phase 4 must read the transcript |
| `transcript_path` | "Path to conversation JSON … written asynchronously and may lag the in-memory conversation" ([common input fields](https://code.claude.com/docs/en/hooks#common-input-fields)). Location and JSONL format are documented, the per-line schema is not ([claude-directory: application data](https://code.claude.com/docs/en/claude-directory#application-data)) | Phase 4 and the measurement tool must fail open |
| [SessionEnd](https://code.claude.com/docs/en/hooks#sessionend) | `reason` includes `clear`. No decision control. "SessionEnd hooks have a default timeout of 1.5 seconds", and "Timeouts set on plugin-provided hooks don't raise the budget." | Too short and too late for model work. Not used |
| [UserPromptSubmit](https://code.claude.com/docs/en/hooks#userpromptsubmit) | `additionalContext` is added "alongside the submitted prompt"; can block | Phase 4's channel: no extra request |
| [PostToolBatch](https://code.claude.com/docs/en/hooks#posttoolbatch) | "Runs once after every tool call in a batch has resolved, before Claude Code sends the next request"; `additionalContext` goes "next to the tool result" | Phase 4 alternative that also reaches long autonomous turns |
| [Stop](https://code.claude.com/docs/en/hooks#stop) | `decision: "block"` keeps the turn going; 8-consecutive-continuation cap | A Stop nudge costs one more request at full context. Not used |
| Hook outputs | The [decision control](https://code.claude.com/docs/en/hooks#decision-control) table lists context, block or allow decisions, permission decisions, and side-effect fields only | Hooks cannot run `/clear`, `/compact`, or a skill |
| Status line | `context_window.used_percentage`, `total_input_tokens`, `current_usage`; the script's stdout is displayed ([statusline: context window fields](https://code.claude.com/docs/en/statusline#context-window-fields)) | Display only; the user's setting, not Synapse's |
| Compaction re-injection | CLAUDE.md, skill descriptions, and up to five recently edited files are re-read; invoked skill bodies come back capped at 5,000 tokens each ([context-window](https://code.claude.com/docs/en/context-window#what-survives-compaction)) | A freshly written `EXECUTION.md` is likely re-read after `/compact` |

Synapse's own SessionStart hooks have no matcher (`hooks/hooks.json`), so
the core rules, platform rules, and Facts already return after `compact`
and `clear` (`lib/synapse/facts.py`: `LIST_ON = ("startup", "clear",
"compact")`).

---

## Design overview

```
work ──► /synapse:checkpoint (Phase 3, model judgment)
           ├─ EXECUTION.md  ## Resume         (replaced in place)
           └─ CHECKPOINTS.md ## Checkpoint …  (appended)
         user runs /clear (cheapest) or /compact
           ├─ /compact: PreCompact hook (Phase 1) shapes the summary
           └─ both:     SessionStart compact|clear (Phase 2) adds a resume pointer
work continues … (Phase 4 may suggest the next checkpoint)
/synapse:end-session merges CHECKPOINTS.md into NOTES_<id>.md
/synapse:extract-session promotes its decisions and user-stated facts
```

New working file: `.claude-work/current/CHECKPOINTS.md`, beside
`PLAN.md` and `EXECUTION.md`. It is append-only and holds what has no home
in the planning files: session-level decisions with rationale, user-stated
facts, open questions, deferred items. `EXECUTION.md` gains one section,
`## Resume`, replaced at each checkpoint. Its location goes through
`lib/synapse/paths.py` (a `work_dir()` helper, which `archive.py` would
also use) per AGENTS.md.

Switches live in a new `[continuation]` table in `config.toml`, read by
`paths.settings()`, each phase separately switchable.

---

## Phase 1: PreCompact summary instructions

### What

A PreCompact command hook in `hooks/hooks.json`, no matcher (manual and
auto):

```
SYNAPSE_OPTIONAL=1 bash "${CLAUDE_PLUGIN_ROOT}/lib/py.sh" "${CLAUDE_PLUGIN_ROOT}/lib/synapse/cli.py" compact-guide --hook
```

It reads the hook JSON, checks which planning files exist under `cwd`, and
prints plain text (about 2,000 characters, well under the 10,000 cap):

- **Keep:** the user's objective in their words; the active step and the
  next action; decisions with their rationale and the rejected
  alternatives; facts the user stated or confirmed about the project,
  marked as user-stated; open questions and pending user decisions; the
  state of the work (branch, uncommitted files, last test command and
  result, background jobs still running); the paths of
  `.claude-work/current/PLAN.md`, `EXECUTION.md`, and `CHECKPOINTS.md`
  when they exist, named as the source of truth.
- **Drop:** tool output, logs, file contents that are on disk, search
  results, superseded attempts, diffs already reported.
- **Prefer pointers:** where a planning file holds an item, name the file
  instead of restating it. If `EXECUTION.md`'s `## Resume` section was
  written in the last 30 minutes, say so, so the summary can stay short.
- **Defer to the user:** when `custom_instructions` is not null, the text
  says the user's own instructions take precedence. It does the same for a
  CLAUDE.md "Compact instructions" section, which the docs offer for the
  same purpose ([costs: manage context proactively](https://code.claude.com/docs/en/costs#manage-context-proactively)).

Never-block guarantees: the command never exits 2, never prints JSON or a
`decision`, and catches every error (on error it prints the static part of
the text, or nothing). `SYNAPSE_OPTIONAL=1` makes a missing Python a silent
exit 0. The hook needs no Ollama, venv, or database.

Optional measurement aid: a PostCompact hook, off by default
(`[continuation] log_summaries = false`), that writes `compact_summary`
and the trigger to `<Synapse home>/state/compactions/` so retention can be
graded. It writes only inside the Synapse home.

`/synapse:doctor` gains a check that lists other PreCompact hooks in the
user's settings and plugins (each hook's stdout is capped on its own, so
two sets of instructions can conflict), and INSTALL.md's preflight table
gains a row for it.

### Cost

- Build: small. One CLI subcommand, one `hooks.json` entry, unit tests,
  one doctor check.
- Runtime: no extra requests. About 500 input tokens added to each
  compaction request, which already reads the whole context. The summary
  may grow; the measurement watches that.

### Risk

Low.

- A bug that blocks compaction would fail a request when the compaction
  recovers from a context-limit error. Mitigation: the guarantees above,
  plus tests that feed malformed JSON, a missing `cwd`, and an unreadable
  file and assert exit 0 with plain-text stdout.
- How the hook's stdout combines with the user's `/compact` text and
  CLAUDE.md "Compact instructions" is not documented. The hook text defers
  to both; verify by hand before release.
- PreCompact is not named in the docs' "fails or times out, still carries
  out the action" sentence. Test: a hook that sleeps past its timeout
  during `/compact` must let the compaction finish.
- Alone, it changes nothing for #11's sessions, which never compacted.
  It pays off with Phase 3, with a lower `/autocompact` window, or both.

### Measurement

- **Size:** transcripts mark each compaction with a `system` entry,
  `subtype: "compact_boundary"`, whose `compactMetadata` holds `trigger`,
  `preTokens`, `postTokens`, and `durationMs` (observed locally, not
  documented; for example, one manual compaction went from 945,539 to
  23,257 tokens in 99 s). Compare `postTokens` with and without the hook.
- **Retention:** a fixed conversation that plants an objective, a
  decision with rationale, a user-stated fact, an open question, and the
  planning-file paths, compacted with and without the hook. Grade the
  logged `compact_summary` for each planted item.
- **Done when:** every planted item survives with the hook in at least 4
  of 5 runs and does at least as well as without it; `postTokens` grows
  less than 20%; no compaction is blocked in any test.

---

## Phase 2: SessionStart resume pointer (`compact`, `clear`)

### What

A SessionStart command hook, `synapse resume --hook`, added to the
existing SessionStart group. It speaks only when `source` is `compact` or
`clear` and the project has planning files under `cwd`. It prints
`additionalContext` of at most about 1,500 characters, written as facts:

```
This conversation continues earlier work in this project.
Planning files: .claude-work/current/EXECUTION.md (updated 12 min ago,
has a Resume section), PLAN.md, CHECKPOINTS.md (3 checkpoints, latest
12 min ago). The Resume section, below, holds the active step.
<the ## Resume section of EXECUTION.md, clipped to 1,000 characters>
```

Inlining the short Resume section saves the first read and makes it hard
to skip. Everything else stays a pointer.

- **On `compact`:** speak whenever the files exist. The summary already
  continues the work; the pointer adds the file paths and the fresh Resume
  section.
- **On `clear`:** speak only when `## Resume` or `CHECKPOINTS.md` was
  written within `[continuation] resume_fresh_minutes` (default 120). A
  fresh checkpoint means the user is clearing to continue. An old one
  means they may be switching to unrelated work, where a pointer to the
  old task would mislead.

It sits beside the Facts hook, which already speaks on these sources, and
its text is separate from it (each hook's string is capped on its own).

### Cost

- Build: small. One subcommand, one `hooks.json` entry, unit tests per
  source.
- Runtime: about 400 tokens once per compaction or clear. One fewer
  request after a clear, because the Resume section is already in context.

### Risk

Low.

- A stale pointer after an unrelated `/clear`. Mitigation: the freshness
  gate and factual wording, which leave the model free to ignore it.
- Two sessions in one checkout share `.claude-work/current/`. This is
  already true for `PLAN.md` and `EXECUTION.md`; worktrees, the desktop
  app's default, keep them apart.

### Measurement

- From the first transcript after a clear or compaction: requests until
  the first tool call on the task; whether `EXECUTION.md` is re-read (it
  should not be when the Resume section was inlined); files re-read that
  the summary or the Resume section already covered.
- User corrections in the first five turns ("I already said", "we decided"),
  counted by hand on a sample.
- **Done when:** unit tests cover every source and the freshness gate; the
  hook is silent on `startup`, `resume`, and `fork`, and when no planning
  files exist; output stays under 1,500 characters.

---

## Phase 3: `/synapse:checkpoint` skill

### What

A skill, `skills/checkpoint/SKILL.md`, invoked by the user or offered by
the model (Phase 5). It needs judgment, which hooks cannot supply. It
edits files only and calls no CLI, so evals can test it. Steps:

1. **Replace `## Resume` in `EXECUTION.md`:** the objective in the user's
   words, the active step, the next action, the state of the work (branch,
   uncommitted files, last test command and result), background jobs still
   running, and what not to redo.
2. **Append `## Checkpoint <YYYY-MM-DD HH:MM>` to `CHECKPOINTS.md`**, with
   only what is new since the last checkpoint or already in `PLAN.md`:
   - Decisions: the decision, why, and what was rejected.
   - User-stated facts: in the user's words or a close paraphrase, marked
     user-stated. These are candidates for Fact notes, not Fact notes.
   - Open questions and pending user decisions.
   - Deferred items.
3. Durable decisions also go to `PLAN.md`'s Decision Log, as the core
   rules already require.
4. Confirm both writes, then tell the user the next step: `/clear` when the
   Resume section is complete and the work is between stages (costs
   nothing); `/compact` when much unwritten state is in play, such as a
   debug session midway. Before a long pause, recommend one or the other,
   because of the cache rewrite described above.

Changes to existing skills:

- **`/synapse:end-session`** reads `CHECKPOINTS.md` with `PLAN.md` and
  `EXECUTION.md`, merges its open items into the existing NOTES sections,
  and adds two sections to `NOTES_<id>.md`: "Decisions (from checkpoints)"
  and "User-stated facts (from checkpoints)". It then appends one marker
  line to `CHECKPOINTS.md`, `<!-- merged into NOTES_<id> -->`, so the next
  merge takes only later sections. That marker is the only write to a
  working file, append-only; the archive itself stays copy-only.
- **`/synapse:extract-session`** reads the NOTES "User-stated facts"
  section as Fact candidates. Each still has to pass the four-part test in
  step 5.

### Cost

- Build: small to medium. One skill, edits to two skills, eval cases.
- Runtime: about 4 requests at the current context plus about 3k output
  tokens per checkpoint; break-even about 6 requests after a `/clear` at
  400k (see Cost arithmetic). After `/compact` the checkpoint also costs
  the compaction request.

### Risk

Medium, because it rests on model judgment and on a user step.

- A missed fact before `/clear` is lost for good. Mitigation: the skill
  asks for user-stated facts by name; Phase 1 still guards `/compact`.
- Friction: the user must run `/clear` or `/compact` by hand.
- `CHECKPOINTS.md` grows across a long session. It is append-only and
  merged once; plan-session may move an old one aside when starting a new
  task.
- The core.md change in Phase 5 is what makes the model offer it; without
  it the skill is used only when the user remembers.

### Measurement

- **Cost:** per session, cache reads per main request before and after
  each checkpoint-plus-clear, and the request count to break-even.
- **Knowledge:** eval cases. (a) Capture: a prompt in which the user
  states a fact and makes a decision with a reason, then asks for a
  checkpoint; graders check `CHECKPOINTS.md` for both and `EXECUTION.md`
  for a Resume section. (b) Merge: a fixture with `CHECKPOINTS.md` already
  present; end-session's NOTES must contain its items. Merge needs the
  `synapse archive` CLI, which eval sessions cannot run (AGENTS.md), so it
  runs as a live check like `tools/live-check-share.sh`.
- **Done when:** both cases pass in at least 4 of 5 runs; a hand-run
  session with two checkpoint-plus-clear cycles produces NOTES that list
  every planted decision and fact.

---

## Phase 4 (optional): context-size nudge

### What

Hooks get no token count, so the nudge reads the last API usage from
`transcript_path`: seek to the end of the JSONL file, read about the last
64 KB, take the newest `assistant` entry with `message.usage`, and compute
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens`
(the formula the status line uses for context size). The format is
undocumented, so any parse failure means silence.

When the size crosses a threshold (`[continuation] nudge_at`, for example
250k, then each further 150k), it adds one factual line as
`additionalContext`:

```
Synapse: the main context is about 410k tokens; each tool call re-reads
it. /synapse:checkpoint followed by /clear continues from the planning files.
```

It speaks once per threshold crossing per session (state beside
`paths.hint_state`) and stays quiet when the user has declined in this
session.

Channel options:

| Channel | Extra requests | Reaches a long autonomous turn | Hook runs |
|---------|----------------|-------------------------------|-----------|
| UserPromptSubmit `additionalContext` (preferred start) | None | No: Session A's 78-minute turn had no prompt in it | One per user prompt |
| PostToolBatch `additionalContext` | None | Yes | One per tool batch (hundreds per session; must stay well under 100 ms) |
| Stop `decision: "block"` | One at full context per nudge | Only at turn end | One per stop |

Zero-code alternative, measured first: document `/autocompact <tokens>`
as Synapse's recommended setting (for example 300k), so compaction comes
early and Phase 1 shapes it. Rough illustration only: with a 300k window
and about 40k after each compaction, the context saw-tooths around an
average near 170k instead of Session A's 366k. That cuts cache reads by
about half, minus about two compactions of about 100k each. It costs a
lossy summary each time instead of a deliberate checkpoint. Synapse would
document the setting, not write it: it is the user's setting.

### Cost

- Build: small to medium (transcript tail reader, state, tests against
  real transcript samples with personal data removed).
- Runtime: about 60 tokens per nudge; a process start on every prompt or
  batch.

### Risk

Medium.

- Format drift breaks the nudge silently. Mitigation: fail open, plus a
  doctor check that parses the current session's transcript and reports
  "nudge unavailable".
- The transcript may lag by a turn; acceptable for a nudge.
- Nag fatigue. Mitigation: rising thresholds, one nudge per crossing,
  silence after a decline.
- PostToolBatch adds latency to every tool batch.

### Measurement

- Replay past transcripts offline to see when the nudge would have fired.
- Share of nudges followed by a checkpoint within three requests; context
  size at checkpoint; average context per request with the nudge on and
  off, by config, over comparable work.
- **Done when:** the replay shows at most one nudge per 150k of growth; no
  error reaches the user when the transcript is missing or malformed.

---

## Phase 5: rule changes in `instructions/core.md`

`core.md` holds 8,795 characters of its 9,500 budget (AGENTS.md), so 705
remain. The draft text below adds 510 characters (9,305 in all):

- Sub-agents and Waves, new bullet: "Hand a run-test, read-log, fix loop to
  `synapse:implementer` with the failing command and the done condition;
  read its report, not the logs. Each main-session tool call re-reads the
  whole context."
- Session Lifecycle table, new row: "Checkpoint | `/synapse:checkpoint` |
  Between stages of a multi-stage request, or when Synapse reports a large
  context; the user then runs `/clear` or `/compact`".
- Token / Context Discipline, new bullet: "Between stages of a multi-stage
  request, offer `/synapse:checkpoint` before the next stage when the
  context is large or the next stage is long."

The implementer already stops after two failed validations
(`agents/implementer.md`); a loop brief should give it the failing
command, the done condition, and an attempt limit. After the edit, run
`python3 tools/build_context.py` and keep `core.md` under 9,500.

### Cost

- Build: small.
- Runtime: about 130 always-on tokens, cached, in every request. Each
  delegated loop adds a subagent start-up (its own prompt and the files it
  reads) but moves dozens of calls off the large context.

### Risk

Medium: these change behavior on every session.

- A delegated loop lacks the main context and may fail more often.
  Mitigation: the brief carries the failing command, the done condition,
  and the files.
- Offers at stage boundaries can interrupt a user who asked for one
  unbroken run (Session A's "push, then begin wave 8 … adversarial review").
  The wording offers, it does not stop; see open question 3.

### Measurement

- Main-session tool calls per session by tool (Bash, Edit, PowerShell) and
  the main share of cost, before and after (#11's 85.6% and 66.5%).
- An eval case with a failing test to fix: a grader checks for a
  `synapse:implementer` dispatch (`arm: with-only`) and caps main-session
  Bash calls. Run the `hard` and `guard` tags to check for regressions.

---

## Measuring the effect from transcripts

#11's numbers came from transcript `usage` fields. The same method,
written once as a stdlib dev tool, `tools/context-cost.py TRANSCRIPT...`:

- **Inputs.** The main transcript `projects/<project>/<session>.jsonl` and
  the subagent transcripts in `projects/<project>/<session>/subagents/`
  ("in the same format as the session transcript",
  [claude-directory](https://code.claude.com/docs/en/claude-directory#application-data)).
  The line schema is not documented: skip any line that does not parse.
- **Count each request once.** One response is written as several
  `assistant` entries, one per content block, each repeating the same
  `usage`. In one local transcript, 1,753 entries were 655 responses. Key
  on `message.id`; counting entries would overstate tokens about 2.7x.
- **Per request:** time, model, context size (`input_tokens +
  cache_read_input_tokens + cache_creation_input_tokens`), cache reads,
  cache writes (split by `usage.cache_creation` into one-hour and
  five-minute where present), output tokens.
- **Per session:** request count; mean and 90th-percentile context per
  request; total cache reads; base-equivalent cost (input + 0.1 × cache
  read + 1.25 × cache write + 5 × output, and again with 2 × for one-hour
  writes); main versus subagent share of each.
- **Events:** compactions (`compact_boundary` with `preTokens`,
  `postTokens`); checkpoints (`Skill` tool calls or prompts naming
  `synapse:checkpoint`); clears (a new session file in the same project
  that starts right after the old one ends; pair by time and `cwd`, since
  how a cleared conversation links to its predecessor is not documented).
- **Comparisons:** cache reads per main request before and after each
  shrink event; average context per request per day; main versus subagent
  share. Retention is measured separately (Phase 1 and 3 evals, NOTES
  coverage at end-session) because tokens cannot show lost knowledge.

The tool reads transcripts that hold the user's code and conversation. It
prints only numbers and never writes outside the working directory.

---

## Recommendation: first phase

Start with **Phase 1 and the measurement tool** as one small release:

- It is the change the maintainer described ("runs when the user
  compacts"), and it cannot lose anything that compaction does not lose
  today.
- It is low risk and needs no model judgment, no new working files, and no
  user step.
- The measurement tool sets the baseline that every later phase needs.
  Run it on #11's transcripts first and confirm it reproduces the issue's
  table.
- Pair it with a documented `/autocompact` recommendation (no code), so it
  has an effect on 1M-window sessions like #11's.

Then Phase 3 with Phase 2 (checkpoint, then resume pointer), which is
where the larger saving is: `/clear` costs nothing and resets to about
60k. Phase 5 follows once the skill exists, and Phase 4 last, only if
users do not checkpoint without a prompt.

---

## Open questions for the user

1. **Auto-compact window.** Should Synapse recommend a lower
   `/autocompact` window for 1M-context models, and which value (200k,
   300k, 400k)? A lower window shrinks cost automatically, but each
   compaction is lossy and costs a large request.
2. **Partial notes file.** Is `.claude-work/current/CHECKPOINTS.md` the
   right name and place? Should `synapse archive` also copy it as
   `CHECKPOINTS_<id>.md`, which changes the archive's prefixes and what
   recall embeds, or is merging it into NOTES enough?
3. **Stage boundaries.** Should the rule offer a checkpoint and continue,
   or end the turn and wait (the soft pause worked as a brake in #11, but
   it interrupts a user who asked for one unbroken run)?
4. **Nudge channel.** If Phase 4 is built: UserPromptSubmit only, or also
   PostToolBatch, which reaches long autonomous turns at the price of a
   hook run per tool batch?
5. **Inline the Resume section.** Phase 2 inlines up to 1,000 characters
   of `## Resume` after a clear or compaction. Acceptable, or pointers
   only?
6. **Testing compaction.** It is not verified that a `claude plugin eval`
   case or a headless `claude -p` session can trigger `/compact`. If
   neither can, Phase 1's retention check runs by hand. Is that acceptable
   for release?
7. **Use of #11's transcripts.** May the measurement tool be run on the two
   sessions behind #11 to set the baseline, with only numbers published?
