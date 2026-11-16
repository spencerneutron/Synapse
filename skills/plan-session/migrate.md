# Split a large PLAN.md into efforts

Use this only when the user asks to split `.claude-work/current/PLAN.md` (or
asks for effort folders in a project that already has a large plan). Nothing
here runs on its own. Every step that changes files waits for the user.

## 1. Propose (read-only)

```
synapse effort migrate > proposal.json
```

Write `proposal.json` outside the repo or in `.claude-work/.tmp/`. The
proposal is JSON with `version`, `source` (the `sha256` and `lines` of
`PLAN.md` and `EXECUTION.md`), `efforts` (one per open unit, a heading or
`Phase` item: `slug`, `title`, `status`, `waiting_on`, and the line ranges
`plan` and `execution`, each a list of `[first, last]`), `history` (the
closed effort for the finished units: `slug`, `title`, `plan`, `execution`),
`fact_candidates` (`line`, `text`) and `notes`.

If `current/` was already split and has not changed since, this step and
step 3 refuse and name the snapshot. Tell the user. Retire `current/`
(step 5), or add `--again` to split it once more (it makes `-2` copies of
every effort, so only on the user's word).

## 2. Confirm with the user

Show the user, in short form:

- the proposed efforts: slug, title, the lines each takes
- the finished units that go to `history`
- where `EXECUTION.md` sections (its `## Resume` among them) would land
- the Fact candidates

Ask for corrections: rename a slug, merge two efforts, move a line range,
assign a part of `EXECUTION.md` to the effort it belongs to. Edit the JSON to
what the user confirms. Lines assigned to no effort go to `history`, so
nothing is lost.

## 3. Apply

```
synapse effort migrate --apply proposal.json
```

It refuses when a file changed since the proposal (hash mismatch), a target
slug already exists, or the proposal is malformed (a bad range, a missing
hash, a title that is not text). Then fix the JSON, or re-run step 1 and
start over. Before it writes anything, it snapshots `current/` into the
archive as `<date>-pre-split`. When it succeeds it leaves `current/` as it
was and records the split in `efforts/.split.json`; step 5 removes that
record.

## 4. Constraints become Facts

A session lists the project's Facts at start, so a repo-wide constraint
belongs there and not in an always-read file. For each constraint the user
confirms:

1. Write the note with `synapse vault create-note` (type `fact`, with the
   project).
2. Embed it with `synapse extract embed-note`.

Keep one effort's own constraints in that effort's PLAN. The constraint
lines also stay in the history effort's PLAN, so nothing depends on this
step succeeding. Only about 20 Facts show at session start: pick repo-wide
ones.

## 5. Retire the old files, on the user's word

`current/` is left as it is: another session may be using it. When the user
says to retire it, run:

```
synapse effort migrate --retire-current
```

It moves the old planning files to `efforts/_closed/<snapshot id>/` and
removes the split record. Until then the index keeps one line about
`current/`.

Finish with `synapse effort resume <slug>` for the effort the user wants to
work on.
