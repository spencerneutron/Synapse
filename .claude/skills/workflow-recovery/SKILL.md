---
name: workflow-recovery
description: Recover completed work from a background Workflow that died, was paused, or crossed a session boundary — harvest finished agents' results from the run's on-disk journal instead of re-running (and re-paying for) the whole fleet, then run only the missing tail.
---

# Workflow Recovery Skill

## Purpose

A multi-agent Workflow run persists every agent's lifecycle to disk as it
goes. When a run is interrupted — session exit, user pause, usage-limit
hard stop — the completed agents' full return values are still sitting in
that run's journal even though the harness may report the run as stopped
with no result. This skill recovers them and finishes only what's
actually missing, instead of re-running (and re-paying for) the fleet.

---

## Facts that make recovery work (verify, don't assume)

These are behavioral invariants; exact file layouts may drift, so treat
paths as search patterns and always inspect one line/file before parsing
in bulk.

- **Every run has a transcript directory** keyed by its run id (`wf_…`),
  under the *project's session directories*:
  `~/.claude/projects/<project-slug>/<session-id>/subagents/workflows/<run-id>/`
  Find it by globbing for the run id across all session dirs of the
  project — do not assume the current session's dir.
- **`journal.jsonl` is the ledger.** Lines are lifecycle events per
  agent; the important distinction is *started* events vs *result*
  events, and result events carry the agent's **full structured return
  value**. Started-without-result = the agent was culled mid-flight.
- **Per-agent transcripts** (`agent-<id>.jsonl`) hold the complete
  conversation. The first user-type line contains the agent's **original
  prompt verbatim** — this is how you attribute an anonymous journal
  result to its task, and how you seed a continuation agent without
  reconstructing anything.
- **Resume is same-session-only.** `Workflow({resumeFromRunId})` replays
  cached agents from the *current session's* journal. After a session
  boundary (crash, compaction restart, new process) the resume starts a
  fresh journal, sees nothing, and re-runs — and re-bills — everything.
  A "no completion record found" notification for a run you know did
  work is the tell.
- **Pausing/stopping does not stop in-flight agents.** Requests already
  at the API run to completion and may still write results to the
  journal *after* the stop. Always harvest even a deliberately-killed
  run — it usually finished more than the stop implies.
- **The same run id can have transcript dirs under several sessions**
  (original + resume attempts). Harvest every dir that has result
  lines; the fresh resume's dir is often empty.

## When to use

- A background workflow's task notification says stopped / no completion
  record, but its agents had visible progress.
- A resume re-ran agents you know had completed (session boundary).
- Agents died on usage limits (`session limit` errors) partway through.
- Before ANY re-launch of an interrupted workflow — harvest first, then
  decide what's actually left.

## Procedure

1. **Locate.** Glob for the run id under the project's session dirs.
   List candidates and check each `journal.jsonl` line count.
2. **Inspect one line, then parse.** Read the first few journal lines to
   confirm the current event shapes, then tally per agent: started,
   completed-with-result, culled. Print completed results grouped by
   shape (your workflow's own schemas tell you which stage each result
   belongs to).
3. **Attribute if needed.** For anonymous results or culled agents, read
   the first user-type line of the matching `agent-<id>.jsonl` to
   recover the original prompt/task.
4. **Decide the gap.** Often the harvested results are enough — finish
   remaining verification inline in the main loop (costs no subagent
   budget) rather than re-running a verify fleet. Only spawn agents for
   work that genuinely didn't complete.
5. **Continuation run (when warranted).** Author a NEW small workflow
   for just the culled tail. Seed each agent with its predecessor's
   transcript path and instruct it to (a) read its original assignment
   from the transcript's first user line, (b) skim the partial reasoning
   as hints, never as conclusions. If the repo changed since the
   original run (fixes landed, commits made), say so in the prompt and
   redefine the verdict space accordingly — an agent judging stale
   claims against new code produces garbage unless told the tree moved.
6. **Spend discipline.** If limits killed the original: batch the
   continuation (e.g. groups of 4 with a barrier), stop the loop when a
   whole batch returns empty, and consider a cheaper model for the
   workers — or inline main-loop verification, which draws no subagent
   budget at all.

## Rules

- Harvest before any re-launch; never resume across a session boundary
  expecting cache hits.
- Treat partial transcripts as leads, not verdicts.
- Record the recovery outcome (what was salvaged, what re-ran, what it
  cost) in the session's EXECUTION.md progress notes.
