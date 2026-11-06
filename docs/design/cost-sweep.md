# The 2.5.0 sweep: cost and memory hygiene (design)

Status: **approved 2026-11-06 and implemented in 2.5.0.**

Issues: [#10](https://github.com/spencerneutron/Synapse/issues/10)
(PR #12, candidate recall before promoting) and
[#11](https://github.com/spencerneutron/Synapse/issues/11)
(PR #13, the continuation assist design). This document is the frame both
land in. It does not repeat PR #13's platform research; it cites it.

---

## Problem

Issue #11 measured two parallel Opus sessions: main contexts of 605k and
431k tokens, main-session cache reads at 85.6% and 79.3% of each session's
cost (the maintainer's re-measurement in the #11 comments, 2026-11-06 21:28
UTC; the issue body overstated absolute figures about 2.4 times), and the
hands-on work done in the main context (197 Bash, 43 Edit, and 42
PowerShell calls in one session). Every one of those calls re-read the
whole context.

The cause is not the user's workflow. Synapse makes the main session the
default worker in three places:

| Where | What it says | Effect |
|-------|--------------|--------|
| `instructions/core.md`, Session Lifecycle | The Execute row is "(these rules)"; sub-agents are for work that "would blow the context or run serially" | Delegation is an exception the model decides under pressure to finish; it rarely does |
| `skills/plan-session/SKILL.md`, step 7 | "perform one step, validate result, update EXECUTION.md" | The skill addresses the main session as the executor |
| `templates/EXECUTION.md`, `## Next` | Steps carry no role; "owner if it is not the agent" | The agent is assumed to be the main session |

The two open PRs treat symptoms. PR #13 shrinks what the main session
carries; a session that compacts then refills the same way. PR #12 adds one
recall call per candidate in the main session at the end of its life, its
most expensive moment. Neither changes who does the work.

A fourth constraint shapes every fix: `instructions/core.md` holds 8,801 of
its 9,500 characters (AGENTS.md). PR #13's phase 5 wants 510 of the
remaining 699. Rules added issue by issue cannot fit; the core has to be
rewritten once, as a whole, with room left for 2.6.

## Decisions already taken (2026-11-06)

- PR #12 is folded into 2.5.0: merge it, do not tag 2.4.1. Its version
  bump and CHANGELOG header become part of the 2.5.0 entry.
- Slice F (reach: an MCP server, a Linux profile) is deferred.
- Evals are not the cost baseline. `tools/context-cost.py` from PR #13
  (local transcripts, stdlib, numbers only) is.
- The sweep as written here, Appendix A and the Obsidian trim included,
  was approved on 2026-11-06. Implementation and validation run in their
  own session, which ends in one PR against `main`.

---

## Principle: the main session conducts, roles work

The main session is the only context that holds the user's words, the
plan, and the decisions. That is what it is for. Its job list:

- Dialogue with the user; decisions; the Decision Log.
- Writing `PLAN.md` and `EXECUTION.md`, including a role per step.
- Writing briefs; reading reports; verifying claims before reporting.
- Anything that takes a handful of tool calls.

Everything else is a brief for a role (`synapse:implementer`, `verifier`,
`researcher`, `reviewer`, `scout`), which runs at a context of a few
thousand tokens on a cheaper model. A run-test, read-log, fix loop is the
canonical case: it is the loop #11's sessions ran in the main context.

The rule needs a trigger the model can apply without judgment: **a step
that needs more than about five tool calls, or reading more than three
files, is a brief, not a step.** The numbers are a starting point for the
open question below.

## Goals and non-goals

Goals:

- The main session's share of cost falls from 79 to 100 percent (seven
  sessions, two machines) to under half, measured by `tools/context-cost.py` on long sessions.
- Nothing the user said is lost at compaction, `/clear`, or extraction.
- The end of a session needs no more user turns than today (one: step 8
  of extraction).
- `core.md` ends at 9,000 characters or fewer, so 2.6 has room.

Non-goals:

- Ending sessions early (rejected in #11).
- Slice F.
- A store schema change; `synapse recall-check` must give the same results
  before and after.
- New eval infrastructure. Existing tags cover the rule change; one new
  case is enough.

---

## Change 1: rewrite `instructions/core.md` around dispatch

### What

One rewrite, not a patch. The sections `Core Operating Principles`,
`Planning Discipline`, `Repository Exploration and Execution`, and
`Validation Requirements` overlap (plan first, smallest step, explore
before assuming, every change carries a run path). They fold into one
`Execution` section that states each rule once. The space pays for:

- **Session Lifecycle table.** The Execute row becomes "Briefs to roles;
  the main session runs what takes a handful of calls".
- **Sub-agents and Waves** rewritten at the top: the main session's job
  list, the five-calls, three-files trigger, and the loop bullet from
  PR #13 phase 5 (a run-test, read-log, fix loop goes to
  `synapse:implementer` with the failing command, the done condition, and
  an attempt limit; read its report, not the logs). The role table and
  the model rules stay as they are.
- **Token / Context Discipline** gains one bullet: "When the user states a
  fact or a decision, write it to `PLAN.md` before the next step." This
  makes the planning files the source of truth for Change 4 and for
  compaction.
- **Parallel Tool Use** folds into `Execution` as one paragraph.
  **Knowledge Integration (Obsidian)** shrinks to one sentence under
  Planning Files.

PR #13's Checkpoint row and checkpoint bullet are not in this rewrite:
they ship with the skill in 2.6.0, into the room this rewrite leaves.

Budget: the drafts in Appendix A land at about 8,100 characters after
`python3 tools/build_context.py`, against 8,801 today. 2.6.0's checkpoint
text needs about 300.

### Cost and risk

- Briefs are output tokens (5x), but written at a small context, and a
  brief replaces tens of main-session calls at 0.1x of a large context.
  Break-even is a few calls.
- Over-delegation: a two-call fix sent to an agent costs a round trip and
  a report for nothing. The "handful of calls" clause and the trigger
  numbers keep quick things in the main session.
- Sonnet on a hard loop: the implementer stops after two failed
  validations, and the escalation rule (one tier after two failures)
  already exists. The brief carries an attempt limit.
- Teams: a teammate's session gets the same default without knowing the
  role names, because the plan names them (Change 2).

### Measurement

- Evals: `delegate-and-verify`, `implement-with-validation`,
  `general-purpose-brief`, `scout-inventory`, `verify-before-done` already
  exist. One new case, `loop-goes-to-implementer`: a prompt with a failing
  test and a fix that takes three attempts; graders: an implementer
  dispatch happened, and the main transcript has fewer than five Edit
  calls (`arm: with-only`).
- `tools/context-cost.py`: main share of cache reads and mean context per
  request on the next two long sessions, against #11's two.

## Change 2: a role per step in `EXECUTION.md` and plan-session

### What

- `templates/EXECUTION.md`, `## Next`: each step names who runs it.
  Example: `1. [ ] Make the e2e workflow run on a schedule — implementer`,
  `2. [ ] Confirm the schedule fired — verifier`, `3. [ ] Decide the
  cadence with the user — main`. The template's comment says a step
  without a role is a brief to write, not a step to run.
- `skills/plan-session/SKILL.md`, step 7 becomes: write the brief (goal,
  files, done condition, what is ruled out, run path, attempt limit),
  dispatch, verify the report, log the result in `## Progress log`. The
  skill's output gains a third line: who runs the next step.
- `templates/NOTES.md` gains `## User-stated facts` (one line each, in the
  user's words), filled by `/synapse:end-session` step 4 from `PLAN.md`
  and the conversation. Change 4 reads it.

### Cost and risk

No runtime cost. Users who keep `EXECUTION.md` by hand may omit roles; the
plan-session skill adds them when it reads the file. `examples/` holds real
files from a mature project and stays as it is.

### Measurement

Eval grader on plan-session output: the plan names a role for every step
that is not dialogue (`arm: with-only`), added to an existing core-loop
case rather than a new one.

## Change 3: knowledge on disk (PR #13, phase 1)

PR #13's phase 1 ships in 2.5.0 unchanged: the PreCompact hook
(`synapse compact-guide --hook`) that tells the compaction summary what to
keep, with its never-block guarantees, the doctor check for other
PreCompact hooks, and `tools/context-cost.py`. The `PLAN.md` rule in
Change 1 is what makes phase 1 cheap: the summary can point at the file
instead of restating it.

Phases 2 to 4 (resume pointer, `/synapse:checkpoint`, the nudge) wait for
2.6.0, after the measurement tool has a baseline.

## Change 4: the end of a session runs in fresh contexts

### What

`/synapse:extract-session` is 19,064 characters of skill text plus the
archive, read into the largest context of the session, followed by PR #12's
one recall per candidate. The judgment it needs (what is a Decision, what
supersedes what) does not need the conversation: the archive is on disk,
and with Change 2 the user's stated facts are in `NOTES_<id>.md`.

Three pieces:

1. **`synapse extract check-candidates`**, a new CLI subcommand. Input: a
   JSON file of candidates, each with `type` (decision, fact, pattern),
   `title`, and `concept` (the query PR #12 defines: the subject without
   the choice). Output: per candidate, the local hits scoring 0.70 or more
   (`--scope local`, top 3, the extracted session's own id excluded), with
   title, score, session id, and snippet. One process, one embedding call
   per candidate, no model calls. It replaces PR #12's loop of `synapse
   recall` calls; PR #12's judgment rules (same concept and different
   choice is `supersedes`; same choice is a duplicate; Patterns never
   supersede) move unchanged into the extractor's body.
2. **`agents/extractor.md`**, a sixth role on Sonnet, tools `Read, Grep,
   Glob, Bash`. The brief names the store folder, the session id, and the
   project. The agent reads the archive, runs steps 2 to 7 of today's
   skill (candidates, `check-candidates`, the note specs), writes the
   specs as Markdown files into a folder from `mktemp -d`, and reports
   the step 8 summary with the folder's path. It never writes to the
   vault, the archive, or the DB. Verified 2026-11-06: a sub-agent's Bash
   finds `synapse` on PATH (`command -v synapse` printed the plugin's
   `bin/synapse`).
3. **`skills/extract-session/SKILL.md` becomes the orchestration**, under
   4,000 characters: step 1 (locate the archive, `synapse vault verify`),
   dispatch the extractor, show its summary to the user (step 8, the one
   question), then on approval run `synapse vault create-note --from-md`
   on the approved spec files, `synapse extract embed-note` once, and
   `synapse extract embed-archive`. The extraction rules the main session no
   longer needs leave the skill; sub-agents never see skills, so they go
   into the agent body (AGENTS.md: "put the rules a role needs in its
   body").

The main session's end of life then costs about six CLI calls and one
report, instead of the archive read, 19k of skill text, and a recall call
per candidate.

### Cost and risk

- The extractor's context is the archive plus the agent body: tens of
  thousands of tokens at most, on Sonnet.
- Lost conversational context: a Fact "stated or confirmed" only in
  conversation is invisible to the extractor. Change 1's `PLAN.md` rule
  and Change 2's `## User-stated facts` close this; `/synapse:end-session`
  step 4 is the last chance and says so in its text.
- `--force` re-runs: the extractor gets the session id and excludes it from
  hits, as PR #12 does.
- Windows: the spec files are plain Markdown (2.3.2's `--from-md`), so
  nothing is escaped twice.

### Measurement

- `synapse recall-check` on the golden set before and after: identical, as
  there is no retrieval change.
- Unit tests for `check-candidates` on a throwaway store
  (`SYNAPSE_HOME=$(mktemp -d) bin/synapse setup`): threshold, own-session
  exclusion, empty result.
- A live check like `tools/live-check-share.sh` (about $0.30 a run): a
  headless session with a fixture archive, the extractor's summary names
  the planted supersession.

## Change 5 (2.6.0): extraction with no session turn at all

Later, not in the sweep. Notes written with status `proposed` by a
headless run (`claude -p` with this plugin, as the live checks do) after
`/synapse:end-session`, listed at the next session start ("3 proposed
notes await review"), shown by recall with a `proposed` label, and
approved per note when the user wants. It keeps per-note approval, which
`/synapse:share` depends on, and removes the extraction from the session
tail entirely. It needs Change 4 first.

---

## Sequencing

2.5.0, in implementation order (each step validated on its own):

1. `synapse extract check-candidates` with unit tests. No skill change yet.
2. `agents/extractor.md`; rewrite `skills/extract-session/SKILL.md` to
   dispatch it (PR #12's step 5b moves into the agent). Live check.
3. `templates/EXECUTION.md`, `templates/NOTES.md`, `skills/plan-session`,
   `skills/end-session` step 4.
4. `instructions/core.md` rewrite as in Appendix A (PR #13 phase 5's loop
   bullet included, its checkpoint text deferred to 2.6.0);
   `python3 tools/build_context.py`; about 8,100 characters.
5. PR #13 phase 1: the PreCompact hook, the doctor check, the INSTALL.md
   preflight row, `tools/context-cost.py`.
6. CHANGELOG 2.5.0 (absorbing PR #12's 2.4.1 entry), `plugin.json`,
   `docs/architecture.md` (the V2 status table gains a Cost row), README.

Checks before release: `python3 -m unittest discover -s tests`,
`python3 tools/build_context.py --check`, `claude plugin validate .
--strict`; evals only when asked: the five cases named under Change 1 and
the new one, about $1 for one run each.

2.6.0: PR #13 phases 2 and 3 (resume pointer, checkpoint), then phase 4
only if users do not checkpoint on their own; Change 5.

## Measurement plan

| What | Tool | Before | After |
|------|------|--------|-------|
| Main share of cache reads | `tools/context-cost.py` | #11's two sessions (85.6%, 79.3%) | The next two long sessions on 2.5.0; target under 50% |
| Mean context per main request | same | 366k, 261k | Reported; no target until a baseline exists |
| Retrieval unchanged | `synapse recall-check` | golden set | identical |
| Rules hold | the evals named under Change 1 | current pass rate | no regression; the new case passes with Synapse |

Retention (nothing lost at compaction) is PR #13's measurement and stays
there.

## Open questions

1. **Trigger numbers.** Five tool calls and three files: right for the
   rule, or should it be stated as "any run-test-fix loop" only?
2. **The Obsidian section.** Resolved 2026-11-06: it shrinks to the one
   sentence in Appendix A; the advice to use the Obsidian CLI directly
   between extractions goes.
3. **Extractor model.** Sonnet for the whole extraction, or Haiku for
   candidates and Sonnet for the specs? One agent on Sonnet is simpler.
4. **`## User-stated facts` in NOTES** or only the `PLAN.md` rule? Both is
   safest; the NOTES section is the one the extractor reads.
5. **PR #12's merge order.** Merge it first and let step 2 above move its
   step 5b, or hold it and merge its logic through step 2? Merging first
   keeps the review history.

---

## Appendix A: the `core.md` fold

Section sizes today (characters, each with its separator), what happens
to each, and the eval graders whose outcomes rest on its text:

| Section | Size | Action | Graders that rest on it |
|---------|------|--------|-------------------------|
| Session Lifecycle | 785 | Keep; Execute row reworded (+17) | none |
| Core Operating Principles | 279 | Fold into `Execution` | none |
| Planning Discipline | 360 | Fold into `Execution` | none |
| Planning Files | 926 | Keep | none |
| Repository Exploration and Execution | 309 | Fold into `Execution` | `scope-discipline` (utils and README untouched); `general-purpose-brief` (the brief limits scope) |
| Validation Requirements | 418 | Fold into `Execution`; second paragraph near verbatim | `hidden-second-suite` (documented checks run after the last edit, reported truthfully); `verify-before-done`; `implement-with-validation`; `delegate-and-verify` and `general-purpose-brief` (the brief names a run path and an expected result) |
| Token / Context Discipline | 241 | Keep; one bullet added (+91) | none |
| Parallel Tool Use | 319 | Fold into `Execution` | none |
| Sub-agents and Waves | 2,047 | Replace the first two bullets (298 out, 539 in); the role table and model rules unchanged | `delegate-and-verify`, `general-purpose-brief` (briefs carry the rules); `scout-inventory`, `reviewer-minimum`, `verify-claims`, `review-planted-bug` (the role table) |
| Local Knowledge Recall | 1,941 | Keep | the `memory-*` cases, `team-conflict`, `superseded-decision` |
| Emission | 329 | Keep | `answer-first` |
| Knowledge Integration (Obsidian) | 334 | One sentence under Planning Files (139) | none |
| Failure Handling and Scope | 215 | Fold into `Execution` | `scope-discipline` |

No grader quotes rule text; each tests an outcome: files outside the task
untouched, the documented checks run after the last edit and reported
truthfully, a brief that limits scope and names a run path with its
expected result. The folded text keeps every phrase those outcomes rest
on: smallest change, no speculative or unrelated refactors, no scope
beyond the stated objective, the run path, expected outcome, and failure
signal triad, and the documented-checks paragraph.

### Draft: `## Execution` (1,059 characters; replaces 1,900)

```markdown
## Execution

Plan before changing anything: name the objective, search the repository
for the conventions and similar code it already has, and write the steps.
Each step is the smallest change that meets the objective, localized and
observable; reuse what exists before adding structure. No speculative or
unrelated refactors, and no scope beyond the stated objective. Re-evaluate
after each step, and stop when uncertainty is high: log the blocker in
`PLAN.md` instead of widening the work.

Every change carries a run path (a test, build, or command), an expected
outcome, and a failure signal. Before calling a change done, run the
project's own documented checks (CONTRIBUTING, the README, `Makefile` or
task-runner targets, CI config), not only the default test runner, and say
which ran. If one cannot run, say so instead of calling the change done.

Batch independent reads, searches, and commands into one call. Do not batch
when a call depends on an earlier result, for destructive operations, or
when batching hides which call produced what.
```

### Draft: Sub-agents and Waves, first bullets (539 characters; replace 298)

```markdown
- Once the plan is set, the main session conducts: dialogue, decisions, the
  planning files, briefs, and reading reports. It keeps work that takes a
  handful of calls. A step that needs more than about five tool calls or
  three files is a brief for a role, not a step to run here: each
  main-session call re-reads the whole context.
- Hand a run-test, read-log, fix loop to `synapse:implementer` with the
  failing command, the done condition, and an attempt limit; read its
  report, not the logs.
- Independent briefs run as a wave.
```

The bullets that follow today ("Brief every agent", worktree isolation,
"Treat every result as a claim", Models, Interrupted runs) stay.

### Draft: Token / Context Discipline, added bullet (91 characters)

```markdown
- When the user states a fact or a decision, write it to `PLAN.md` before
  the next step.
```

### Draft: Obsidian, one sentence under Planning Files (139 characters; replaces 334)

```markdown
The store's Obsidian vault holds durable knowledge; `/synapse:extract-session`
writes it as summaries, never raw logs or transient output.
```

### Budget

| Step | Characters |
|------|-----------|
| Today | 8,801 |
| Remove the five folded sections and Parallel Tool Use | -1,900 |
| Add `Execution` | +1,059 |
| Sub-agents bullets | +241 |
| Token bullet | +91 |
| Execute row | +17 |
| Obsidian section to one sentence | -195 |
| **2.5.0** | **8,114** |
| 2.6.0: Checkpoint row and bullet (PR #13 phase 5) | about +300 |
| After 2.6.0 | about 8,400 |

The counts come from the draft files; `python3 tools/build_context.py` is
the check that matters. The platform files are unchanged.
